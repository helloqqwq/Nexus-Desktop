"""本地语音识别：sherpa-onnx + SenseVoice-Small（int8），不依赖系统语音功能。"""
from __future__ import annotations

import logging
import re
import shutil
import tarfile
import threading
import urllib.request
from pathlib import Path
from typing import Callable

log = logging.getLogger("nexus.asr")

MODEL_DIR_NAME = "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17"
MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
    + MODEL_DIR_NAME
    + ".tar.bz2"
)
HF_BASE = (
    "https://hf-mirror.com/csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"
    "/resolve/main"
)
HF_FILES = (("model.int8.onnx", 228.0), ("tokens.txt", 0.3))
TAG_RE = re.compile(r"<\|[^|]*\|>")


class SpeechRecognizer:
    """管理 SenseVoice 模型的下载、加载与识别。"""

    def __init__(self, data_dir: Path,
                 on_progress: Callable[[int, str], None] | None = None):
        self.root = Path(data_dir) / "models" / MODEL_DIR_NAME
        self.on_progress = on_progress
        self._recognizer = None
        self._lock = threading.Lock()
        self._downloading = False

    def ready(self) -> bool:
        return (self.root / "model.int8.onnx").is_file() and (self.root / "tokens.txt").is_file()

    def downloading(self) -> bool:
        return self._downloading

    def _report(self, percent: int, text: str) -> None:
        if self.on_progress:
            try:
                self.on_progress(max(0, min(100, int(percent))), text)
            except Exception:
                pass

    def _fetch(self, url: str, dest: Path, on_ratio) -> None:
        req = urllib.request.Request(url, headers={"User-Agent": "Nexus/1.0"})
        with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as fh:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                if total:
                    on_ratio(min(1.0, done / total))

    def _download_hf(self) -> bool:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            total_weight = sum(w for _, w in HF_FILES)
            finished = 0.0
            for name, weight in HF_FILES:
                dest = self.root / name
                part = dest.with_name(dest.name + ".part")
                base = finished

                def progress(frac, base=base, weight=weight):
                    self._report(int((base + frac * weight) * 96 / total_weight),
                                 "正在下载语音模型")

                self._fetch(f"{HF_BASE}/{name}", part, progress)
                part.replace(dest)
                finished += weight
            self._report(100, "语音模型已就绪")
            return self.ready()
        except Exception:
            log.warning("hf-mirror 下载失败", exc_info=True)
            return False

    def _download_tar(self) -> bool:
        tmp = self.root.parent / (MODEL_DIR_NAME + ".tar.bz2")
        try:
            self.root.parent.mkdir(parents=True, exist_ok=True)
            self._fetch(MODEL_URL, tmp,
                        lambda r: self._report(int(r * 96), "正在下载语音模型"))
            self._report(98, "正在解压语音模型")
            with tarfile.open(tmp, "r:bz2") as tar:
                members = [m for m in tar.getmembers()
                           if m.name.startswith(MODEL_DIR_NAME + "/")]
                tar.extractall(self.root.parent, members=members)
            extracted = self.root.parent / MODEL_DIR_NAME
            if extracted != self.root and extracted.is_dir():
                if self.root.exists():
                    shutil.rmtree(self.root)
                extracted.rename(self.root)
            self._report(100, "语音模型已就绪")
            return self.ready()
        except Exception:
            log.warning("GitHub 模型下载失败", exc_info=True)
            return False
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass

    def ensure_model(self) -> bool:
        """下载并解压模型；已存在时直接返回。"""
        if self.ready():
            return True
        if self._downloading:
            return False
        self._downloading = True
        try:
            self._report(0, "正在下载语音模型")
            if self._download_hf():
                return True
            if self._download_tar():
                return True
            self._report(0, "语音模型下载失败")
            return False
        finally:
            self._downloading = False

    def recognize(self, samples) -> str:
        """samples: 16kHz 单声道 float32（-1~1）。"""
        if not self.ready():
            return ""
        try:
            import sherpa_onnx
        except ImportError:
            log.warning("未安装 sherpa-onnx，无法本地识别")
            return ""
        with self._lock:
            if self._recognizer is None:
                self._recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                    model=str(self.root / "model.int8.onnx"),
                    tokens=str(self.root / "tokens.txt"),
                    num_threads=2,
                    use_itn=True,
                    language="auto",
                    debug=False,
                )
            stream = self._recognizer.create_stream()
            stream.accept_waveform(16000, samples)
            self._recognizer.decode_stream(stream)
            text = (stream.result.text or "").strip()
        return TAG_RE.sub("", text).strip()

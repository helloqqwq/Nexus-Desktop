"""更新检查与安装。

两种更新源，按优先级选择：
1. 自建更新服务（`update.base_url`）：读取该地址下的 update.json，安装包与清单同源；
2. GitHub Releases（`update.repo`）：读取 latest release 的资产。

下载完成后写一个独立的 PowerShell 脚本，等 Nexus 退出后再替换文件并重启。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .config import Config
from .i18n import t

CACHE_SECONDS = 6 * 3600
USER_AGENT = "Nexus/0.2"
MANIFEST_NAME = "update.json"



def parse_version(value: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", str(value or ""))
    return tuple(int(n) for n in nums[:4]) or (0,)


def is_newer(latest: str, current: str) -> bool:
    return parse_version(latest) > parse_version(current)


def normalize_repo(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^https?://github\.com/", "", text, flags=re.I)
    text = re.sub(r"\.git$", "", text, flags=re.I)
    text = text.strip("/")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", text):
        return ""
    return text


def is_portable() -> bool:
    if not getattr(sys, "frozen", False):
        return False
    return (Path(sys.executable).resolve().parent / "portable.flag").exists()


def manifest_url(base: str) -> str:
    """把用户填写的更新服务地址规范成清单地址。"""
    text = str(base or "").strip().rstrip("/")
    if not text:
        return ""
    if text.lower().endswith(".json"):
        return text
    return text + "/" + MANIFEST_NAME


def manifest_update(data: dict, base_url: str, current: str) -> dict:
    """把 update.json 转成与 GitHub 检查一致的结果结构（纯函数，便于自检）。"""
    latest = str(data.get("version") or "").lstrip("vV")
    current = str(current or "")
    note = str(data.get("notes") or "")
    raw = data.get("installer") if isinstance(data.get("installer"), dict) else {}
    name = str(raw.get("name") or "")
    target = str(raw.get("url") or "")
    url = urllib.parse.urljoin(manifest_url(base_url), target) if target else ""
    sha = str(raw.get("sha256") or "").strip().lower()
    if sha.startswith("sha256:"):
        sha = sha[7:]
    result = {
        "ok": True,
        "source": "manifest",
        "current": current,
        "latest": latest or current,
        "tag": ("v" + latest) if latest else "",
        "notes": note[:12000],
        "simulate": bool(data.get("simulate")),
        "page": "",
        "has_update": False,
    }
    if not latest or not is_newer(latest, current):
        return result
    if not name or not url:
        return {
            "ok": False,
            "source": "manifest",
            "error": t("更新清单缺少安装包信息", "Update manifest has no installer entry"),
        }
    if not url.lower().startswith("https://"):
        return {
            "ok": False,
            "source": "manifest",
            "error": t("更新包地址必须是 https 链接", "Update package URL must use https"),
        }
    result.update({
        "has_update": True,
        "kind": "installer",
        "asset_name": name,
        "asset_url": url,
        "asset_size": int(raw.get("size") or 0),
        "digest": ("sha256:" + sha) if sha else "",
    })
    return result


class Updater:
    def __init__(self, config: Config):
        self.config = config

    @property
    def repo(self) -> str:
        return normalize_repo(str(self.config.get("update.repo") or ""))

    @property
    def base_url(self) -> str:
        return str(self.config.get("update.base_url") or "").strip()

    def enabled(self) -> bool:
        return bool(self.base_url or self.repo)

    def _request(self, url: str) -> urllib.request.Request:
        return urllib.request.Request(url, headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
        })

    def check(self, force: bool = False) -> dict:
        if self.base_url:
            return self._check_manifest(force)
        return self._check_github(force)

    def _check_manifest(self, force: bool = False) -> dict:
        current = self._current_version()
        last = float(self.config.get("update.last_check") or 0)
        if not force and time.time() - last < CACHE_SECONDS:
            return {"ok": True, "has_update": False, "cached": True,
                    "current": current, "source": "manifest"}
        url = manifest_url(self.base_url)
        try:
            request = urllib.request.Request(url, headers={
                "Accept": "application/json",
                "Cache-Control": "no-cache",
                "User-Agent": USER_AGENT,
            })
            with urllib.request.urlopen(request, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            message = t(f"检查更新失败（HTTP {e.code}）", f"Update check failed (HTTP {e.code})")
            if e.code == 404:
                message = t("更新服务上没有 update.json", "update.json was not found on the update service")
            return {"ok": False, "source": "manifest", "error": message}
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
            return {"ok": False, "source": "manifest",
                    "error": t(f"检查更新失败：{e}", f"Update check failed: {e}")}

        self.config.set("update.last_check", int(time.time()))
        self.config.save()
        info = manifest_update(data, self.base_url, current)
        if info.get("ok") and info.get("has_update"):
            info["skipped"] = str(self.config.get("update.skipped_version") or "") == info.get("latest")
        return info

    def _check_github(self, force: bool = False) -> dict:
        repo = self.repo
        if not repo:
            return {"ok": False, "error": t(
                "还没有配置 GitHub 更新仓库，请在设置中填写 owner/repo。",
                "No GitHub update repository configured. Enter owner/repo in Settings.",
            )}
        last = float(self.config.get("update.last_check") or 0)
        if not force and time.time() - last < CACHE_SECONDS:
            return {"ok": True, "has_update": False, "cached": True,
                    "current": self._current_version()}
        try:
            with urllib.request.urlopen(
                self._request(f"https://api.github.com/repos/{repo}/releases/latest"),
                timeout=12,
            ) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            message = t(f"检查更新失败（HTTP {e.code}）", f"Update check failed (HTTP {e.code})")
            if e.code == 404:
                message = t("GitHub 仓库或 Release 不存在", "GitHub repository or release not found")
            elif e.code == 403:
                message = t("GitHub API 请求受限，请稍后再试", "GitHub API rate limit reached")
            return {"ok": False, "error": message}
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
            return {"ok": False, "error": t(f"检查更新失败：{e}", f"Update check failed: {e}")}

        self.config.set("update.last_check", int(time.time()))
        self.config.save()
        current = self._current_version()
        tag = str(data.get("tag_name") or data.get("name") or "")
        latest = tag.lstrip("vV")
        page = str(data.get("html_url") or f"https://github.com/{repo}/releases")
        notes = str(data.get("body") or "")[:12000]
        if not latest or not is_newer(latest, current):
            return {"ok": True, "has_update": False, "current": current,
                    "latest": latest, "page": page}

        kind = "portable" if is_portable() else "installer"
        asset = self._pick_asset(data.get("assets") or [], kind, latest)
        skipped = str(self.config.get("update.skipped_version") or "")
        return {
            "ok": True,
            "has_update": True,
            "current": current,
            "latest": latest,
            "tag": tag,
            "notes": notes,
            "page": page,
            "kind": kind,
            "asset_name": asset.get("name", ""),
            "asset_url": asset.get("browser_download_url", ""),
            "asset_size": int(asset.get("size") or 0),
            "digest": str(asset.get("digest") or ""),
            "skipped": skipped == latest,
        }

    def _current_version(self) -> str:
        try:
            from app import __version__
        except Exception:
            __version__ = "0.0.0"
        return str(__version__)

    @staticmethod
    def _pick_asset(assets: list, kind: str, version: str) -> dict:
        if kind == "portable":
            patterns = (r"^Nexus-Portable-.*\.zip$", r"^Nexus-Portable.*\.zip$")
        else:
            patterns = (r"^Nexus-Setup-.*\.exe$", r"^Nexus-Setup.*\.exe$")
        for pattern in patterns:
            for asset in assets:
                name = str(asset.get("name") or "")
                if re.fullmatch(pattern, name, flags=re.I):
                    return asset
        # 名称不完全匹配时，退而选择包含版本号和正确后缀的资产
        suffix = ".zip" if kind == "portable" else ".exe"
        for asset in assets:
            name = str(asset.get("name") or "")
            if name.lower().endswith(suffix) and version in name:
                return asset
        return {}

    def download(self, asset_url: str, asset_name: str, progress=None,
                 digest: str = "") -> Path:
        if not asset_url.lower().startswith("https://"):
            raise ValueError(t("更新下载地址必须是 https 链接", "The update URL must use https"))
        folder = Path(tempfile.mkdtemp(prefix="nexus-update-"))
        safe_name = Path(str(asset_name or "")).name or "Nexus-Update.bin"
        target = folder / safe_name
        request = urllib.request.Request(asset_url, headers={"User-Agent": USER_AGENT})
        hasher = hashlib.sha256()
        done = 0
        with urllib.request.urlopen(request, timeout=30) as resp, target.open("wb") as fh:
            total = int(resp.headers.get("Content-Length") or 0)
            while True:
                block = resp.read(256 * 1024)
                if not block:
                    break
                fh.write(block)
                hasher.update(block)
                done += len(block)
                if progress:
                    progress(done, total)
        expected = ""
        if digest.startswith("sha256:"):
            expected = digest[7:].lower()
        if expected and hasher.hexdigest().lower() != expected:
            target.unlink(missing_ok=True)
            raise ValueError(t("更新包校验失败，请重试", "Update package checksum failed"))
        return target

    def install(self, path: Path) -> None:
        """启动独立更新脚本；调用方随后应立即退出 Nexus。"""
        app_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path.cwd()
        kind = "portable" if is_portable() else "installer"
        script = Path(tempfile.mkdtemp(prefix="nexus-updater-")) / "apply.ps1"
        script.write_text(self._script(kind), encoding="utf-8")
        flags = 0
        if os.name == "nt":
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
        subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", str(script), "-ProcessId", str(os.getpid()),
             "-Package", str(path), "-AppDir", str(app_dir), "-Kind", kind],
            creationflags=flags,
            close_fds=True,
        )

    @staticmethod
    def _script(kind: str) -> str:
        # 绿色包会保留 data 目录和 portable.flag；安装包使用 NSIS 静默安装。
        return r"""
param(
  [int]$ProcessId,
  [string]$Package,
  [string]$AppDir,
  [string]$Kind
)
$ErrorActionPreference = 'SilentlyContinue'
Wait-Process -Id $ProcessId -Timeout 30
Start-Sleep -Milliseconds 900
if ($Kind -eq 'installer') {
  Start-Process -FilePath $Package -ArgumentList '/S' -Wait
  Start-Sleep -Milliseconds 800
  $install = (Get-ItemProperty -Path 'HKCU:\Software\Nexus' -Name InstallDir).InstallDir
  if ($install) { $AppDir = $install }
  Start-Process -FilePath (Join-Path $AppDir 'Nexus.exe')
} else {
  $temp = Join-Path $env:TEMP ('nexus-portable-' + [guid]::NewGuid().ToString('N'))
  Expand-Archive -Path $Package -DestinationPath $temp -Force
  $src = Get-ChildItem -Path $temp -Directory | Select-Object -First 1
  if ($null -eq $src) { $src = Get-Item $temp }
  for ($i = 0; $i -lt 5; $i++) {
    robocopy $src.FullName $AppDir /E /XD (Join-Path $AppDir 'data') /XF (Join-Path $AppDir 'portable.flag') | Out-Null
    if ($LASTEXITCODE -lt 8) { break }
    Start-Sleep -Seconds 1
  }
  Start-Process -FilePath (Join-Path $AppDir 'Nexus.exe')
  Remove-Item $temp -Recurse -Force
}
Remove-Item $Package -Force
Remove-Item $PSCommandPath -Force
""".strip()

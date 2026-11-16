"""配置读写与 Windows DPAPI 密钥加密。

数据目录优先级：
1. 环境变量 NEXUS_HOME（调试 / 测试用）
2. 可执行文件同级存在 portable.flag -> ./data
3. %APPDATA%\\Nexus
"""
from __future__ import annotations

import base64
import copy
import json
import logging
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

from . import providers
from .secret import (
    KeyUnreadable,
    SecretBox,
    SecretError,
    dpapi_decrypt,
    dpapi_encrypt,
)

log = logging.getLogger("nexus.config")

APP_NAME = "Nexus"

DEFAULTS: dict = {
    "llm": {
        "provider": "deepseek",      # 当前厂商 id
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-flash",
        "providers": {},             # id -> {key, base_url, models, name, kind}
        "thinking": "auto",          # auto | enabled | disabled
        "reasoning_effort": "high",  # high | max
        "timeout": 90,
        "max_tokens": 65536,       # 输出上限：64K / 128K 两档
    },
    "ui": {
        "theme": "light",          # light | dark | system
        "accent": "blue",          # blue | green | violet | orange
        "hotkey": "ctrl+alt+space",
        "voice_hotkey": "ctrl+alt+v",
        "autostart": False,
        "language": "zh",          # zh | en | system
        "assistant_name": "Nexus",
        "profile": {
            "name": "",
            "avatar": "default",   # default | custom
            "color": "blue",       # 旧版头像配色，保留兼容
            "avatar_version": 0,
        },
        "notify_done": True,
        "show_api_errors": True,
        "context_limit": 131072,   # 仅两档：128K / 1M
        "context_compress": True,   # 自动压缩（达到档位 50% 触发）
        "onboarded": False,
        "last_seen_version": "",
    },
    "paths": {
        "output_dir": "",
        "extra_dirs": [],
    },
    "mode": "supervised",          # safe | supervised | full
    "privacy": {
        "upload_screenshot": True,
    },
    "prompt": {
        "extra": "",               # 用户附加到系统提示词末尾的指令
    },
    "skills": {
        "auto": True,              # 是否允许模型按描述自动调用技能
    },
    "memory": {
        "enabled": True,           # 是否允许模型写入长期记忆
    },
    "update": {
        # 自建更新服务：读取该地址下的 update.json；优先级高于 GitHub Releases
        "base_url": "https://37jn10d54xg2snsh7sl.traesite.cn",
        "repo": "",                # GitHub owner/repo，留空则不使用 GitHub
        "auto_check": True,
        "skipped_version": "",
        "last_check": 0,
    },
}

# DeepSeek 已于 2026-07-24 停用 deepseek-chat / deepseek-reasoner；
# 旧配置读取时自动迁移到当前模型名，避免用户升级后请求 400。
_MODEL_ALIASES = {
    "deepseek-chat": "deepseek-flash",
    "deepseek-reasoner": "deepseek-flash",
    "deepseek-v4-flash": "deepseek-flash",
    "deepseek-v4-flash-vision-exp": "deepseek-flash",
}

class ConfigError(Exception):
    pass


def _merge(base: dict, patch: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def resolve_data_dir() -> Path:
    env = os.environ.get("NEXUS_HOME")
    if env:
        return Path(env).expanduser().resolve()
    root = _app_root()
    if (root / "portable.flag").exists():
        return root / "data"
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(appdata) / APP_NAME


class Config:
    """配置对象。主密钥由 DPAPI 保护，配置整体 AES-256-GCM 加密落盘。"""

    def __init__(self, data_dir: Path | None = None):
        self.dir = Path(data_dir) if data_dir else resolve_data_dir()
        self.path = self.dir / "config.dat"
        self.recovery_note = ""
        self.box = self._open_box()
        self._data = copy.deepcopy(DEFAULTS)
        self._load()

    def _open_box(self) -> SecretBox:
        try:
            return SecretBox(self.dir)
        except KeyUnreadable:
            # 数据来自其他 Windows 账户/电脑：先完整备份，再以全新状态启动。
            backup = self._backup_stale_data()
            box = SecretBox(self.dir)
            self.recovery_note = (
                "检测到本地数据属于其他 Windows 账户或电脑，无法解密。\n"
                "旧数据已完整备份到：\n"
                f"{backup}\n\n"
                "Nexus 将以全新状态启动。"
            )
            log.warning("数据密钥不可用，旧数据已备份到 %s", backup)
            return box

    def _backup_stale_data(self) -> Path:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup = self.dir / f"backup-{stamp}"
        backup.mkdir(parents=True, exist_ok=True)
        names = ("secret.key", "config.dat", "config.json", "nexus.db",
                 "nexus.db-wal", "nexus.db-shm")
        for name in names:
            src = self.dir / name
            if not src.exists():
                continue
            try:
                shutil.move(str(src), str(backup / name))
            except OSError:
                log.warning("备份旧数据失败：%s", src, exc_info=True)
        return backup

    # ---------- 基础 ----------
    def _load(self) -> None:
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise ConfigError(f"无法创建数据目录：{e}") from e
        legacy = self.dir / "config.json"
        if self.path.exists():
            try:
                raw = json.loads(
                    self.box.decrypt_bytes(self.path.read_bytes()).decode("utf-8")
                )
                self._data = _merge(DEFAULTS, raw)
            except (OSError, json.JSONDecodeError, SecretError) as e:
                raise ConfigError(f"配置文件损坏：{self.path}（{e}）") from e
            # 迁移成功后清掉遗留的明文配置，避免敏感信息长期暴露。
            if legacy.exists():
                try:
                    legacy.unlink()
                except OSError:
                    pass
        elif legacy.exists():
            try:
                raw = json.loads(legacy.read_text(encoding="utf-8"))
                self._data = _merge(DEFAULTS, raw)
            except (OSError, json.JSONDecodeError) as e:
                raise ConfigError(f"配置文件损坏：{legacy}（{e}）") from e
            self.save()
            try:
                legacy.unlink()
            except OSError:
                pass
            log.info("已将明文配置迁移为加密配置 config.dat")
        else:
            self._data["paths"]["output_dir"] = str(self.dir / "files")
            self.save()
            return
        if not self._data["paths"].get("output_dir"):
            self._data["paths"]["output_dir"] = str(self.dir / "files")
        changed = False
        llm = self._data.setdefault("llm", {})
        store = llm.setdefault("providers", {})
        if not isinstance(store, dict):
            store = {}
            llm["providers"] = store
        # 旧版只有一把 Key：迁移成 DeepSeek 厂商配置，保留原有地址与模型。
        legacy_key = llm.pop("api_key", None)
        if legacy_key:
            deep = store.setdefault("deepseek", {})
            if not deep.get("key"):
                deep["key"] = legacy_key
            changed = True
        legacy_base = str(llm.get("base_url") or "").rstrip("/")
        if legacy_base == "https://api.deepseek.com/v1":
            legacy_base = "https://api.deepseek.com"
        if legacy_base and legacy_base != providers.default_base_url("deepseek"):
            deep = store.setdefault("deepseek", {})
            if not deep.get("base_url"):
                deep["base_url"] = legacy_base
                changed = True
        provider_id = str(llm.get("provider") or "deepseek")
        if provider_id not in (providers.BUILTIN_IDS + ("custom",)):
            provider_id = "deepseek"
            changed = True
        if llm.get("provider") != provider_id:
            llm["provider"] = provider_id
            changed = True
        model = str(llm.get("model") or "")
        if model in _MODEL_ALIASES:
            model = _MODEL_ALIASES[model]
            llm["model"] = model
            changed = True
        if not model:
            model = providers.default_model(provider_id)
            llm["model"] = model
            changed = True
        # 保证当前模型出现在该厂商的模型列表里；旧配置里的自定义模型名优先保留。
        models = self.provider_models(provider_id)
        if model and model not in models:
            entry = store.setdefault(provider_id, {})
            if entry.get("key") or entry.get("base_url") or entry.get("models"):
                entry["models"] = [model] + [m for m in models if m != model]
                changed = True
            elif models:
                llm["model"] = models[0]
                changed = True
        base_url = str((store.get(provider_id) or {}).get("base_url")
                       or providers.default_base_url(provider_id) or "").rstrip("/")
        if base_url and llm.get("base_url") != base_url:
            llm["base_url"] = base_url
            changed = True
        # 桌面宠物已移除，只保留悬浮球；旧配置里的 persona 直接清掉。
        ui = self._data.get("ui")
        if isinstance(ui, dict) and "persona" in ui:
            ui.pop("persona", None)
            changed = True
        # 旧版预设头像已移除，统一迁移为默认头像。
        if isinstance(ui, dict):
            profile = ui.get("profile")
            if isinstance(profile, dict) and profile.get("avatar") not in ("default", "custom"):
                profile["avatar"] = "default"
                changed = True
        # 上下文档位收敛为 128K / 1M，旧的自定义值按最接近的档位迁移。
        if isinstance(ui, dict):
            try:
                limit = int(ui.get("context_limit") or 0)
            except (TypeError, ValueError):
                limit = 0
            if limit not in (131072, 1048576):
                ui["context_limit"] = 1048576 if limit >= 600000 else 131072
                changed = True
        # 输出上限收敛为 64K / 128K 两档，旧值按 96K 分界迁移。
        try:
            out = int(llm.get("max_tokens") or 0)
        except (TypeError, ValueError):
            out = 0
        if out not in (65536, 131072):
            llm["max_tokens"] = 131072 if out >= 98304 else 65536
            changed = True
        # 旧的在线/专业模式合并为三级权限，统一回退到监管模式。
        mode = str(self._data.get("mode") or "").lower()
        if mode not in ("safe", "supervised", "full"):
            self._data["mode"] = "supervised"
            changed = True
        if "pro" in self._data:
            self._data.pop("pro", None)
            changed = True
        if changed:
            self.save()

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(self._data, ensure_ascii=False, indent=2).encode("utf-8")
        blob = self.box.encrypt_bytes(raw)
        fd, tmp = tempfile.mkstemp(dir=str(self.dir), prefix=".config-", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(blob)
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def get(self, dotted: str, default=None):
        cur = self._data
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def set(self, dotted: str, value) -> None:
        parts = dotted.split(".")
        cur = self._data
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        cur[parts[-1]] = value

    def update(self, patch: dict) -> None:
        self._data = _merge(self._data, patch or {})

    def as_dict(self) -> dict:
        data = copy.deepcopy(self._data)
        # 不向前端暴露密文
        llm = data.setdefault("llm", {})
        llm.pop("api_key", None)
        for item in (llm.get("providers") or {}).values():
            if isinstance(item, dict):
                item.pop("key", None)
        return data

    def reset_preferences(self) -> None:
        """恢复默认偏好，保留全部厂商 Key、账号资料、语言和引导状态。"""
        providers_data = copy.deepcopy(self.get("llm.providers") or {})
        provider = self.get("llm.provider") or "deepseek"
        model = self.get("llm.model") or "deepseek-flash"
        profile = copy.deepcopy(self.get("ui.profile") or {})
        language = self.get("ui.language") or "zh"
        onboarded = bool(self.get("ui.onboarded"))
        last_seen = self.get("ui.last_seen_version") or ""
        self._data = copy.deepcopy(DEFAULTS)
        self._data["paths"]["output_dir"] = str(self.dir / "files")
        if providers_data:
            self._data["llm"]["providers"] = providers_data
        self._data["llm"]["provider"] = provider
        base = str((providers_data.get(provider) or {}).get("base_url") or "").strip()
        self._data["llm"]["model"] = model
        self._data["llm"]["base_url"] = base or providers.default_base_url(provider)
        self._data["ui"]["profile"] = profile
        self._data["ui"]["language"] = language
        self._data["ui"]["onboarded"] = onboarded
        self._data["ui"]["last_seen_version"] = last_seen
        self.save()

    # ---------- 路径 ----------
    @property
    def db_path(self) -> Path:
        return self.dir / "nexus.db"

    @property
    def output_dir(self) -> Path:
        p = Path(self.get("paths.output_dir") or (self.dir / "files"))
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def log_dir(self) -> Path:
        p = self.dir / "logs"
        p.mkdir(parents=True, exist_ok=True)
        return p

    # ---------- 厂商与密钥 ----------
    def active_provider(self) -> str:
        pid = str(self.get("llm.provider") or "deepseek")
        if pid not in (providers.BUILTIN_IDS + ("custom",)):
            return "deepseek"
        return pid

    def active_model(self) -> str:
        model = str(self.get("llm.model") or "").strip()
        return model or providers.default_model(self.active_provider())

    def provider_data(self, provider_id: str | None = None) -> dict:
        pid = provider_id or self.active_provider()
        item = (self.get("llm.providers") or {}).get(pid)
        return dict(item) if isinstance(item, dict) else {}

    def provider_base_url(self, provider_id: str | None = None) -> str:
        pid = provider_id or self.active_provider()
        base = str(self.provider_data(pid).get("base_url") or "").strip()
        return (base or providers.default_base_url(pid)).rstrip("/")

    def provider_models(self, provider_id: str | None = None) -> list[str]:
        pid = provider_id or self.active_provider()
        saved = self.provider_data(pid).get("models")
        if isinstance(saved, list) and saved:
            return [str(item) for item in saved if str(item).strip()]
        return [str(item["id"]) for item in (providers.get(pid) or {}).get("models") or []]

    @staticmethod
    def _decode_key(enc: str) -> str:
        if not enc:
            return ""
        try:
            if enc.startswith("dpapi:"):
                return dpapi_decrypt(base64.b64decode(enc[6:])).decode("utf-8")
            return str(enc)  # 兼容早期明文
        except (ConfigError, SecretError, ValueError):
            return ""

    def provider_key(self, provider_id: str | None = None) -> str:
        pid = provider_id or self.active_provider()
        if pid == self.active_provider():
            env = os.environ.get("NEXUS_API_KEY", "").strip()
            if env:
                return env
        return self._decode_key(str(self.provider_data(pid).get("key") or ""))

    def provider_has_key(self, provider_id: str | None = None) -> bool:
        return bool(self.provider_key(provider_id))

    def set_provider_key(self, provider_id: str, key: str, save: bool = True) -> None:
        pid = str(provider_id or "").strip()
        if not pid:
            return
        item = self._data.setdefault("llm", {}).setdefault("providers", {}).setdefault(pid, {})
        key = (key or "").strip()
        if not key:
            item["key"] = ""
        else:
            enc = dpapi_encrypt(key.encode("utf-8"))
            item["key"] = "dpapi:" + base64.b64encode(enc).decode("ascii")
        if save:
            self.save()

    def save_provider(self, provider_id: str, patch: dict, save: bool = True) -> None:
        """保存单个厂商的地址、模型列表、自定义名称与协议。Key 走 set_provider_key。"""
        pid = str(provider_id or "").strip()
        if not pid:
            return
        patch = patch or {}
        item = self._data.setdefault("llm", {}).setdefault("providers", {}).setdefault(pid, {})
        if "base_url" in patch:
            item["base_url"] = str(patch.get("base_url") or "").strip().rstrip("/")
        if "models" in patch and isinstance(patch.get("models"), list):
            cleaned: list[str] = []
            for value in patch["models"]:
                name = str(value or "").strip()
                if name and name not in cleaned:
                    cleaned.append(name)
            item["models"] = cleaned
        if providers.is_builtin(pid):
            item.pop("name", None)
            item.pop("kind", None)
        else:
            if "name" in patch:
                item["name"] = str(patch.get("name") or "").strip()[:40]
            if "kind" in patch:
                kind = str(patch.get("kind") or "openai").lower()
                item["kind"] = "anthropic" if kind == "anthropic" else "openai"
        if save:
            self.save()

    def delete_provider(self, provider_id: str, save: bool = True) -> None:
        pid = str(provider_id or "").strip()
        if not pid:
            return
        data = self._data.setdefault("llm", {}).setdefault("providers", {})
        data.pop(pid, None)
        if self.active_provider() == pid:
            candidates = [p for p in (providers.BUILTIN_IDS + ("custom",))
                          if p != pid and self.provider_has_key(p)]
            fallback = candidates[0] if candidates else "deepseek"
            models = self.provider_models(fallback) if fallback else []
            self._data["llm"]["provider"] = fallback or "deepseek"
            self._data["llm"]["model"] = models[0] if models else "deepseek-flash"
            self._data["llm"]["base_url"] = self.provider_base_url(fallback or "deepseek")
        if save:
            self.save()

    def provider_kind(self, provider_id: str | None = None) -> str:
        pid = provider_id or self.active_provider()
        kind = str(self.provider_data(pid).get("kind") or "").lower()
        if pid == "custom":
            return "anthropic" if kind == "anthropic" else "openai"
        return "openai"

    def provider_name(self, provider_id: str | None = None) -> str:
        pid = provider_id or self.active_provider()
        custom = str(self.provider_data(pid).get("name") or "").strip()
        if custom:
            return custom
        return str((providers.get(pid) or {}).get("name") or pid)

    def set_active(self, provider_id: str, model: str = "") -> None:
        pid = str(provider_id or "").strip()
        if pid not in (providers.BUILTIN_IDS + ("custom",)):
            raise ConfigError(f"未知厂商：{pid}")
        models = self.provider_models(pid)
        chosen = str(model or "").strip() or (models[0] if models else "")
        if chosen and models and chosen not in models:
            raise ConfigError(f"{pid} 不支持模型 {chosen}")
        self._data.setdefault("llm", {})
        self._data["llm"]["provider"] = pid
        self._data["llm"]["model"] = chosen
        self._data["llm"]["base_url"] = self.provider_base_url(pid)
        self.save()

    @property
    def api_key(self) -> str:
        return self.provider_key(self.active_provider())

    def set_api_key(self, key: str) -> None:
        self.set_provider_key(self.active_provider(), key)

    def has_key(self, provider_id: str | None = None) -> bool:
        return self.provider_has_key(provider_id)

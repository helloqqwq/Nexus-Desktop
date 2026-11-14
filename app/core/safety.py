"""安全策略：路径沙箱、危险动作确认令牌、审计。"""
from __future__ import annotations

import os
import secrets
import threading
import time
from pathlib import Path

from .config import Config

# 禁止读取的敏感位置（按小写片段匹配）
DENY_READ_PARTS = (
    "\\.ssh", "\\id_rsa", "\\id_ed25519", "\\cookies", "\\login data",
    "\\web data", "\\local state", "\\microsoft\\credentials",
    "\\microsoft\\protect", "\\ntuser.dat",
)


class ConfirmDenied(Exception):
    pass


class Safety:
    def __init__(self, config: Config, store=None):
        self.config = config
        self.store = store
        self.home = Path.home().resolve()
        self._tokens: dict[str, tuple[float, str, dict]] = {}
        self._lock = threading.Lock()

    # ---------------- 路径沙箱 ----------------
    def write_roots(self) -> list[Path]:
        roots = [
            self.home / "Desktop",
            self.home / "Documents",
            self.home / "Downloads",
            self.home / "Pictures",
            self.config.output_dir,
        ]
        for p in self.config.get("paths.extra_dirs") or []:
            try:
                roots.append(Path(p).expanduser().resolve())
            except OSError:
                continue
        return [r for r in roots if r.exists() or r == self.config.output_dir]

    def read_roots(self) -> list[Path]:
        roots = [self.home, self.config.dir]
        for p in self.config.get("paths.extra_dirs") or []:
            try:
                roots.append(Path(p).expanduser().resolve())
            except OSError:
                continue
        return roots

    @staticmethod
    def _inside(child: Path, parent: Path) -> bool:
        try:
            child.relative_to(parent)
            return True
        except ValueError:
            return False

    def resolve(self, raw: str, for_write: bool = False, action: str = "") -> Path:
        """把用户/模型给的路径变成绝对路径，并做沙箱校验。"""
        text = str(raw or "").strip().strip('"')
        if not text:
            raise PermissionError("路径为空")
        p = Path(os.path.expandvars(os.path.expanduser(text)))
        if not p.is_absolute():
            p = (self.config.output_dir if for_write else self.home) / p
        try:
            p = p.resolve()
        except OSError as e:
            raise PermissionError(f"路径无法解析：{e}") from e

        low = str(p).lower()
        if not for_write and any(part in low for part in DENY_READ_PARTS):
            raise PermissionError("该位置包含敏感凭据，Nexus 不会读取。")

        roots = self.write_roots() if for_write else self.read_roots()
        target = p if for_write else p
        if not any(self._inside(target, r) or target == r for r in roots):
            allowed = "、".join(str(r) for r in self.write_roots()[:4])
            if for_write:
                label = "允许删除的位置" if action == "delete" else "允许写入的位置"
            else:
                label = "允许读取的位置"
            raise PermissionError(
                f"路径不在允许范围内：{p}\n{label}：{allowed} 等。可在设置中添加目录。"
            )
        return p

    # ---------------- 确认令牌 ----------------
    def issue_confirm(self, action: str, detail: str, payload: dict | None = None, ttl: int = 60) -> dict:
        token = secrets.token_urlsafe(16)
        with self._lock:
            self._tokens[token] = (time.time() + ttl, action, payload or {})
        self.audit("confirm_request", {"action": action, "detail": detail, "ttl": ttl})
        return {"token": token, "action": action, "detail": detail, "ttl": ttl}

    def consume(self, token: str) -> dict | None:
        with self._lock:
            item = self._tokens.pop(token, None)
        if not item:
            return None
        expire, action, payload = item
        if time.time() > expire:
            return None
        return {"action": action, "payload": payload}

    def purge(self) -> None:
        now = time.time()
        with self._lock:
            for k in [k for k, v in self._tokens.items() if v[0] < now]:
                self._tokens.pop(k, None)

    # ---------------- 审计 ----------------
    def audit(self, action: str, detail=None, ok: bool = True) -> None:
        if self.store:
            try:
                self.store.audit(action, detail, ok)
            except Exception:
                pass

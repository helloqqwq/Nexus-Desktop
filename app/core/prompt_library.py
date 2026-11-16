"""系统提示词库：用户自建的多个 Markdown 提示词文件。"""
from __future__ import annotations

import re
import time
from pathlib import Path

from .config import Config

MAX_BODY = 20000
MAX_NAME = 60
_ID_BAD = re.compile(r"[^\w\-]", re.UNICODE)


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _slug(value: str) -> str:
    slug = _ID_BAD.sub("-", (value or "").strip().lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return (slug or "prompt")[:60]


def _scalar(raw: str) -> str:
    text = raw.strip()
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        text = text[1:-1]
        return text.replace('\\"', '"').replace("\\n", "\n")
    return text


def _parse(text: str) -> tuple[dict, str]:
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?", text, re.S)
    if not match:
        return {}, text
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip().lower()] = _scalar(value)
    return meta, text[match.end():]


def _dump(name: str, enabled: bool, body: str, updated: str) -> str:
    def quote(value: str) -> str:
        text = str(value or "").replace("\\", "\\\\").replace('"', '\\"')
        return '"' + text.replace("\n", "\\n") + '"'

    return (
        "---\n"
        f"name: {quote(name)}\n"
        f"enabled: {'true' if enabled else 'false'}\n"
        f"updated: {quote(updated)}\n"
        "---\n\n"
        + str(body or "").strip()
        + "\n"
    )


class PromptBook:
    """读写 `%APPDATA%\\Nexus\\prompts` 下的 Markdown 系统提示词。"""

    def __init__(self, config: Config):
        self.config = config
        self.dir = Path(config.dir) / "prompts"
        self._migrate_legacy()

    def _migrate_legacy(self) -> None:
        """把旧版单段附加提示词迁移成一个 Markdown 文件，只执行一次。"""
        extra = str(self.config.get("prompt.extra") or "").strip()
        marker = self.dir / ".migrated"
        if not extra or marker.exists():
            return
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            path = self.dir / "custom.md"
            if not path.exists():
                path.write_text(_dump("自定义提示词", True, extra, _now()), encoding="utf-8")
            marker.write_text("1", encoding="utf-8")
            self.config.set("prompt.extra", "")
            self.config.save()
        except OSError:
            pass

    def _read(self, path: Path) -> dict | None:
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            return None
        meta, body = _parse(raw)
        name = " ".join(str(meta.get("name") or path.stem).split())[:MAX_NAME] or path.stem
        return {
            "id": path.stem,
            "name": name,
            "enabled": str(meta.get("enabled", "true")).lower() not in ("false", "0", "no"),
            "body": body.strip()[:MAX_BODY],
            "updated": str(meta.get("updated") or ""),
            "path": str(path),
        }

    def list(self) -> list[dict]:
        if not self.dir.exists():
            return []
        items = []
        for path in self.dir.glob("*.md"):
            item = self._read(path)
            if item:
                items.append(item)
        return sorted(items, key=lambda i: i["name"].lower())

    def get(self, pid: str) -> dict | None:
        for item in self.list():
            if item["id"] == pid:
                return item
        return None

    def save(self, data: dict) -> dict:
        name = " ".join(str(data.get("name") or "").split())[:MAX_NAME]
        body = str(data.get("body") or "").strip()
        if not name:
            return {"ok": False, "error": "提示词名称不能为空"}
        if not body:
            return {"ok": False, "error": "提示词正文不能为空"}
        pid = str(data.get("id") or "").strip() or _slug(name)
        pid = _slug(pid)
        path = self.dir / f"{pid}.md"
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            path.write_text(_dump(name, bool(data.get("enabled", True)), body, _now()),
                            encoding="utf-8")
        except OSError as exc:
            return {"ok": False, "error": f"保存提示词失败：{exc}"}
        item = self.get(pid)
        return {"ok": True, "prompt": item} if item else {"ok": False, "error": "保存后读取失败"}

    def delete(self, pid: str) -> dict:
        item = self.get(pid)
        if not item:
            return {"ok": False, "error": "提示词不存在"}
        try:
            Path(item["path"]).unlink()
        except OSError as exc:
            return {"ok": False, "error": f"删除提示词失败：{exc}"}
        return {"ok": True}

    def set_enabled(self, pid: str, enabled: bool) -> dict:
        item = self.get(pid)
        if not item:
            return {"ok": False, "error": "提示词不存在"}
        data = dict(item)
        data["enabled"] = enabled
        return self.save(data)

    def enabled(self) -> list[dict]:
        return [
            {"id": item["id"], "name": item["name"], "body": self.render(item["body"])}
            for item in self.list() if item["enabled"] and item["body"].strip()
        ]

    def render(self, body: str) -> str:
        profile = self.config.get("ui.profile") or {}
        variables = {
            "date": time.strftime("%Y-%m-%d"),
            "time": time.strftime("%H:%M"),
            "datetime": time.strftime("%Y-%m-%d %H:%M"),
            "user": str(profile.get("name") or "").strip() or "用户",
            "assistant": str(self.config.get("ui.assistant_name") or "Nexus").strip() or "Nexus",
            "model": self.config.active_model() or "deepseek-flash",
            "output_dir": str(self.config.output_dir),
        }
        text = body or ""
        for key, value in variables.items():
            text = text.replace("{{" + key + "}}", str(value))
        return text

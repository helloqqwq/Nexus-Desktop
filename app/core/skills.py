"""技能：本地 SKILL.md / JSON 技能包的读取、保存与提示词注入。"""
from __future__ import annotations

import json
import re
import shutil
import sys
import time
from pathlib import Path

from .config import Config

MAX_BODY = 20000
MAX_NAME = 40
MAX_DESC = 300
_ID_BAD = re.compile(r"[^\w\-]", re.UNICODE)


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _base_dir() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))


def builtin_dir() -> Path:
    return _base_dir() / "app" / "skills"


def _clean(value, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def _slug(value: str, fallback: str = "skill") -> str:
    slug = _ID_BAD.sub("-", (value or "").strip().lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return (slug or fallback)[:60]


def _parse_scalar(raw: str) -> str:
    text = raw.strip()
    if not text:
        return ""
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        text = text[1:-1]
        return text.replace('\\"', '"').replace("\\n", "\n")
    return text


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """解析简单的 YAML frontmatter（只支持 key: value），返回 (meta, body)。"""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?", text, re.S)
    if not match:
        return {}, text
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip().lower()] = _parse_scalar(value)
    return meta, text[match.end():]


def _dump_frontmatter(skill: dict) -> str:
    def quote(value: str) -> str:
        text = str(value or "").replace("\\", "\\\\").replace('"', '\\"')
        return '"' + text.replace("\n", "\\n") + '"'

    lines = [
        "---",
        f"name: {quote(skill.get('name'))}",
        f"description: {quote(skill.get('description'))}",
        f"when_to_use: {quote(skill.get('when_to_use'))}",
        f"version: {int(skill.get('version') or 1)}",
        f"enabled: {'true' if skill.get('enabled', True) else 'false'}",
        "---",
        "",
    ]
    return "\n".join(lines) + str(skill.get("body") or "").strip() + "\n"


def _skill_from_meta(meta: dict, body: str, sid: str, source: str,
                     path: Path | None, fmt: str) -> dict:
    name = _clean(meta.get("name"), MAX_NAME) or sid
    return {
        "id": sid,
        "name": name,
        "description": _clean(meta.get("description"), MAX_DESC),
        "when_to_use": _clean(meta.get("when_to_use") or meta.get("when"), MAX_DESC),
        "body": str(body or "")[:MAX_BODY],
        "enabled": str(meta.get("enabled", "true")).lower() not in ("false", "0", "no"),
        "version": int(meta.get("version") or 1) if str(meta.get("version") or "").isdigit() else 1,
        "source": source,
        "format": fmt,
        "path": str(path or ""),
    }


def _read_skill_file(path: Path, source: str) -> dict | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        sid = _clean(data.get("id") or path.stem, 60) or _slug(path.stem)
        return _skill_from_meta(data, str(data.get("body") or ""), sid, source, path, "json")
    meta, body = _parse_frontmatter(raw)
    sid = _clean(meta.get("id") or path.parent.name, 60) or _slug(path.parent.name)
    if not meta and not body.strip():
        return None
    return _skill_from_meta(meta, body, sid, source, path, "md")


class Skills:
    """同时读取内置与用户技能；同名 id 时用户技能覆盖内置。"""

    def __init__(self, config: Config):
        self.config = config
        self.user_dir = Path(config.dir) / "skills"
        self.builtin = builtin_dir()
        self.state_file = Path(config.dir) / "skills_state.json"

    # ---------- 读取 ----------
    def _state(self) -> dict:
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_state(self, state: dict) -> None:
        try:
            self.state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _disabled_builtin(self) -> set[str]:
        raw = self._state().get("disabled") or []
        return {str(item) for item in raw} if isinstance(raw, list) else set()

    def _load_dir(self, root: Path, source: str) -> dict[str, dict]:
        out: dict[str, dict] = {}
        if not root.exists():
            return out
        try:
            entries = list(root.iterdir())
        except OSError:
            return out
        for entry in entries:
            path = None
            if entry.is_dir():
                for name in ("SKILL.md", "skill.md", "SKILL.MD"):
                    candidate = entry / name
                    if candidate.is_file():
                        path = candidate
                        break
            elif entry.is_file() and entry.suffix.lower() == ".json":
                path = entry
            elif entry.is_file() and entry.suffix.lower() == ".md":
                path = entry
            if not path:
                continue
            skill = _read_skill_file(path, source)
            if not skill:
                continue
            out[skill["id"]] = skill
        return out

    def list(self) -> list[dict]:
        builtin = self._load_dir(self.builtin, "builtin")
        user = self._load_dir(self.user_dir, "user")
        disabled = self._disabled_builtin()
        merged: dict[str, dict] = {}
        for sid, skill in builtin.items():
            skill = dict(skill)
            skill["enabled"] = skill["enabled"] and sid not in disabled
            merged[sid] = skill
        for sid, skill in user.items():
            merged[sid] = skill
        items = list(merged.values())

        def order(item: dict) -> tuple:
            return (0 if item["source"] == "user" else 1, item["name"].lower())

        return sorted(items, key=order)

    def get(self, sid: str) -> dict | None:
        for item in self.list():
            if item["id"] == sid:
                return item
        return None

    def catalog(self) -> list[dict]:
        return [
            {
                "id": item["id"],
                "name": item["name"],
                "description": item["description"],
                "when_to_use": item["when_to_use"],
            }
            for item in self.list() if item["enabled"]
        ]

    # ---------- 写入 ----------
    def save(self, data: dict) -> dict:
        sid = _clean(data.get("id"), 60) or _slug(data.get("name") or data.get("id"))
        existing = self.get(sid)
        if existing and existing["source"] == "builtin":
            existing = None  # 覆盖内置：在用户目录创建同名副本
        name = _clean(data.get("name"), MAX_NAME)
        if not name:
            return {"ok": False, "error": "技能名称不能为空"}
        body = str(data.get("body") or "").strip()
        if not body:
            return {"ok": False, "error": "技能正文不能为空"}
        skill = {
            "id": sid,
            "name": name,
            "description": _clean(data.get("description"), MAX_DESC),
            "when_to_use": _clean(data.get("when_to_use"), MAX_DESC),
            "body": body[:MAX_BODY],
            "enabled": bool(data.get("enabled", True)),
            "version": int(existing.get("version") or 1) if existing else 1,
            "source": "user",
            "format": (existing or {}).get("format") or "md",
        }
        try:
            self.user_dir.mkdir(parents=True, exist_ok=True)
            if skill["format"] == "json":
                old_path = Path((existing or {}).get("path") or "")
                path = old_path if old_path.suffix.lower() == ".json" and old_path.parent == self.user_dir \
                    else self.user_dir / f"{sid}.json"
                payload = {k: skill[k] for k in
                           ("id", "name", "description", "when_to_use", "body", "enabled", "version")}
                path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            else:
                path = self.user_dir / sid / "SKILL.md"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(_dump_frontmatter(skill), encoding="utf-8")
        except OSError as exc:
            return {"ok": False, "error": f"保存技能失败：{exc}"}
        item = self.get(sid)
        return {"ok": True, "skill": item} if item else {"ok": False, "error": "保存后读取失败"}

    def delete(self, sid: str) -> dict:
        skill = self.get(sid)
        if not skill:
            return {"ok": False, "error": "技能不存在"}
        if skill["source"] != "user":
            return {"ok": False, "error": "内置技能不能删除，可以停用"}
        path = Path(skill.get("path") or "")
        try:
            if path.is_file() and path.parent == self.user_dir:
                path.unlink()
            elif path.is_file():
                shutil.rmtree(path.parent, ignore_errors=True)
            else:
                shutil.rmtree(self.user_dir / sid, ignore_errors=True)
        except OSError as exc:
            return {"ok": False, "error": f"删除技能失败：{exc}"}
        return {"ok": True}

    def set_enabled(self, sid: str, enabled: bool) -> dict:
        skill = self.get(sid)
        if not skill:
            return {"ok": False, "error": "技能不存在"}
        if skill["source"] == "builtin":
            state = self._state()
            disabled = {str(item) for item in (state.get("disabled") or [])}
            if enabled:
                disabled.discard(sid)
            else:
                disabled.add(sid)
            state["disabled"] = sorted(disabled)
            self._save_state(state)
            return {"ok": True, "enabled": enabled}
        data = dict(skill)
        data["enabled"] = enabled
        return self.save(data)

    # ---------- 注入 ----------
    def variables(self) -> dict:
        now = time.localtime()
        profile = self.config.get("ui.profile") or {}
        return {
            "date": time.strftime("%Y-%m-%d", now),
            "time": time.strftime("%H:%M", now),
            "datetime": time.strftime("%Y-%m-%d %H:%M", now),
            "user": str(profile.get("name") or "").strip() or "用户",
            "assistant": str(self.config.get("ui.assistant_name") or "Nexus").strip() or "Nexus",
            "model": self.config.active_model() or "deepseek-flash",
            "output_dir": str(self.config.output_dir),
        }

    def render(self, body: str) -> str:
        text = body or ""
        for key, value in self.variables().items():
            text = text.replace("{{" + key + "}}", str(value))
        return text

    def body_for(self, sid: str) -> str:
        skill = self.get(sid)
        if not skill:
            return ""
        return self.render(skill["body"])

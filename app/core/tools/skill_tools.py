"""技能与长期记忆工具。"""
from __future__ import annotations

from ..config import Config
from ..safety import Safety
from ..skills import Skills
from ..store import Store
from .registry import Registry, Tool


def register(reg: Registry, config: Config, safety: Safety, store: Store | None = None) -> None:
    def skill_use(args: dict) -> dict:
        key = str(args.get("id") or args.get("name") or "").strip()
        if not key:
            return {"ok": False, "error": "缺少技能 id 或名称"}
        skills = Skills(config)
        skill = skills.get(key)
        if not skill:
            skill = next((item for item in skills.list() if item["name"] == key), None)
        if not skill:
            available = "、".join(item["id"] for item in skills.catalog()[:12])
            return {"ok": False, "error": f"没有这个技能：{key}",
                    "hint": f"可用技能：{available}" if available else "当前没有启用的技能"}
        if not skill["enabled"]:
            return {"ok": False, "error": f"技能已停用：{skill['name']}"}
        safety.audit("skill_use", {"id": skill["id"]})
        return {
            "ok": True,
            "id": skill["id"],
            "name": skill["name"],
            "content": skills.render(skill["body"]),
        }

    def memory_save(args: dict) -> dict:
        if not config.get("memory.enabled", True):
            return {"ok": False, "error": "长期记忆已在设置中关闭"}
        if store is None:
            return {"ok": False, "error": "记忆存储不可用"}
        text = str(args.get("text") or "").strip()
        if not text:
            return {"ok": False, "error": "缺少要记住的内容"}
        category = str(args.get("category") or "preference").strip().lower()
        if category not in ("preference", "habit", "fact"):
            category = "preference"
        memory_id = store.add_memory(text, category)
        safety.audit("memory_save", {"id": memory_id, "chars": len(text)})
        return {"ok": True, "id": memory_id, "output": "已记住"}

    def memory_forget(args: dict) -> dict:
        if store is None:
            return {"ok": False, "error": "记忆存储不可用"}
        raw = args.get("id")
        if raw not in (None, ""):
            try:
                deleted = store.delete_memory(int(raw))
            except (TypeError, ValueError):
                return {"ok": False, "error": "记忆 id 无效"}
            return {"ok": True, "deleted": deleted}
        text = " ".join(str(args.get("text") or "").split())
        if not text:
            return {"ok": False, "error": "请提供记忆 id 或内容"}
        for item in store.memories(limit=200):
            if item["text"] == text:
                return {"ok": True, "deleted": store.delete_memory(int(item["id"]))}
        return {"ok": False, "error": "没有找到匹配的记忆"}

    reg.add(Tool(
        name="skill_use",
        description=(
            "读取一个技能的完整步骤并按其执行。当用户请求与可用技能匹配、或用户点名某个技能时调用。"
            "参数用技能 id 或名称。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "技能 id（优先）"},
                "name": {"type": "string", "description": "技能名称或 id"},
            },
        },
        handler=skill_use,
        tag="skill",
    ))
    reg.add(Tool(
        name="memory_save",
        description=(
            "把用户稳定的偏好、习惯或长期有效的事实写入长期记忆。"
            "不要保存密码、密钥、验证码或一次性信息；同一内容会自动去重。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "要记住的一句话，尽量具体"},
                "category": {
                    "type": "string",
                    "enum": ["preference", "habit", "fact"],
                    "description": "偏好 / 习惯 / 事实，默认 preference",
                },
            },
            "required": ["text"],
        },
        handler=memory_save,
        tag="memory",
    ))
    reg.add(Tool(
        name="memory_forget",
        description="删除一条长期记忆。用户要求忘记某事时使用。",
        parameters={
            "type": "object",
            "properties": {
                "id": {"type": "integer", "description": "记忆 id"},
                "text": {"type": "string", "description": "记忆内容（按原文精确匹配）"},
            },
        },
        handler=memory_forget,
        tag="memory",
    ))

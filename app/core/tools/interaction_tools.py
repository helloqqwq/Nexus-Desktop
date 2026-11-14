"""交互工具：向用户提问、发送通知。"""
from __future__ import annotations

from ..config import Config
from ..safety import Safety
from .registry import Registry, Tool


def register(reg: Registry, config: Config, safety: Safety) -> None:
    def ask_user(args: dict) -> dict:
        # 真正的提问由 Agent 层拦截并等待前端/终端回答
        return {"ok": False, "error": "ask_user 需要由对话层处理"}

    def notify_user(args: dict) -> dict:
        title = str(args.get("title") or "Nexus").strip()[:60]
        message = str(args.get("message") or "").strip()[:500]
        if not message:
            return {"ok": False, "error": "缺少 message"}
        safety.audit("notify_user", {"title": title, "chars": len(message)})
        return {"ok": True, "title": title, "message": message,
                "output": f"已通知：{title}"}

    reg.add(Tool(
        name="ask_user",
        description=(
            "向用户提问并等待回答。信息不足或需要用户做选择时使用。"
            "options 给 2-4 个选项；allow_text=true 时用户也可以自己输入。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "要问用户的问题"},
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "可选项，最多 4 个",
                },
                "allow_text": {"type": "boolean", "description": "是否允许自由输入，默认是"},
            },
            "required": ["question"],
        },
        handler=ask_user,
        tag="interaction",
    ))
    reg.add(Tool(
        name="notify_user",
        description="给用户发一条桌面通知，适合长任务完成或需要用户回来查看时使用。",
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "通知标题"},
                "message": {"type": "string", "description": "通知正文"},
            },
            "required": ["message"],
        },
        handler=notify_user,
        tag="interaction",
    ))

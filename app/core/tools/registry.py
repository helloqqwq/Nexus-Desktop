"""工具注册表。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    handler: Callable[[dict], dict]
    needs_confirm: bool = False
    tag: str = "general"

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters or {"type": "object", "properties": {}},
            },
        }


class Registry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}
        self.cancel_event = None

    def add(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def schemas(self, exclude: set[str] | None = None) -> list[dict]:
        exclude = exclude or set()
        return [t.schema() for n, t in self._tools.items() if n not in exclude]

    def dispatch(self, name: str, args: dict | None) -> dict:
        tool = self._tools.get(name)
        if not tool:
            return {"ok": False, "error": f"未知工具：{name}"}
        try:
            result = tool.handler(args or {})
            if not isinstance(result, dict):
                return {"ok": False, "error": "工具返回格式异常"}
            return result
        except PermissionError as e:
            return {"ok": False, "error": str(e), "denied": True}
        except TimeoutError as e:
            return {"ok": False, "error": f"执行超时：{e}"}
        except Exception as e:  # 工具层兜底，避免整轮对话中断
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

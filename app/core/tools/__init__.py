"""工具装配：一次性注册全部工具。"""
from __future__ import annotations

from ..config import Config
from ..safety import Safety
from ..store import Store
from . import (app_tools, desktop_tools, diag_tools, fs_tools,
               interaction_tools, office_tools, shell_tool, skill_tools, web_tools)
from .registry import Registry, Tool

# 安全模式只保留读取类工具，任何会改动系统或文件的工具都不可见。
SAFE_EXCLUDE = {
    "fs_write", "fs_edit", "fs_delete",
    "shell_run", "shell_exec",
    "app_open", "app_launch",
    "ui_act",
    "schedule_task", "cancel_schedule",
    "docx_write", "xlsx_write", "pptx_write", "html_to_pptx", "office_edit",
}


def exclude_for(mode: str) -> set[str]:
    mode = (mode or "supervised").lower()
    if mode == "safe":
        return set(SAFE_EXCLUDE)
    return set()


def build(config: Config, safety: Safety, store: Store | None = None) -> Registry:
    reg = Registry()
    fs_tools.register(reg, config, safety)
    shell_tool.register(reg, config, safety)
    diag_tools.register(reg, config, safety)
    app_tools.register(reg, config, safety)
    desktop_tools.register(reg, config, safety)
    web_tools.register(reg, config, safety)
    interaction_tools.register(reg, config, safety)
    office_tools.register(reg, config, safety)
    skill_tools.register(reg, config, safety, store)
    return reg


__all__ = ["build", "Registry", "Tool", "SAFE_EXCLUDE", "exclude_for"]

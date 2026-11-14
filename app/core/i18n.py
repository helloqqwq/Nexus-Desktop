"""后端文案语言开关。

前端有独立的 i18n 字典；这里只负责后端生成的提示、错误和通知。
语言来源为 ``ui.language``，支持 zh / en / system。
"""
from __future__ import annotations

import locale
import os

_LANG = "zh"


def resolve_language(value: str | None) -> str:
    value = str(value or "").strip().lower()
    if value in ("zh", "en"):
        return value
    # system：按 Windows / 系统区域判断，中文环境用中文，其余用英文
    try:
        code = locale.getdefaultlocale()[0] or ""
    except Exception:
        code = ""
    if not code and os.name == "nt":
        try:
            import ctypes

            lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            code = "zh" if lang_id in (0x0804, 0x0404, 0x0C04, 0x1004) else "en"
        except Exception:
            code = ""
    return "zh" if str(code).lower().startswith("zh") else "en"


def set_language(value: str | None) -> str:
    global _LANG
    _LANG = resolve_language(value)
    return _LANG


def get_language() -> str:
    return _LANG


def t(zh: str, en: str) -> str:
    return en if _LANG == "en" else zh

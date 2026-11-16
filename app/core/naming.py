"""按内容生成名称：优先让模型取名，未配置 Key 或失败时退回本地规则。"""
from __future__ import annotations

import re

from .config import Config
from .i18n import get_language, t

MAX_BODY = 8000
_CLEAN_CHARS = " \t\r\n\"'“”‘’`#*·:：。.,，、-—"


def _clean(text: str, limit: int) -> str:
    value = " ".join(str(text or "").split()).strip(_CLEAN_CHARS)
    return value[:limit]


def _local_name(body: str, kind: str) -> str:
    """本地兜底：优先用一级标题，其次用第一句有效文本。"""
    for line in str(body or "").splitlines():
        text = line.strip()
        if not text:
            continue
        heading = re.match(r"^#{1,6}\s*(.+)$", text)
        if heading:
            return _clean(heading.group(1), 30)
        if text.startswith(("-", "*", "+", "|", ">", "```")):
            continue
        return _clean(text, 30)
    return t("未命名提示词", "Untitled prompt") if kind == "prompt" else t("未命名技能", "Untitled skill")


def _model_name(config: Config, body: str, kind: str, limit: int) -> str:
    from .llm import LLMClient

    label = "系统提示词" if kind == "prompt" else "技能"
    if get_language() == "en":
        instruction = (
            f"The user wrote the {label} below but did not give it a name. "
            "Reply with a short title (2-6 words) only. No quotes, no explanation.\n\n"
        )
    else:
        instruction = (
            f"下面是用户写的{label}正文，但他没有命名。请根据正文内容取一个简洁的名称"
            "（2-10 个字），只输出名称本身，不要引号，不要解释。\n\n"
        )
    text = LLMClient(config).complete(
        [{"role": "user", "content": instruction + str(body)[:MAX_BODY]}],
        max_tokens=32,
        temperature=0.2,
    )
    first = str(text or "").splitlines()[0] if str(text or "").strip() else ""
    return _clean(first, limit)


def suggest_name(config: Config, body: str, kind: str = "prompt", limit: int = 40) -> str:
    """给没有名称的提示词/技能生成名称；返回空字符串表示正文也为空。"""
    text = str(body or "").strip()
    if not text:
        return ""
    if config.api_key:
        try:
            name = _model_name(config, text, kind, limit)
            if name:
                return name
        except Exception:
            pass
    return _clean(_local_name(text, kind), limit)

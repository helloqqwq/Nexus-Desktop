"""上下文压缩：提示词、token 估算与摘要合并。

压缩不是在本地做关键词抽取，而是把较早的完整对话交给模型总结。
历史很长时按字符预算分块送模，逐块合并，避免一次请求超过模型上下文。
"""
from __future__ import annotations

import json

from .i18n import get_language

# 单次摘要请求的输入预算（字符）。中文约 1 字 ≈ 0.6 token，这里留足余量。
CHUNK_CHARS = 22000
SUMMARY_MAX_TOKENS = 1400
# 达到上下文档位的 50% 时自动触发全量摘要压缩。
COMPRESS_RATIO = 0.5

# 结构开销：与 deepseek-harness 的 token-meter 保持一致。
BLOCK_OVERHEAD = 4   # 每个内容块的结构与类型标签
ROLE_OVERHEAD = 4    # 每条消息的角色与信封开销
# 图片按固定值估算；base64 长度没有参考价值，精确价格由厂商决定。
IMAGE_TOKENS = 1200

PROMPT_ZH = """你是 Nexus 的上下文压缩器，不负责回答用户。
输入包含两部分：【已有摘要】和【新增对话】。请把它们合并成一份新的摘要，供后续对话直接使用。

必须保留：
1. 用户明确的目标、偏好、禁止事项、已经确认的决定；
2. 文件路径、命令、报错信息、关键数据、接口名、字段名、函数名；
3. 已完成事项、未完成事项、下一步计划；
4. 重要信息之间的因果关系，以及用户纠正过的错误理解。

可以删除：寒暄、重复内容、已经失效的中间尝试、冗长的解释。
要求：
- 用条目式输出，不超过 1200 字；
- 不要编造输入中不存在的信息；
- 不要输出“以下是摘要”之类的前缀；
- 信息冲突时，以较新的对话为准；
- 保留用户的原话关键词，尤其是路径、命令和错误码。
"""

PROMPT_EN = """You compress context for Nexus. Do not answer the user.
The input contains [Previous summary] and [New conversation]. Merge them into one new summary that can be used directly in later turns.

Preserve:
1. The user's goals, preferences, prohibitions, and confirmed decisions;
2. File paths, commands, error messages, key data, API names, field names, and function names;
3. Completed work, unfinished work, and next steps;
4. Important cause-and-effect relationships and corrections the user made.

You may remove: greetings, repetition, failed intermediate attempts, and long explanations.
Requirements:
- Use bullet points, no more than 900 words;
- Do not invent information;
- Do not add a prefix such as "Here is the summary";
- When information conflicts, prefer the newer conversation;
- Keep the user's exact keywords, especially paths, commands, and error codes.
"""


def estimate_tokens(text: str) -> int:
    """与前端一致的粗略 token 估算：ASCII 4 字符 1 token，其余 1.6 字符 1 token。"""
    s = str(text or "")
    ascii_count = sum(1 for ch in s if ord(ch) < 128)
    other = len(s) - ascii_count
    return max(1, int(round(ascii_count / 4 + other / 1.6)))


def estimate_rows(rows: list[dict]) -> int:
    return sum(estimate_tokens(row.get("content") or "") + 6 for row in rows)


def estimate_block(block) -> int:
    """给一个内容块定价：文本按密度，图片按固定值，其余按 JSON 结构。"""
    if not isinstance(block, dict):
        return BLOCK_OVERHEAD + estimate_tokens(str(block))
    kind = str(block.get("type") or "")
    if kind == "image_url":
        return IMAGE_TOKENS
    if kind == "text":
        return BLOCK_OVERHEAD + estimate_tokens(block.get("text") or "")
    return BLOCK_OVERHEAD + estimate_tokens(json.dumps(block, ensure_ascii=False))


def estimate_system(text: str) -> int:
    """系统提示词按纯文本计价，不加内容块开销。"""
    s = str(text or "")
    if not s.strip():
        return 0
    return estimate_tokens(s) + ROLE_OVERHEAD


def estimate_message(message: dict) -> int:
    """按真正发送出去的消息计价，包含角色与内容块的结构开销。"""
    role = str(message.get("role") or "")
    content = message.get("content")
    if role == "system":
        if isinstance(content, list):
            return sum(estimate_block(b) for b in content) + ROLE_OVERHEAD
        return estimate_system(content)
    tokens = ROLE_OVERHEAD
    if isinstance(content, str):
        if content:
            tokens += BLOCK_OVERHEAD + estimate_tokens(content)
    elif isinstance(content, list):
        for block in content:
            tokens += estimate_block(block)
    calls = message.get("tool_calls")
    if calls:
        tokens += BLOCK_OVERHEAD + estimate_tokens(json.dumps(calls, ensure_ascii=False))
    return tokens


def estimate_messages(messages: list[dict]) -> int:
    return sum(estimate_message(msg) for msg in messages)


def estimate_tools(tools: list[dict] | None) -> int:
    """工具 schema 本身也占上下文，按 JSON 长度计价。"""
    if not tools:
        return 0
    return BLOCK_OVERHEAD + estimate_tokens(json.dumps(tools, ensure_ascii=False))


def format_rows(rows: list[dict]) -> str:
    lines = []
    for row in rows:
        role = "用户" if row.get("role") == "user" else "助手"
        if get_language() == "en":
            role = "User" if row.get("role") == "user" else "Assistant"
        content = str(row.get("content") or "").strip()
        if not content:
            continue
        lines.append(f"[{role}]\n{content}")
    return "\n\n".join(lines)


def chunks(rows: list[dict], budget: int = CHUNK_CHARS) -> list[list[dict]]:
    """按字符预算分组，尽量不切断单条消息。"""
    groups: list[list[dict]] = []
    current: list[dict] = []
    size = 0
    for row in rows:
        length = len(str(row.get("content") or "")) + 16
        if current and size + length > budget:
            groups.append(current)
            current, size = [], 0
        current.append(row)
        size += length
    if current:
        groups.append(current)
    return groups


def summary_prompt(previous: str, rows: list[dict]) -> list[dict]:
    system = PROMPT_EN if get_language() == "en" else PROMPT_ZH
    conversation = format_rows(rows)
    if get_language() == "en":
        user = (
            "[Previous summary]\n" + (previous.strip() or "(none)") +
            "\n\n[New conversation]\n" + conversation
        )
    else:
        user = (
            "【已有摘要】\n" + (previous.strip() or "（无）") +
            "\n\n【新增对话】\n" + conversation
        )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def split_for_summary(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """返回（全部需要总结的历史，保留在上下文里的消息）。

    压缩策略是“全量摘要”：除当前正在等待回答的最后一条用户消息外，
    其余历史全部进入摘要，不再保留最近若干条原文。
    """
    if rows and rows[-1].get("role") == "user":
        return rows[:-1], rows[-1:]
    return list(rows), []

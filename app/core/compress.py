"""上下文压缩：提示词、token 估算与摘要合并。

压缩不是在本地做关键词抽取，而是把较早的完整对话交给模型总结。
历史很长时按字符预算分块送模，逐块合并，避免一次请求超过模型上下文。
"""
from __future__ import annotations

from .i18n import get_language

# 单次摘要请求的输入预算（字符）。中文约 1 字 ≈ 0.6 token，这里留足余量。
CHUNK_CHARS = 22000
SUMMARY_MAX_TOKENS = 1400
# 达到上下文档位的 50% 时自动触发全量摘要压缩。
COMPRESS_RATIO = 0.5

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

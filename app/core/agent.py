"""对话编排：系统提示、工具循环、事件推送、离线诊断。"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from pathlib import Path

from . import diag
from .compress import (
    COMPRESS_RATIO,
    SUMMARY_MAX_TOKENS,
    chunks,
    estimate_message,
    estimate_messages,
    estimate_rows,
    estimate_system,
    estimate_tokens,
    estimate_tools,
    split_for_summary,
    summary_prompt,
)
from .config import Config
from .i18n import t
from .llm import Cancelled, LLMClient, LLMError
from .prompts import build_system_prompt
from .prompt_library import PromptBook
from .skills import Skills
from .safety import Safety
from .store import Store
from .tools import Registry, exclude_for

TOOL_TRIM_CHARS = 800    # 轮内上下文吃紧时，旧工具输出截断到该长度
TOOL_MIN_CHARS = 120     # 二次压缩时保留的最小工具输出
TOOL_RESULT_CHARS = 6000 # 单次工具结果回传给模型的上限
NET_KEYS = ("网", "wifi", "wlan", "dns", "ping", "路由器", "代理", "连不上",
            "打不开", "掉线", "延迟", "丢包", "宽带", "光猫")
log = logging.getLogger("nexus.agent")


def _short(value, limit: int = 400) -> str:
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    text = str(value or "").replace("\n", " ")
    return text[:limit]


def _tool_content(result: dict, limit: int = TOOL_RESULT_CHARS) -> str:
    """把工具结果转成模型可读的 JSON；超长时压缩字段而不是截断 JSON 本身。"""
    payload = json.dumps(result, ensure_ascii=False)
    if len(payload) <= limit:
        return payload
    slim = dict(result)
    slim["truncated"] = True
    # 结构化列表已经能表达内容时，先丢掉重复的纯文本 output，避免被二次压缩
    if any(isinstance(v, list) and len(v) > 20 for v in slim.values()):
        slim.pop("output", None)
        slim.pop("output_text", None)
    for key, value in list(slim.items()):
        if isinstance(value, str) and len(value) > 1200:
            slim[key] = value[:1200] + "…"
        elif isinstance(value, list) and len(value) > 60:
            slim[key] = value[:60]
    payload = json.dumps(slim, ensure_ascii=False)
    if len(payload) <= limit:
        return payload
    return json.dumps({
        "ok": bool(result.get("ok")),
        "error": result.get("error") or "",
        "hint": result.get("hint") or "",
        "truncated": True,
        "note": "工具返回内容过大，已省略明细；请缩小查询范围或调小 limit 后重试。",
    }, ensure_ascii=False)


class _Emitter:
    def __init__(self, on_event):
        self.on_event = on_event

    def __call__(self, payload: dict) -> None:
        if not self.on_event:
            return
        try:
            self.on_event(payload)
        except Exception:
            pass


class Agent:
    def __init__(self, config: Config, store: Store, safety: Safety, registry: Registry):
        self.config = config
        self.store = store
        self.safety = safety
        self.registry = registry
        self._changes: dict[str, dict] = {}

    # ---------------- 对外入口 ----------------
    def run(self, session_id: int, text: str, on_event=None, confirm=None,
            cancel=None, attachments: list | None = None,
            ask=None, notify=None, on_control=None, skill_id: str | None = None) -> None:
        self.registry.cancel_event = cancel
        self._changes = {}
        try:
            return self._run_impl(session_id, text, on_event, confirm, cancel,
                                  attachments, ask, notify, on_control, skill_id)
        finally:
            self._flush_changes(_Emitter(on_event))
            if on_control:
                try:
                    on_control(False)
                except Exception:
                    pass
            self.registry.cancel_event = None

    def _record_change(self, result: dict) -> None:
        """按文件累计本轮改动的行数，供前端展示改动最大的几个文件。"""
        path = str(result.get("path") or "")
        added = int(result.get("lines_added") or 0)
        removed = int(result.get("lines_removed") or 0)
        if not path or (added == 0 and removed == 0):
            return
        entry = self._changes.get(path)
        if entry:
            entry["added"] += added
            entry["removed"] += removed
            return
        self._changes[path] = {
            "path": path,
            "name": str(result.get("name") or Path(path).name),
            "added": added,
            "removed": removed,
        }

    def _flush_changes(self, emit) -> None:
        """一轮结束后只推送改动最大的 3 个文件，而不是把所有碰过的文件都列出来。"""
        changes = getattr(self, "_changes", None) or {}
        if not changes:
            return
        items = sorted(changes.values(), key=lambda it: it["added"] + it["removed"],
                       reverse=True)
        emit({
            "type": "changes",
            "items": items[:3],
            "total": len(items),
            "more": max(0, len(items) - 3),
            "added": sum(it["added"] for it in items),
            "removed": sum(it["removed"] for it in items),
        })
        self._changes = {}

    def _run_impl(self, session_id: int, text: str, on_event=None, confirm=None,
                  cancel=None, attachments: list | None = None,
                  ask=None, notify=None, on_control=None,
                  skill_id: str | None = None) -> None:
        emit = _Emitter(on_event)
        mode = str(self.config.get("mode") or "supervised").lower()
        text = (text or "").strip()
        attachments = attachments or []
        skills = Skills(self.config)
        catalog = skills.catalog()
        active = skills.get(skill_id) if skill_id else None
        active_skill = None
        if active and active.get("enabled"):
            active_skill = {
                "id": active["id"],
                "name": active["name"],
                "body": skills.render(active["body"]),
            }
        meta: dict = {"attachments": len(attachments)}
        if active_skill:
            meta["skill"] = active_skill["id"]
            meta["skill_name"] = active_skill["name"]
        self.store.add_message(session_id, "user", text, meta)
        session = self.store.get_session(session_id)
        if session and session.get("title") == "新对话" and text:
            self.store.touch_session(session_id, title=text[:18])

        emit({"type": "state", "status": "thinking"})
        if not self.config.api_key:
            self._offline(session_id, text, emit, cancel)
            return

        memories = self.store.memories(limit=40) if self.config.get("memory.enabled", True) else []
        custom_prompts = PromptBook(self.config).enabled()
        system_prompt = build_system_prompt(
            self.config, catalog, memories, active_skill, custom_prompts)
        messages = [{"role": "system", "content": system_prompt}]
        tools = self.registry.schemas(exclude=exclude_for(mode))
        llm = LLMClient(self.config)
        system_tokens = estimate_system(system_prompt)
        tools_tokens = estimate_tools(tools)
        envelope = llm.envelope(tools)
        messages.extend(self._history(session_id, emit, system_tokens + tools_tokens))
        if attachments:
            messages[-1] = {"role": "user", "content": self._user_content(text, attachments)}

        vision_stripped = not attachments

        # 不设固定轮次上限，也不做重复调用拦截：由模型自己决定何时结束。
        # 唯一的中断来源是用户取消。
        round_idx = 0
        while True:
            if cancel is not None and cancel.is_set():
                emit({"type": "state", "status": "idle"})
                return
            round_idx += 1
            self._fit_messages(messages, tools_tokens)
            surface_tokens = estimate_messages(messages)
            self._emit_usage(emit, session_id, surface_tokens, system_tokens, tools_tokens, envelope)
            msg_id = "m" + uuid.uuid4().hex[:10]
            emit({"type": "state", "status": "thinking"})
            try:
                result = llm.chat(
                    messages, tools=tools, cancel=cancel,
                    on_delta=lambda d, mid=msg_id: emit({"type": "assistant_delta", "id": mid, "text": d}),
                    on_reasoning=lambda d, mid=msg_id: emit({"type": "reasoning_delta", "id": mid, "text": d}),
                    on_retry=lambda attempt, total, delay, reason: emit({
                        "type": "notify",
                        "title": t("网络重试", "Network retry"),
                        "message": t(
                            f"连接不稳定，第 {attempt}/{total} 次重试（{delay}s）…",
                            f"Unstable connection, retry {attempt}/{total} in {delay}s…",
                        ),
                    }),
                )
            except Cancelled as e:
                if e.partial:
                    emit({"type": "assistant_done", "id": msg_id, "text": e.partial, "stopped": True})
                    self.store.add_message(session_id, "assistant", e.partial, {"stopped": True})
                emit({"type": "state", "status": "idle"})
                return
            except LLMError as e:
                partial = (getattr(e, "partial", "") or "").strip()
                if partial:
                    # 流式回答中途断网：保留已生成内容，避免用户白等一场。
                    emit({"type": "assistant_done", "id": msg_id, "text": partial,
                          "stopped": True, "network_error": True})
                    self.store.add_message(session_id, "assistant", partial,
                                           {"stopped": True, "network_error": True})
                    emit({"type": "error", "message": e.message,
                          "hint": e.hint or t("网络中断，已保留部分回答",
                                              "The connection dropped; partial answer kept"),
                          "detail": e.detail, "status": e.status})
                    emit({"type": "state", "status": "error"})
                    return
                if not vision_stripped:
                    vision_stripped = True
                    messages[-1] = {
                        "role": "user",
                        "content": (text or t("请看截图", "Please look at the screenshot")) +
                        t("\n（当前模型不支持图片，截图已忽略）",
                          "\n(The current model does not support images; the screenshot was ignored.)"),
                    }
                    emit({"type": "error",
                          "message": t("当前模型不支持图片，已改为文字对话",
                                       "The current model does not support images; switched to text."),
                          "hint": t("可在设置中换用支持图片的模型",
                                    "Choose an image-capable model in Settings")})
                    continue
                if round_idx == 0:
                    answer = offline_answer(text, self.registry, emit, cancel)
                    answer = (t("（模型连接失败，已切换为离线诊断）",
                                "(Model connection failed; switched to offline diagnostics)") +
                              "\n\n" + answer)
                    self._stream_answer(session_id, answer, emit)
                    emit({"type": "error", "message": e.message,
                          "hint": e.hint or t("检查设置中的接口地址与密钥",
                                              "Check the API URL and key in Settings"),
                          "detail": e.detail, "status": e.status})
                else:
                    emit({"type": "error", "message": e.message, "hint": e.hint,
                          "detail": e.detail, "status": e.status})
                    emit({"type": "state", "status": "error"})
                return

            text_out = result.get("text") or ""
            calls = result.get("tool_calls") or []
            if text_out:
                emit({"type": "assistant_done", "id": msg_id, "text": text_out})

            usage = result.get("usage")
            usage_meta = self._usage_meta(usage, envelope, surface_tokens, tools_tokens)

            if not calls:
                if text_out:
                    self.store.add_message(session_id, "assistant", text_out, usage_meta)
                elif usage_meta:
                    # 没有文字但有用量时也要落库，否则锚点会丢。
                    self.store.add_message(session_id, "assistant", "", usage_meta)
                emit({"type": "state", "status": "idle"})
                return

            message_meta = dict(usage_meta or {})
            message_meta["tool_calls"] = [c["function"]["name"] for c in calls]
            self.store.add_message(session_id, "assistant", text_out, message_meta)
            assistant_msg = {"role": "assistant", "content": text_out, "tool_calls": calls}
            if result.get("reasoning"):
                # 思考模式下发生工具调用时，reasoning_content 必须原样回传
                assistant_msg["reasoning_content"] = result["reasoning"]
            messages.append(assistant_msg)
            for tc in calls:
                emit({"type": "state", "status": "working"})
                tool_msg = self._exec_tool(session_id, tc, emit, confirm, cancel, ask, notify,
                                           on_control)
                messages.append(tool_msg)

    def _fit_messages(self, messages: list[dict], base_tokens: int = 0) -> None:
        """轮内上下文兜底：超预算时逐步压缩较早的工具输出，让长任务能继续跑。"""
        budget = int(self._context_limit() * 0.85)
        total = estimate_messages(messages) + base_tokens
        if total <= budget:
            return
        for limit_chars in (TOOL_TRIM_CHARS, TOOL_MIN_CHARS):
            for msg in messages[1:]:
                if total <= budget:
                    return
                if msg.get("role") != "tool":
                    continue
                content = str(msg.get("content") or "")
                if len(content) <= limit_chars:
                    continue
                trimmed = (content[:limit_chars] +
                           "\n（较早的工具输出已截断，以控制上下文长度）")
                msg["content"] = trimmed
                total += estimate_tokens(trimmed) - estimate_tokens(content)

    @staticmethod
    def _usage_meta(usage, envelope: str, surface: int, tools_tokens: int) -> dict | None:
        """把真实用量与当次请求信封一起记录，供下次计量复用。"""
        if not isinstance(usage, dict):
            return None
        return {
            "usage": usage,
            "envelope": envelope,
            "surface": int(surface),
            "estimate": int(tools_tokens) + int(surface),
        }

    def _pressure(self, session_id: int, surface: int, system_tokens: int,
                  tools_tokens: int, envelope: str) -> tuple[int, str]:
        """上下文压力：优先复用同一信封下的真实 prompt 用量，否则用本地估算。"""
        used = tools_tokens + surface
        source = "estimate"
        anchor = self.store.last_usage(session_id)
        if anchor and anchor.get("envelope") == envelope and isinstance(anchor.get("usage"), dict):
            u = anchor["usage"]
            prompt = (int(u.get("input") or 0) + int(u.get("cache_read") or 0)
                      + int(u.get("cache_write") or 0))
            if prompt > 0:
                anchor_surface = int(anchor.get("surface") or 0)
                anchor_estimate = tools_tokens + anchor_surface
                # 和参考实现一致：供应商少报时退回估算，避免环图偏低。
                used = max(prompt, anchor_estimate) + (surface - anchor_surface)
                if prompt >= anchor_estimate:
                    source = "usage"
        return max(0, used), source

    def _emit_usage(self, emit, session_id: int, surface: int, system_tokens: int,
                    tools_tokens: int, envelope: str) -> None:
        used, source = self._pressure(session_id, surface, system_tokens,
                                      tools_tokens, envelope)
        limit = self._context_limit()
        emit({
            "type": "context", "action": "usage", "session_id": session_id,
            "used": used, "limit": limit, "percent": self._percent(used, limit),
            "threshold": max(512, int(limit * COMPRESS_RATIO)),
            "source": source,
            "breakdown": {
                "system": system_tokens,
                "tools": tools_tokens,
                "messages": max(0, surface - system_tokens),
            },
        })

    # ---------------- 历史 ----------------
    def _history(self, session_id: int, emit=None, base_tokens: int = 0) -> list[dict]:
        rows, summary = self._session_context(session_id)
        limit = self._context_limit()
        threshold = max(512, int(limit * COMPRESS_RATIO))
        total = estimate_rows(rows) + estimate_tokens(summary) + base_tokens
        note = ""

        # 达到档位 50% 时，把除“当前提问”外的全部历史统一压缩成一份摘要。
        if (total >= threshold and len(rows) > 1
                and self.config.get("ui.context_compress", True)):
            if emit:
                emit({"type": "context", "action": "compressing", "session_id": session_id,
                      "before": total, "limit": limit, "threshold": threshold})
            try:
                compressed, keep, changed = self._compact(session_id, rows, summary)
                if changed:
                    summary, rows = compressed, keep
                    after = estimate_rows(rows) + estimate_tokens(summary) + base_tokens
                    if emit:
                        emit({"type": "context", "action": "compressed",
                              "session_id": session_id,
                              "before": total, "after": after, "used": after,
                              "limit": limit, "percent": self._percent(after, limit),
                              "threshold": threshold, "preview": summary[:240],
                              "summarized": bool(summary), "manual": False})
            except Exception as e:
                log.warning("上下文压缩失败：%s", e)
                if emit:
                    emit({"type": "context", "action": "compress_failed",
                          "session_id": session_id,
                          "before": total, "limit": limit, "threshold": threshold,
                          "message": str(e), "manual": False})

        # 压缩后仍超预算，或用户关闭了自动压缩：只裁掉最早的消息，并明确告知。
        if estimate_rows(rows) + estimate_tokens(summary) + base_tokens > limit and len(rows) > 1:
            before = estimate_rows(rows) + estimate_tokens(summary) + base_tokens
            rows = self._trim_rows(rows, max(512, int(limit * 0.9) - base_tokens), summary)
            note = t("早期对话因上下文上限已省略。", "Earlier messages were omitted due to the context limit.")
            if emit:
                emit({"type": "context", "action": "trimmed", "session_id": session_id,
                      "before": before,
                      "after": estimate_rows(rows) + estimate_tokens(summary) + base_tokens,
                      "limit": limit, "threshold": threshold})

        out: list[dict] = []
        if summary:
            out.append({"role": "system", "content": self._summary_header() + summary})
        if note:
            out.append({"role": "system", "content": note})
        for row in rows:
            out.append({
                "role": row.get("role"),
                "content": str(row.get("content") or "")[:4000],
            })
        return out

    # ---------------- 上下文统计与压缩 ----------------
    def _context_limit(self) -> int:
        return int(self.config.get("ui.context_limit") or 131072)

    @staticmethod
    def _percent(used: int, limit: int) -> float:
        return round(used / limit * 100, 1) if limit else 0.0

    def _session_rows(self, session_id: int, upto: int = 0,
                      limit: int = 50000) -> list[dict]:
        rows = self.store.messages_after(session_id, upto, limit)
        rows = [
            row for row in rows
            if row.get("role") in ("user", "assistant")
            and str(row.get("content") or "").strip()
        ]
        return rows

    def _session_context(self, session_id: int) -> tuple[list[dict], str]:
        summary, upto = self.store.get_session_summary(session_id)
        return self._session_rows(session_id, upto), summary

    @staticmethod
    def _summary_header() -> str:
        return t(
            "以下是本次会话较早内容的摘要，请在后续回答中继续遵守其中的目标、约束和结论：\n",
            "Below is a summary of earlier parts of this conversation. Keep following its goals, constraints, and conclusions:\n",
        )

    def _fixed_cost(self) -> tuple[int, int, str]:
        """固定开销：系统提示词、工具 schema 与请求信封指纹。"""
        mode = str(self.config.get("mode") or "supervised").lower()
        tools = self.registry.schemas(exclude=exclude_for(mode))
        skills = Skills(self.config)
        memories = self.store.memories(limit=40) if self.config.get("memory.enabled", True) else []
        prompts = PromptBook(self.config).enabled()
        system_prompt = build_system_prompt(
            self.config, skills.catalog(), memories, None, prompts)
        llm = LLMClient(self.config)
        return estimate_system(system_prompt), estimate_tools(tools), llm.envelope(tools)

    def context_usage(self, session_id: int) -> dict:
        """返回当前会话的上下文占用，供界面实时展示。"""
        rows, summary = self._session_context(session_id)
        system_tokens, tools_tokens, envelope = self._fixed_cost()
        surface = system_tokens
        if summary:
            surface += estimate_system(self._summary_header() + summary)
        for row in rows:
            surface += estimate_message({
                "role": row.get("role"),
                "content": str(row.get("content") or "")[:4000],
            })
        used, source = self._pressure(session_id, surface, system_tokens,
                                      tools_tokens, envelope)
        limit = self._context_limit()
        threshold = max(512, int(limit * COMPRESS_RATIO))
        return {
            "used": used,
            "limit": limit,
            "percent": self._percent(used, limit),
            "threshold": threshold,
            "summary_tokens": estimate_tokens(summary),
            "messages": len(rows),
            "summarized": bool(summary),
            "source": source,
            "breakdown": {
                "system": system_tokens,
                "tools": tools_tokens,
                "messages": max(0, surface - system_tokens),
            },
        }

    def compress_session(self, session_id: int, emit=None) -> dict:
        """手动压缩：不受 50% 阈值限制，把整个会话统一总结成一份摘要。"""
        rows, summary = self._session_context(session_id)
        system_tokens, tools_tokens, _ = self._fixed_cost()
        base = system_tokens + tools_tokens
        if not rows:
            used = estimate_tokens(summary) + base
            return {"ok": True, "skipped": True, "reason": "empty",
                    "used": used,
                    "limit": self._context_limit(),
                    "percent": self._percent(used, self._context_limit())}

        before = estimate_rows(rows) + estimate_tokens(summary) + base
        limit = self._context_limit()
        threshold = max(512, int(limit * COMPRESS_RATIO))
        if emit:
            emit({"type": "context", "action": "compressing", "session_id": session_id,
                  "before": before, "limit": limit, "threshold": threshold,
                  "manual": True})

        compressed, keep, changed = self._compact(session_id, rows, summary)
        if not changed:
            return {"ok": True, "skipped": True, "reason": "nothing",
                    "used": before, "limit": limit,
                    "percent": self._percent(before, limit)}

        after = estimate_rows(keep) + estimate_tokens(compressed) + base
        result = {
            "ok": True,
            "skipped": False,
            "before": before,
            "after": after,
            "used": after,
            "limit": limit,
            "percent": self._percent(after, limit),
            "threshold": threshold,
            "summarized_count": len(rows) - len(keep),
            "summary_tokens": estimate_tokens(compressed),
            "messages": len(keep),
        }
        if emit:
            emit({"type": "context", "action": "compressed",
                  "session_id": session_id,
                  "before": before, "after": after, "used": after,
                  "limit": limit, "threshold": threshold,
                  "percent": result["percent"], "preview": compressed[:240],
                  "summarized": True, "manual": True,
                  "summarized_count": result["summarized_count"]})
        return result

    def _compact(self, session_id: int, rows: list[dict],
                 summary: str) -> tuple[str, list[dict], bool]:
        """全量摘要：除当前提问外全部交给模型总结，旧摘要一并合并。"""
        old, keep = split_for_summary(rows)
        if not old:
            return summary, rows, False
        compressed = self._summarize(summary, old)
        upto_id = int(old[-1].get("id") or 0)
        self.store.set_session_summary(session_id, compressed, upto_id)
        return compressed, keep, True

    def _summarize(self, previous: str, rows: list[dict]) -> str:
        """逐块把全部历史交给模型总结，再合并成一份摘要。"""
        llm = LLMClient(self.config)
        summary = (previous or "").strip()
        groups = chunks(rows)
        if not groups:
            return summary
        for group in groups:
            text = llm.complete(
                summary_prompt(summary, group),
                max_tokens=SUMMARY_MAX_TOKENS,
                temperature=0.2,
            )
            if not text:
                raise LLMError(t("模型返回了空摘要", "The model returned an empty summary"))
            summary = text.strip()
        return summary

    def _trim_rows(self, rows: list[dict], budget: int, summary: str) -> list[dict]:
        """保留最近消息；最后一条（当前提问）永不裁掉。"""
        kept = list(rows)
        while len(kept) > 1 and estimate_rows(kept) + estimate_tokens(summary) > budget:
            kept.pop(0)
        return kept

    @staticmethod
    def _user_content(text: str, attachments: list) -> list:
        head = text or "请看看这张截图"
        files = []
        images = []
        for item in attachments[:4]:
            if str(item.get("type") or "") == "file":
                name = str(item.get("name") or "附件")
                body = str(item.get("text") or "")[:32000]
                if body:
                    files.append(f"\n\n【附件 {name}】\n```\n{body}\n```")
                continue
            data = str(item.get("data") or "")
            if not data:
                continue
            url = data if data.startswith("data:") else "data:image/png;base64," + data
            images.append({"type": "image_url", "image_url": {"url": url}})
        parts = [{"type": "text", "text": head + "".join(files)}]
        parts.extend(images[:2])
        return parts

    # ---------------- 工具执行 ----------------
    def _exec_tool(self, session_id: int, tc: dict, emit, confirm, cancel,
                   ask=None, notify=None, on_control=None) -> dict:
        call_id = tc.get("id") or ("call_" + uuid.uuid4().hex[:8])
        name = (tc.get("function") or {}).get("name") or ""
        if name in ("ui_windows", "ui_tree", "ui_find", "ui_act", "app_focus_capture",
                    "screenshot_capture", "app_open", "app_launch") and on_control:
            try:
                on_control(True)
            except Exception:
                pass
        raw_args = (tc.get("function") or {}).get("arguments") or "{}"
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
            if not isinstance(args, dict):
                args = {}
        except json.JSONDecodeError:
            args = {}
        emit({"type": "tool_start", "id": call_id, "name": name, "args": args})
        started = time.perf_counter()

        tool = self.registry.get(name)
        allowed = True
        if tool is None:
            result = {"ok": False, "error": f"未知工具：{name}"}
        elif name == "ask_user":
            result = self._ask_user(args, emit, ask, cancel)
        elif tool.needs_confirm and self._confirm_required():
            allowed = self._ask_confirm(tool, args, emit, confirm, cancel)
            result = (self.registry.dispatch(name, args) if allowed
                      else {"ok": False, "error": "用户取消了这次操作", "cancelled": True})
        else:
            result = self.registry.dispatch(name, args)

        if cancel is not None and cancel.is_set() and not result.get("ok"):
            result = {"ok": False, "error": "已停止", "cancelled": True}

        ms = int((time.perf_counter() - started) * 1000)
        summary = _short(
            result.get("output") or result.get("content") or result.get("path")
            or result.get("answer") or result.get("error")
            or ("完成" if result.get("ok") else "失败")
        )
        emit({
            "type": "tool_end", "id": call_id, "name": name, "ok": bool(result.get("ok")),
            "summary": summary, "ms": ms,
        })
        self.store.add_tool_run(session_id, name, args, bool(result.get("ok")), summary, ms)

        if name == "notify_user" and result.get("ok"):
            title = str(result.get("title") or "Nexus")
            message = str(result.get("message") or "")
            if notify:
                try:
                    notify(title, message)
                except Exception:
                    pass
            emit({"type": "notify", "title": title, "message": message})

        if name == "todo_write" and result.get("ok"):
            emit({"type": "todo", "items": result.get("items") or []})
        if name in ("fs_write", "fs_edit") and result.get("ok"):
            self._record_change(result)
            if name == "fs_write" and result.get("path"):
                # 只记录到会话文件列表；单个文件的卡片改成轮末的改动汇总，避免刷屏
                self.store.add_file(session_id, result["path"], result.get("name") or "",
                                    result.get("bytes") or 0)
        if name in ("docx_write", "xlsx_write", "pptx_write", "html_to_pptx",
                    "office_edit") and result.get("ok") and result.get("path"):
            self.store.add_file(session_id, result["path"], result.get("name") or "",
                                result.get("bytes") or 0)
            emit({"type": "files", "items": [{
                "path": result["path"], "name": result.get("name") or "",
                "size": result.get("bytes") or 0,
            }]})
        if name == "app_focus_capture" and result.get("ok") and result.get("path"):
            self.store.add_file(session_id, result["path"], result.get("name") or "窗口截图", 0)
            emit({"type": "files", "items": [{
                "path": result["path"], "name": result.get("name") or "窗口截图", "size": 0,
            }]})
        if name == "screenshot_capture" and result.get("ok"):
            self.store.add_file(session_id, result.get("path", ""), "截图", 0)
            emit({"type": "files", "items": [{
                "path": result.get("path", ""), "name": "屏幕截图", "size": 0,
            }]})

        payload = _tool_content(result)
        return {"role": "tool", "tool_call_id": call_id, "content": payload}

    def _ask_user(self, args: dict, emit, ask, cancel) -> dict:
        question = str(args.get("question") or "").strip()
        if not question:
            return {"ok": False, "error": "缺少 question"}
        options = [str(o).strip()[:120] for o in (args.get("options") or []) if str(o).strip()][:6]
        allow_text = bool(args.get("allow_text", True))
        req = {
            "type": "ask_request",
            "id": "a" + uuid.uuid4().hex[:10],
            "question": question[:500],
            "options": options,
            "allow_text": allow_text,
        }
        emit(req)
        if ask is None:
            return {"ok": False, "error": "当前环境不支持提问，请直接用文字询问用户"}
        if cancel is not None and cancel.is_set():
            return {"ok": False, "cancelled": True, "error": "已停止"}
        try:
            reply = ask(req)
        except Exception:
            reply = None
        if not isinstance(reply, dict) or reply.get("cancelled"):
            return {"ok": False, "cancelled": True, "error": "用户没有回答"}
        answer = str(reply.get("answer") or "").strip()[:2000]
        if not answer and options:
            try:
                idx = int(reply.get("option"))
                if 0 <= idx < len(options):
                    answer = options[idx]
            except (TypeError, ValueError):
                pass
        if not answer:
            return {"ok": False, "error": "用户没有回答"}
        return {"ok": True, "answer": answer, "output": answer}

    def _confirm_required(self) -> bool:
        """全部下放模式下不再逐条确认，其余模式沿用工具自身的确认标记。"""
        return str(self.config.get("mode") or "supervised").lower() != "full"

    def _ask_confirm(self, tool, args: dict, emit, confirm, cancel) -> bool:
        if confirm is None:
            return False
        command = ""
        title = "需要你确认"
        detail = "这个操作会修改系统或打开外部程序。"
        if tool.name == "shell_run":
            command = " ".join([str(args.get("program") or "")] + [str(a) for a in (args.get("args") or [])])
            title = "要执行这条命令吗？"
            detail = "只读诊断命令，结果会返回给我分析。"
        elif tool.name == "app_open":
            command = str(args.get("path") or "")
            title = "要打开这个位置吗？"
            detail = "会用系统默认程序打开。"
        elif tool.name == "app_launch":
            from .tools.app_tools import APPS

            name = str(args.get("app") or "").lower()
            label = APPS.get(name, (name, []))[0]
            command = name
            title = f"要打开{label}吗？"
            detail = "会在你的桌面上启动这个程序。"
        elif tool.name == "fs_delete":
            paths = [str(p) for p in (args.get("paths") or []) if str(p).strip()]
            command = "\n".join(paths[:20])
            title = f"要删除这 {len(paths)} 个文件吗？"
            detail = "文件会移到回收站，不会直接永久删除。"
        elif tool.name == "shell_exec":
            command = str(args.get("command") or "")
            title = "要执行这条命令吗？"
            detail = "命令会以 PowerShell 运行，可能修改系统或文件。"
        elif tool.name == "schedule_task":
            interval = args.get("interval_minutes")
            command = str(args.get("prompt") or "")
            title = "要创建定时任务吗？"
            detail = (f"每 {interval} 分钟自动执行：{command}\n"
                      "定时运行不会弹确认，只能使用不需要确认的工具。")
        elif tool.name == "ui_act":
            from .tools import desktop_tools

            info = desktop_tools.describe(args)
            action = str(args.get("action") or "click")
            action_text = {
                "click": "单击", "double_click": "双击", "right_click": "右键",
                "focus": "聚焦", "invoke": "触发", "set_text": "写入文字",
                "send_keys": "发送按键",
            }.get(action, action)
            if info.get("error"):
                title = "这个操作无法执行"
                detail = f"{info['error']}\n你可以取消，或让我重新查找窗口和元素。"
            else:
                target = info.get("control") or info.get("type") or "元素"
                title = f"要在「{info.get('window') or '窗口'}」上{action_text}吗？"
                detail = f"目标：{target}（{info.get('type') or '控件'}）"
                if info.get("text"):
                    detail += f"\n内容：{info['text']}"
                command = f"{args.get('path') or ''}  {action}"
        req = {
            "type": "confirm_request",
            "id": "c" + uuid.uuid4().hex[:10],
            "title": title,
            "detail": detail,
            "command": command,
            "tool": tool.name,
        }
        emit(req)
        try:
            return bool(confirm(req))
        except Exception:
            return False

    # ---------------- 离线 ----------------
    def _offline(self, session_id: int, text: str, emit, cancel) -> None:
        emit({"type": "state", "status": "working"})
        answer = offline_answer(text, self.registry, emit, cancel)
        self._stream_answer(session_id, answer, emit)

    def _stream_answer(self, session_id: int, answer: str, emit) -> None:
        msg_id = "m" + uuid.uuid4().hex[:10]
        for i in range(0, len(answer), 60):
            emit({"type": "assistant_delta", "id": msg_id, "text": answer[i:i + 60]})
        emit({"type": "assistant_done", "id": msg_id, "text": answer})
        emit({"type": "state", "status": "idle"})
        self.store.add_message(session_id, "assistant", answer, {"offline": True})


# ---------------- 离线诊断（无模型也可用） ----------------
def _tool_call(registry: Registry, name: str, args: dict, emit, cancel) -> dict:
    if cancel is not None and cancel.is_set():
        raise Cancelled()
    call_id = "t" + uuid.uuid4().hex[:8]
    emit({"type": "tool_start", "id": call_id, "name": name, "args": args})
    started = time.perf_counter()
    result = registry.dispatch(name, args)
    ms = int((time.perf_counter() - started) * 1000)
    emit({
        "type": "tool_end", "id": call_id, "name": name, "ok": bool(result.get("ok")),
        "summary": _short(result.get("output") or result.get("error") or "完成"), "ms": ms,
    })
    return result


def offline_answer(text: str, registry: Registry, emit=None, cancel=None) -> str:
    """不依赖模型的规则式排查，断网时仍可给出可用结论。"""
    emit = _Emitter(emit)
    raw = text or ""
    low = raw.lower()

    def call(name: str, args: dict) -> dict:
        return _tool_call(registry, name, args, emit, cancel)

    if any(k in raw for k in NET_KEYS):
        ping = call("net_diag", {"action": "ping", "target": "223.5.5.5"})
        ping_ok = bool(ping.get("ok"))
        conf = call("net_diag", {"action": "ipconfig"})
        summary = conf.get("summary") or {}
        gateways = summary.get("gateway") or []
        proxy = call("net_diag", {"action": "proxy"}).get("proxy") or {}
        dns_ok = None
        dns_res = {}
        if ping_ok:
            dns_res = call("net_diag", {"action": "dns", "target": "www.baidu.com"})
            dns_ok = bool(dns_res.get("ok"))

        lines = ["我按顺序检查了这台电脑的网络："]
        lines.append(f"- 外网连通：{'正常' if ping_ok else '失败（ping 223.5.5.5 不通）'}")
        if gateways:
            lines.append(f"- 默认网关：{gateways[0]}")
        else:
            lines.append("- 默认网关：没有获取到")
        if summary.get("ipv4"):
            lines.append(f"- 本机 IP：{summary['ipv4'][0]}")
        if dns_ok is not None:
            lines.append(f"- 域名解析：{'正常' if dns_ok else '失败（nslookup 查不到）'}")
        if proxy.get("enabled"):
            lines.append(f"- 系统代理：已开启（{proxy.get('server') or '未填写地址'}）")

        lines.append("")
        lines.append("判断和建议：")
        if not ping_ok and not gateways:
            lines.append("1. 电脑没有连上路由器，属于本地网络断开。")
            lines.append("2. 检查 Wi-Fi 是否连上、网线是否插好，笔记本确认没开飞行模式。")
            lines.append("3. 如果 Wi-Fi 列表里看不到家里的网络，重启一下路由器。")
        elif not ping_ok:
            lines.append("1. 电脑连上了路由器，但出不了外网，问题多半在路由器或宽带。")
            lines.append("2. 把路由器/光猫断电 30 秒再通电，等 2 分钟重试。")
            lines.append("3. 用手机连同一个 Wi-Fi 试试：手机也不行就是宽带问题，联系运营商。")
        elif dns_ok is False:
            lines.append("1. 能连外网，但域名解析失败，这是 DNS 问题。")
            lines.append("2. 可以先清空 DNS 缓存（在对话里说「清一下 DNS 缓存」，确认后我执行）。")
            lines.append("3. 还不行就把 DNS 改成 223.5.5.5 和 119.29.29.29。")
        elif proxy.get("enabled"):
            lines.append("1. 基础网络正常，但系统代理开着，部分软件可能因此打不开网页。")
            lines.append("2. 关掉代理软件，或在 Windows 设置里关闭代理后重试。")
        else:
            lines.append("1. 基础网络正常，问题可能在目标网站或具体应用。")
            lines.append("2. 换个浏览器/重启应用再试；如果是某个网站，可能它自己故障了。")
            lines.append("3. 需要我进一步检查某个网站或端口，直接告诉我地址。")
        return "\n".join(lines)

    if any(k in raw for k in ("进程", "卡", "内存", "cpu", "占用", "风扇")):
        res = call("proc_list", {"sort": "mem", "limit": 10})
        return (
            "我看了下当前占用内存最多的程序：\n\n"
            f"{res.get('output') or res.get('error')}\n\n"
            "如果电脑卡：\n"
            "1. 优先关掉占用最高的程序（在任务管理器里结束）。\n"
            "2. 浏览器标签页太多也会很占内存，关掉不用的。\n"
            "3. 重启一次电脑能释放大部分占用。"
        )

    if any(k in raw for k in ("配置", "电脑信息", "系统信息", "什么系统", "内存多大", "磁盘")):
        res = call("sys_info", {})
        return f"这台电脑的基本情况：\n\n{res.get('output') or res.get('error')}"

    if any(k in raw for k in ("端口", "占用端口", "监听")):
        m = re.search(r"(\d{2,5})", raw)
        args = {"action": "ports"}
        if m:
            args["port"] = int(m.group(1))
        res = call("net_diag", args)
        return f"端口检查结果：\n\n{res.get('output') or res.get('error')}\n\n需要结束占用端口的程序时，告诉我程序名。"

    if any(k in raw for k in ("服务", "service")):
        res = call("service_list", {"limit": 30})
        return f"当前服务状态（节选）：\n\n{res.get('output') or res.get('error')}"

    if any(k in raw for k in ("下载", "文件", "目录", "文件夹")):
        target = str(Path.home() / "Downloads")
        res = call("fs_list", {"dir": target})
        return f"这是下载文件夹的内容：\n\n{res.get('output') or res.get('error')}"

    return (
        "现在还没有配置 AI 模型，我先用离线模式帮你。\n\n"
        "离线可以直接做的事：\n"
        "1. 网络排查：说「我上不了网」「帮我 ping 一下 xxx」「查一下 DNS」。\n"
        "2. 电脑状态：说「电脑好卡」「看看配置」「哪个程序占内存」。\n"
        "3. 文件相关：说「看看下载文件夹」（只能读，写文件请先配置模型或在设置里操作）。\n\n"
        "想要完整对话、写文档、做网页，点右上角设置填一个模型密钥即可。"
    )

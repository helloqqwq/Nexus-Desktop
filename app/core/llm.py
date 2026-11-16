"""模型客户端：OpenAI 兼容接口 + Anthropic Messages 兼容接口。

两种协议都支持流式输出、工具调用与思考内容；上层 Agent 只看到统一的
OpenAI 风格返回结构（text / reasoning / tool_calls / finish_reason）。
"""
from __future__ import annotations

import http.client
import hashlib
import json
import random
import socket
import time
import urllib.error
import urllib.request

from .config import Config
from .i18n import t


class LLMError(Exception):
    def __init__(self, message: str, hint: str = "", status: int | None = None,
                 detail: str = "", partial: str = ""):
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.status = status
        self.detail = detail
        # 流式回答中途断网时保留已经收到的文本，避免整段丢失。
        self.partial = partial


class Cancelled(Exception):
    def __init__(self, partial: str = ""):
        super().__init__("已停止")
        self.partial = partial


def _parse_data_url(url: str) -> tuple[str, str] | None:
    text = str(url or "")
    if not text.startswith("data:") or ";base64," not in text:
        return None
    head, _, data = text.partition(";base64,")
    media = head[5:].strip() or "image/png"
    return media, data


class LLMClient:
    def __init__(self, config: Config, override: dict | None = None):
        self.config = config
        self.override = dict(override or {})

    # ---------- 目标解析 ----------
    def target(self) -> dict:
        config = self.config
        provider = str(self.override.get("provider") or config.active_provider())
        model = str(self.override.get("model") or config.active_model())
        base_url = str(self.override.get("base_url")
                       or config.provider_base_url(provider)).rstrip("/")
        key = str(self.override.get("api_key") or config.provider_key(provider))
        kind = str(self.override.get("kind") or config.provider_kind(provider)).lower()
        return {
            "provider": provider,
            "provider_name": config.provider_name(provider),
            "model": model,
            "base_url": base_url,
            "api_key": key,
            "kind": "anthropic" if kind == "anthropic" else "openai",
        }

    def _settings(self) -> tuple[str, str, int, int]:
        thinking = str(self.config.get("llm.thinking") or "auto").lower()
        effort = str(self.config.get("llm.reasoning_effort") or "high").lower()
        timeout = int(self.config.get("llm.timeout") or 90)
        max_tokens = int(self.config.get("llm.max_tokens") or 65536)
        return thinking, effort, timeout, max_tokens

    def envelope(self, tools: list[dict] | None = None) -> str:
        """请求信封指纹：只有它一致时，上一轮的 usage 才能复用为锚点。"""
        target = self.target()
        thinking, effort, _, max_tokens = self._settings()
        tools_digest = hashlib.sha256(
            json.dumps(tools or [], ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        payload = {
            "provider": target["provider"],
            "model": target["model"],
            "thinking": thinking,
            "effort": effort,
            "max_tokens": max_tokens,
            "tools": tools_digest,
        }
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _normalize_openai_usage(raw) -> dict | None:
        """OpenAI 兼容用量归一：prompt_tokens 含缓存命中，需要拆开避免重复相加。"""
        if not isinstance(raw, dict):
            return None
        prompt = int(raw.get("prompt_tokens") or 0)
        output = int(raw.get("completion_tokens") or 0)
        if prompt <= 0 and output <= 0:
            return None
        details = raw.get("prompt_tokens_details") or {}
        cached = int(details.get("cached_tokens") or raw.get("prompt_cache_hit_tokens") or 0)
        cache_write = int(details.get("cache_write_tokens") or 0)
        cached = max(0, min(cached, prompt))
        return {
            "input": max(0, prompt - cached),
            "output": output,
            "cache_read": cached,
            "cache_write": cache_write,
            "total": int(raw.get("total_tokens") or (prompt + output)),
        }

    @staticmethod
    def _require_key(target: dict) -> None:
        if not target.get("api_key"):
            name = target.get("provider_name") or target.get("provider") or "模型"
            raise LLMError(
                t(f"还没有配置 {name} 的 API Key",
                  f"No API key configured for {name}"),
                t("打开设置 → 模型与 API，选择厂商并填写 Key",
                  "Open Settings → Models & API, choose a provider and enter its key"),
            )
        if not target.get("base_url"):
            raise LLMError("接口地址为空", "填写厂商的 Base URL 后再试")
        if not target.get("model"):
            raise LLMError(
                t("还没有选择模型", "No model selected"),
                t("打开设置 → 模型与 API，添加或选择一个模型",
                  "Open Settings → Models & API and choose a model"),
            )

    # ---------- 对外 ----------
    def chat(self, messages: list[dict], tools: list[dict] | None = None,
             on_delta=None, cancel=None, temperature: float = 0.3,
             on_reasoning=None, on_retry=None) -> dict:
        target = self.target()
        self._require_key(target)
        if target["kind"] == "anthropic":
            return self._chat_anthropic(messages, tools, on_delta, cancel, temperature,
                                        on_reasoning, on_retry, target)
        return self._chat_openai(messages, tools, on_delta, cancel, temperature,
                                 on_reasoning, on_retry, target)

    def complete(self, messages: list[dict], max_tokens: int = 1200,
                 temperature: float = 0.2) -> str:
        target = self.target()
        self._require_key(target)
        if target["kind"] == "anthropic":
            return self._complete_anthropic(messages, max_tokens, temperature, target)
        return self._complete_openai(messages, max_tokens, temperature, target)

    # ---------- OpenAI 兼容 ----------
    def _chat_openai(self, messages, tools, on_delta, cancel, temperature,
                     on_reasoning, on_retry, target) -> dict:
        thinking, effort, timeout, max_tokens = self._settings()
        if thinking == "enabled":
            # 强制思考时给推理留足输出空间：高 8K，最高 16K
            max_tokens = max(max_tokens, 16384 if effort == "max" else 8192)
        payload: dict = {
            "model": target["model"],
            "messages": messages,
            "stream": True,
            "temperature": temperature,
            # 让兼容服务在流末尾回传 usage；个别服务不认识该字段，下面会自动降级重试。
            "stream_options": {"include_usage": True},
        }
        # 小米 MiMo 的 OpenAI 兼容接口使用 max_completion_tokens。
        if target["provider"] == "mimo":
            payload["max_completion_tokens"] = max_tokens
        else:
            payload["max_tokens"] = max_tokens
        # auto：不发送 thinking / reasoning_effort，完全由模型自行决定这一轮是否思考；
        # enabled：强制每轮思考；disabled：明确关闭。
        if thinking == "enabled":
            payload["thinking"] = {"type": "enabled"}
            payload["reasoning_effort"] = "max" if effort == "max" else "high"
        elif thinking == "disabled":
            payload["thinking"] = {"type": "disabled"}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        url = f"{target['base_url']}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {target['api_key']}",
            "Accept": "text/event-stream",
            "User-Agent": "Nexus/0.1",
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        try:
            response = self._open(url, data, headers, timeout, on_retry=on_retry,
                                  cancel=cancel)
        except LLMError as e:
            # 少数兼容服务会拒绝 stream_options；去掉后重试一次，统计退回本地估算。
            if e.status in (400, 422):
                payload.pop("stream_options", None)
                data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                response = self._open(url, data, headers, timeout, on_retry=on_retry,
                                      cancel=cancel)
            else:
                raise
        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        calls: dict[int, dict] = {}
        finish_reason = ""
        usage_raw = None
        try:
            for raw in response:
                if cancel is not None and cancel.is_set():
                    raise Cancelled("".join(text_parts))
                line = raw.decode("utf-8", "replace").strip()
                if not line or not line.startswith("data:"):
                    continue
                chunk = line[5:].strip()
                if not chunk or chunk == "[DONE]":
                    continue
                try:
                    obj = json.loads(chunk)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj.get("usage"), dict):
                    usage_raw = obj["usage"]
                choices = obj.get("choices") or []
                if not choices:
                    continue
                choice = choices[0]
                finish_reason = choice.get("finish_reason") or finish_reason
                delta = choice.get("delta") or {}
                reason = delta.get("reasoning_content")
                if reason:
                    reasoning_parts.append(reason)
                    if on_reasoning:
                        on_reasoning(reason)
                content = delta.get("content")
                if content:
                    text_parts.append(content)
                    if on_delta:
                        on_delta(content)
                for tc in delta.get("tool_calls") or []:
                    idx = int(tc.get("index") or 0)
                    slot = calls.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                    if tc.get("id"):
                        slot["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        slot["name"] += fn["name"]
                    if fn.get("arguments"):
                        slot["arguments"] += fn["arguments"]
        except (socket.timeout, TimeoutError) as e:
            raise LLMError("模型响应超时", "网络较慢或模型负载高，请稍后重试",
                           partial="".join(text_parts)) from e
        except (http.client.HTTPException, OSError) as e:
            raise LLMError(f"连接中断：{e}", "检查网络是否稳定，或稍后重试",
                           partial="".join(text_parts)) from e
        finally:
            try:
                response.close()
            except OSError:
                pass

        return self._result(text_parts, reasoning_parts, calls, finish_reason,
                            self._normalize_openai_usage(usage_raw))

    def _complete_openai(self, messages, max_tokens, temperature, target) -> str:
        _, _, timeout, _ = self._settings()
        payload = {
            "model": target["model"],
            "messages": messages,
            "stream": False,
            "temperature": temperature,
        }
        if target["provider"] == "mimo":
            payload["max_completion_tokens"] = max(256, int(max_tokens))
        else:
            payload["max_tokens"] = max(256, int(max_tokens))
        url = f"{target['base_url']}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {target['api_key']}",
            "Accept": "application/json",
            "User-Agent": "Nexus/0.2",
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        response = self._open(url, data, headers, timeout)
        try:
            raw = response.read()
        except (socket.timeout, TimeoutError) as e:
            raise LLMError(t("模型响应超时", "Model response timed out"),
                           t("请稍后重试", "Please try again later")) from e
        finally:
            try:
                response.close()
            except OSError:
                pass
        try:
            obj = json.loads(raw.decode("utf-8", "replace"))
        except json.JSONDecodeError as e:
            raise LLMError(t("模型返回了无法解析的内容", "The model returned invalid content"),
                           "", detail=str(raw[:500])) from e
        choices = obj.get("choices") or []
        if not choices:
            raise LLMError(t("模型没有返回内容", "The model returned no content"), "",
                           detail=str(raw[:500]))
        message = choices[0].get("message") or {}
        return str(message.get("content") or "").strip()

    # ---------- Anthropic 兼容 ----------
    @staticmethod
    def _anthropic_url(base: str) -> str:
        text = str(base or "").rstrip("/")
        if text.endswith("/messages"):
            return text
        if text.endswith("/v1"):
            return text + "/messages"
        return text + "/v1/messages"

    @staticmethod
    def _anthropic_tools(tools: list[dict] | None) -> list[dict]:
        out = []
        for item in tools or []:
            fn = item.get("function") or item
            out.append({
                "name": fn.get("name") or "",
                "description": fn.get("description") or "",
                "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
            })
        return out

    @staticmethod
    def _anthropic_user_content(content) -> list[dict]:
        if isinstance(content, str):
            return [{"type": "text", "text": content}] if content else []
        blocks: list[dict] = []
        for part in content or []:
            if not isinstance(part, dict):
                continue
            kind = part.get("type")
            if kind == "text":
                blocks.append({"type": "text", "text": str(part.get("text") or "")})
            elif kind == "image_url":
                url = str((part.get("image_url") or {}).get("url") or "")
                parsed = _parse_data_url(url)
                if parsed:
                    blocks.append({
                        "type": "image",
                        "source": {"type": "base64", "media_type": parsed[0], "data": parsed[1]},
                    })
                elif url.startswith(("http://", "https://")):
                    blocks.append({"type": "image", "source": {"type": "url", "url": url}})
        return blocks

    def _anthropic_messages(self, messages: list[dict]) -> tuple[str, list[dict]]:
        system_parts: list[str] = []
        out: list[dict] = []
        for msg in messages:
            role = str(msg.get("role") or "")
            if role == "system":
                text = msg.get("content")
                if isinstance(text, str) and text.strip():
                    system_parts.append(text)
                continue
            if role == "user":
                blocks = self._anthropic_user_content(msg.get("content"))
            elif role == "assistant":
                blocks = []
                text = str(msg.get("content") or "")
                if text:
                    blocks.append({"type": "text", "text": text})
                for tc in msg.get("tool_calls") or []:
                    fn = tc.get("function") or {}
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    blocks.append({
                        "type": "tool_use",
                        "id": tc.get("id") or f"toolu_{len(blocks)}",
                        "name": fn.get("name") or "",
                        "input": args if isinstance(args, dict) else {},
                    })
            elif role == "tool":
                blocks = [{
                    "type": "tool_result",
                    "tool_use_id": msg.get("tool_call_id") or "",
                    "content": str(msg.get("content") or ""),
                }]
            else:
                continue
            if not blocks:
                continue
            # Anthropic 要求 user / assistant 交替，相邻同角色合并。
            if out and out[-1]["role"] == role:
                out[-1]["content"].extend(blocks)
            else:
                out.append({"role": role, "content": blocks})
        while out and out[0]["role"] != "user":
            out.pop(0)
        return "\n\n".join(system_parts), out

    def _chat_anthropic(self, messages, tools, on_delta, cancel, temperature,
                        on_reasoning, on_retry, target) -> dict:
        thinking, effort, timeout, max_tokens = self._settings()
        system, converted = self._anthropic_messages(messages)
        payload: dict = {
            "model": target["model"],
            "messages": converted,
            "stream": True,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if system:
            payload["system"] = system
        if thinking == "enabled":
            budget = 16384 if effort == "max" else 8192
            payload["max_tokens"] = max(payload["max_tokens"], budget + 2048)
            payload["thinking"] = {"type": "enabled", "budget_tokens": budget}
        anthropic_tools = self._anthropic_tools(tools)
        if anthropic_tools:
            payload["tools"] = anthropic_tools
            payload["tool_choice"] = {"type": "auto"}

        url = self._anthropic_url(target["base_url"])
        headers = {
            "Content-Type": "application/json",
            "x-api-key": target["api_key"],
            "Authorization": f"Bearer {target['api_key']}",
            "anthropic-version": "2023-06-01",
            "Accept": "text/event-stream",
            "User-Agent": "Nexus/0.1",
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        response = self._open(url, data, headers, timeout, on_retry=on_retry,
                              cancel=cancel)
        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        calls: dict[int, dict] = {}
        finish_reason = ""
        usage = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
        try:
            for raw in response:
                if cancel is not None and cancel.is_set():
                    raise Cancelled("".join(text_parts))
                line = raw.decode("utf-8", "replace").strip()
                if not line or not line.startswith("data:"):
                    continue
                chunk = line[5:].strip()
                if not chunk or chunk == "[DONE]":
                    continue
                try:
                    obj = json.loads(chunk)
                except json.JSONDecodeError:
                    continue
                kind = str(obj.get("type") or "")
                if kind == "error":
                    err = obj.get("error") or {}
                    raise LLMError(
                        t(f"模型服务返回错误：{err.get('message') or err.get('type') or '未知错误'}",
                          f"Model service error: {err.get('message') or err.get('type') or 'unknown'}"),
                        t("稍后重试或更换模型", "Try again later or switch models"),
                        partial="".join(text_parts),
                    )
                if kind == "message_start":
                    u = (obj.get("message") or {}).get("usage") or {}
                    usage["input"] = int(u.get("input_tokens") or 0)
                    usage["cache_read"] = int(u.get("cache_read_input_tokens") or 0)
                    usage["cache_write"] = int(u.get("cache_creation_input_tokens") or 0)
                    usage["output"] = int(u.get("output_tokens") or 0)
                    continue
                if kind == "content_block_start":
                    idx = int(obj.get("index") or 0)
                    block = obj.get("content_block") or {}
                    if block.get("type") == "tool_use":
                        calls[idx] = {
                            "id": block.get("id") or f"toolu_{idx}",
                            "name": block.get("name") or "",
                            "arguments": "",
                        }
                elif kind == "content_block_delta":
                    idx = int(obj.get("index") or 0)
                    delta = obj.get("delta") or {}
                    delta_type = str(delta.get("type") or "")
                    if delta_type == "text_delta":
                        text = str(delta.get("text") or "")
                        if text:
                            text_parts.append(text)
                            if on_delta:
                                on_delta(text)
                    elif delta_type == "thinking_delta":
                        reason = str(delta.get("thinking") or "")
                        if reason:
                            reasoning_parts.append(reason)
                            if on_reasoning:
                                on_reasoning(reason)
                    elif delta_type == "input_json_delta":
                        slot = calls.setdefault(idx, {"id": f"toolu_{idx}", "name": "", "arguments": ""})
                        slot["arguments"] += str(delta.get("partial_json") or "")
                elif kind == "message_delta":
                    finish_reason = str((obj.get("delta") or {}).get("stop_reason") or finish_reason)
                    delta_usage = obj.get("usage") or {}
                    if delta_usage.get("output_tokens") is not None:
                        usage["output"] = int(delta_usage.get("output_tokens") or 0)
        except (socket.timeout, TimeoutError) as e:
            raise LLMError("模型响应超时", "网络较慢或模型负载高，请稍后重试",
                           partial="".join(text_parts)) from e
        except (http.client.HTTPException, OSError) as e:
            raise LLMError(f"连接中断：{e}", "检查网络是否稳定，或稍后重试",
                           partial="".join(text_parts)) from e
        finally:
            try:
                response.close()
            except OSError:
                pass

        total = sum(usage.values())
        return self._result(text_parts, reasoning_parts, calls, finish_reason,
                            dict(usage, total=total) if total > 0 else None)

    def _complete_anthropic(self, messages, max_tokens, temperature, target) -> str:
        _, _, timeout, _ = self._settings()
        system, converted = self._anthropic_messages(messages)
        payload = {
            "model": target["model"],
            "messages": converted,
            "stream": False,
            "temperature": temperature,
            "max_tokens": max(256, int(max_tokens)),
        }
        if system:
            payload["system"] = system
        url = self._anthropic_url(target["base_url"])
        headers = {
            "Content-Type": "application/json",
            "x-api-key": target["api_key"],
            "Authorization": f"Bearer {target['api_key']}",
            "anthropic-version": "2023-06-01",
            "Accept": "application/json",
            "User-Agent": "Nexus/0.2",
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        response = self._open(url, data, headers, timeout)
        try:
            raw = response.read()
        except (socket.timeout, TimeoutError) as e:
            raise LLMError(t("模型响应超时", "Model response timed out"),
                           t("请稍后重试", "Please try again later")) from e
        finally:
            try:
                response.close()
            except OSError:
                pass
        try:
            obj = json.loads(raw.decode("utf-8", "replace"))
        except json.JSONDecodeError as e:
            raise LLMError(t("模型返回了无法解析的内容", "The model returned invalid content"),
                           "", detail=str(raw[:500])) from e
        blocks = obj.get("content") or []
        parts = [str(b.get("text") or "") for b in blocks if b.get("type") == "text"]
        if not parts:
            raise LLMError(t("模型没有返回内容", "The model returned no content"), "",
                           detail=str(raw[:500]))
        return "".join(parts).strip()

    @staticmethod
    def _result(text_parts, reasoning_parts, calls, finish_reason, usage=None) -> dict:
        tool_calls = []
        for idx in sorted(calls):
            slot = calls[idx]
            if not slot.get("name"):
                continue
            tool_calls.append({
                "id": slot.get("id") or f"call_{idx}",
                "type": "function",
                "function": {
                    "name": slot["name"],
                    "arguments": slot.get("arguments") or "{}",
                },
            })
        return {
            "text": "".join(text_parts),
            "reasoning": "".join(reasoning_parts),
            "tool_calls": tool_calls,
            "finish_reason": finish_reason,
            "usage": usage,
        }

    # ---------- 连接与重试 ----------
    @staticmethod
    def _retry_delay(attempt: int) -> float:
        return min(6.0, 0.8 * (2 ** (attempt - 1))) + random.uniform(0.0, 0.3)

    def _open(self, url: str, data: bytes, headers: dict, timeout: int,
              on_retry=None, cancel=None):
        """打开流式连接；弱网下对连接错误与 5xx 做指数退避重试。"""
        max_attempts = 4

        def wait_before_retry(attempt: int, reason: str) -> None:
            if cancel is not None and cancel.is_set():
                raise Cancelled("")
            delay = self._retry_delay(attempt)
            if on_retry:
                try:
                    on_retry(attempt, max_attempts - 1, round(delay, 1), reason)
                except Exception:
                    pass
            time.sleep(delay)

        for attempt in range(1, max_attempts + 1):
            try:
                req = urllib.request.Request(url, data=data, headers=headers, method="POST")
                return urllib.request.urlopen(req, timeout=timeout)
            except urllib.error.HTTPError as e:
                body = ""
                try:
                    body = e.read().decode("utf-8", "replace")[:500]
                except OSError:
                    pass
                status = e.code
                if status == 401:
                    raise LLMError(t("模型密钥无效或已过期", "The API key is invalid or expired"),
                                   t("请在设置中重新填写 API Key", "Enter a new API key in Settings"),
                                   status, body) from e
                if status == 403:
                    raise LLMError(t("没有权限访问该模型", "Access to this model is forbidden"),
                                   t("检查 Key 的权限、实名认证或模型开通状态",
                                     "Check key permissions, account verification, or model access"),
                                   status, body) from e
                if status == 402:
                    raise LLMError(
                        t("账户余额不足", "Insufficient account balance"),
                        t("请到厂商控制台充值，或在主界面切换到其他厂商",
                          "Top up in the provider console or switch to another provider"),
                        status, body,
                    ) from e
                if status == 429:
                    raise LLMError(t("请求太频繁或额度不足", "Too many requests or insufficient quota"),
                                   t("稍后再试，或检查账户余额", "Try again later or check your balance"),
                                   status, body) from e
                if status == 404:
                    raise LLMError(t("接口地址或模型名不正确", "The API URL or model name is incorrect"),
                                   t("检查设置中的接口地址与模型名", "Check the API URL and model name in Settings"),
                                   status, body) from e
                if status in (408, 500, 502, 503, 504) and attempt < max_attempts:
                    wait_before_retry(attempt, f"HTTP {status}")
                    continue
                if status >= 500:
                    raise LLMError(
                        t(f"模型服务暂时不可用（已重试 {max_attempts - 1} 次）",
                          f"The model service is temporarily unavailable after {max_attempts - 1} retries"),
                        t("服务端异常，稍后重试", "Server error, please try again later"),
                        status, body) from e
                raise LLMError(t(f"请求失败（{status}）", f"Request failed ({status})"),
                               t("检查设置后重试", "Check Settings and try again"),
                               status, body or "") from e
            except (urllib.error.URLError, OSError, socket.timeout, TimeoutError,
                    http.client.HTTPException) as e:
                if attempt < max_attempts:
                    reason = getattr(e, "reason", None) or str(e)
                    wait_before_retry(attempt, str(reason))
                    continue
                if isinstance(e, (socket.timeout, TimeoutError)):
                    raise LLMError(
                        t(f"连接模型超时（已重试 {max_attempts - 1} 次）",
                          f"Connection to the model timed out after {max_attempts - 1} retries"),
                        t("网络较慢，请稍后重试", "The network is slow, please try again later")) from e
                raise LLMError(
                    t(f"网络连接失败（已重试 {max_attempts - 1} 次）",
                      f"Network connection failed after {max_attempts - 1} retries"),
                    t("检查本机网络、代理或接口地址是否正确",
                      "Check your network, proxy, or API URL")) from e

"""DeepSeek Search / Fetch API 客户端（与聊天共用同一把密钥）。"""
from __future__ import annotations

import json
import logging
import socket
import urllib.error
import urllib.request
from urllib.parse import urlparse

from .config import Config

log = logging.getLogger("nexus.web")


class WebError(Exception):
    def __init__(self, message: str, status: int | None = None, hint: str = "",
                 kind: str = ""):
        super().__init__(message)
        self.message = message
        self.status = status
        self.hint = hint
        self.kind = kind


def _endpoint(config: Config, path: str) -> str:
    base = str(config.provider_base_url("deepseek") or "https://api.deepseek.com").rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    return base + path


def _post(config: Config, path: str, payload: dict, timeout: int = 25) -> dict:
    # 联网搜索使用 DeepSeek 的 Search / Fetch API；即使当前对话用其他厂商，
    # 也优先取 DeepSeek 的 Key，避免把别家的 Key 发到 DeepSeek。
    key = config.provider_key("deepseek") or config.api_key
    if not key:
        raise WebError("还没有配置 DeepSeek 的 API Key",
                       hint="联网搜索使用 DeepSeek Search API，请在设置 → 模型与 API 中配置 DeepSeek")
    url = _endpoint(config, path)
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
            "User-Agent": "Nexus/0.1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:400]
        except OSError:
            pass
        if body:
            log.warning("联网接口返回 %s：%s", e.code, body)
        if e.code == 401:
            raise WebError("模型密钥无效或已过期", e.code, "请在设置中重新填写 API Key") from e
        if e.code == 402:
            raise WebError("账户余额不足", e.code, "请先充值后再使用联网搜索") from e
        if e.code == 403:
            raise WebError("该网页被安全策略拒绝", e.code, "换一个公开网页再试") from e
        if e.code == 404:
            raise WebError(
                "网页不存在或无法访问（404）", e.code,
                "确认网址拼写；如果对方禁止抓取，可改用浏览器打开。",
            ) from e
        if e.code == 429:
            raise WebError("联网请求太频繁", e.code, "稍后再试") from e
        raise WebError(f"联网请求失败（{e.code}）", e.code, "对方服务暂时不可用，稍后再试") from e
    except (socket.timeout, TimeoutError) as e:
        raise WebError("联网请求超时", hint="网络较慢，稍后再试") from e
    except OSError as e:
        raise WebError(f"联网请求失败：{e}", hint="检查网络或代理设置") from e


def _probe_status(url: str, timeout: int = 6) -> int | None:
    """直接访问目标一次，拿到真实状态码；连不上返回 None。"""
    req = urllib.request.Request(
        url, method="HEAD",
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Nexus/0.1"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return int(getattr(resp, "status", 0) or 0) or 200
    except urllib.error.HTTPError as e:
        return e.code
    except (socket.timeout, TimeoutError):
        return None
    except OSError:
        return None


def _fetch_failure(url: str) -> WebError:
    """抓取接口失败时，自行探测目标，区分 DNS、404、拒绝抓取与服务器错误。"""
    host = urlparse(url).hostname or ""
    try:
        socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError):
        return WebError("域名解析失败：找不到这个网站", None,
                        "检查网址拼写与网络连接。", "dns_failure")
    except OSError:
        return WebError("无法连接到这个网站", None,
                        "检查网络或代理设置。", "connection_failed")
    status = _probe_status(url)
    if status is None:
        return WebError("无法连接到这个网站", None, "检查网络或代理设置。", "connection_failed")
    if status == 404:
        return WebError("网页不存在（404）", 404, "确认网址是否正确。", "not_found")
    if status in (401, 403):
        return WebError(f"对方拒绝抓取（HTTP {status}）", status,
                        "目标网站需要登录或禁止抓取，可改用浏览器打开。", "blocked")
    if status >= 500:
        return WebError(f"对方服务器出错（HTTP {status}）", status,
                        "稍后重试，或换其他来源。", "server_error")
    return WebError(f"网页无法抓取（HTTP {status}）", status,
                    "对方可能限制了抓取，可改用浏览器打开。", "fetch_failed")


def search(config: Config, query: str, count: int = 5, need_content: bool = False) -> list[dict]:
    payload = {
        "query": query[:128],
        "count": max(1, min(int(count), 10)),
        "need_content": bool(need_content),
    }
    data = _post(config, "/v1/tools/search", payload)
    results = data.get("results") if isinstance(data, dict) else None
    return results if isinstance(results, list) else []


def fetch(config: Config, url: str) -> dict:
    try:
        data = _post(config, "/v1/tools/fetch", {"url": url})
    except WebError as e:
        if e.status == 404:
            raise _fetch_failure(url) from e
        raise
    return data if isinstance(data, dict) else {}

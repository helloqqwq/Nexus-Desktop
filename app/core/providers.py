"""模型厂商目录：内置 8 家常用服务商 + 自定义（OpenAI / Anthropic 兼容）。

模型名称以各厂商 2026 年 11 月文档站与 /models 接口为准；厂商调整型号后，
用户可在设置里点「刷新可用模型」直接从接口读取，不必等应用更新。
"""
from __future__ import annotations

import copy

BUILTIN_PROVIDERS: list[dict] = [
    {
        "id": "mimo",
        "name": "小米 MiMo",
        "short": "MiMo",
        "mark": "Mi",
        "icon": "providers/mimo.png",
        "color": "#ff6900",
        "kind": "openai",
        "base_url": "https://api.xiaomimimo.com/v1",
        "key_url": "https://platform.xiaomimimo.com/#/console/api-keys",
        "docs_url": "https://mimo.mi.com/docs/zh-CN/quick-start/summary/model",
        "note": "全模态旗舰，1M 上下文",
        "models": [
            {"id": "mimo-v2.6-pro", "label": "MiMo V2.6 Pro", "desc": "旗舰推理，1M 上下文"},
            {"id": "mimo-v2.6-flash", "label": "MiMo V2.6 Flash", "desc": "高性价比，适合高频调用"},
        ],
    },
    {
        "id": "ark",
        "name": "火山方舟",
        "short": "方舟",
        "mark": "方",
        "icon": "providers/ark.png",
        "color": "#1664ff",
        "kind": "openai",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "key_url": "https://console.volcengine.com/ark/region:ark+cn-beijing/apiKey",
        "docs_url": "https://docs.volcengine.com/docs/ark/model-list?lang=zh",
        "note": "豆包 Seed 系列",
        "models": [
            {"id": "doubao-seed-2-1-pro", "label": "Doubao Seed 2.1 Pro", "desc": "旗舰，256K 上下文"},
            {"id": "doubao-seed-evolving", "label": "Doubao Seed Evolving", "desc": "Coding & Agent，1M 上下文"},
            {"id": "doubao-seed-2-1-turbo", "label": "Doubao Seed 2.1 Turbo", "desc": "均衡速度与成本"},
            {"id": "doubao-seed-2-1-lite", "label": "Doubao Seed 2.1 Lite", "desc": "轻量快速"},
        ],
    },
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "short": "DeepSeek",
        "mark": "DS",
        "icon": "providers/deepseek.png",
        "color": "#4d6bfe",
        "kind": "openai",
        "base_url": "https://api.deepseek.com",
        "key_url": "https://platform.deepseek.com/api_keys",
        "docs_url": "https://api-docs.deepseek.com/zh-cn/quick_start/pricing",
        "note": "V4.1 百万上下文",
        "models": [
            {"id": "deepseek-flash", "label": "DeepSeek V4.1 Flash", "desc": "日常主力，1M 上下文"},
            {"id": "deepseek-v4-pro", "label": "DeepSeek V4 Pro", "desc": "旗舰推理，1M 上下文"},
        ],
    },
    {
        "id": "siliconflow",
        "name": "硅基流动",
        "short": "硅基流动",
        "mark": "硅",
        "icon": "providers/siliconflow.png",
        "color": "#7c3aed",
        "kind": "openai",
        "base_url": "https://api.siliconflow.cn/v1",
        "key_url": "https://cloud.siliconflow.cn/account/ak",
        "docs_url": "https://www.siliconflow.cn/models?type=text",
        "note": "聚合多家开源模型",
        "models": [
            {"id": "deepseek-ai/DeepSeek-V4.1-Flash", "label": "DeepSeek V4.1 Flash"},
            {"id": "deepseek-ai/DeepSeek-V4-Pro", "label": "DeepSeek V4 Pro"},
            {"id": "Qwen/Qwen3.8-27B", "label": "Qwen3.8 27B"},
            {"id": "zai-org/GLM-5.3", "label": "GLM-5.3"},
            {"id": "moonshotai/Kimi-K2.6", "label": "Kimi K2.6"},
            {"id": "MiniMaxAI/MiniMax-M2.5", "label": "MiniMax M2.5"},
        ],
    },
    {
        "id": "kimi",
        "name": "Kimi",
        "short": "Kimi",
        "mark": "K",
        "icon": "providers/kimi.png",
        "color": "#111827",
        "kind": "openai",
        "base_url": "https://api.moonshot.cn/v1",
        "key_url": "https://platform.kimi.com/console/api-keys",
        "docs_url": "https://platform.kimi.com/docs/models",
        "note": "K3.1 百万上下文",
        "models": [
            {"id": "kimi-k3.1-pro", "label": "Kimi K3.1 Pro", "desc": "旗舰，1M 上下文"},
            {"id": "kimi-k3.1-pro-highspeed", "label": "Kimi K3.1 Pro 高速版", "desc": "2-3 倍速度"},
            {"id": "kimi-k3", "label": "Kimi K3", "desc": "上一代旗舰，1M 上下文"},
        ],
    },
    {
        "id": "glm",
        "name": "智谱 GLM",
        "short": "GLM",
        "mark": "G",
        "icon": "providers/glm.png",
        "color": "#0e7490",
        "kind": "openai",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "key_url": "https://open.bigmodel.cn/usercenter/apikeys",
        "docs_url": "https://docs.bigmodel.cn/cn/guide/start/model-overview",
        "note": "GLM-5.3 旗舰",
        "models": [
            {"id": "glm-5.3", "label": "GLM-5.3", "desc": "旗舰，1M 上下文"},
            {"id": "glm-5.3-flash", "label": "GLM-5.3 Flash", "desc": "多模态普惠"},
            {"id": "glm-5.3-flashx", "label": "GLM-5.3 FlashX", "desc": "更快更流畅"},
            {"id": "glm-4.7", "label": "GLM-4.7", "desc": "通用对话与智能体"},
            {"id": "glm-4.7-flashx", "label": "GLM-4.7 FlashX", "desc": "轻量高速"},
        ],
    },
    {
        "id": "minimax",
        "name": "MiniMax",
        "short": "MiniMax",
        "mark": "M",
        "icon": "providers/minimax.png",
        "color": "#e11d48",
        "kind": "openai",
        "base_url": "https://api.minimaxi.com/v1",
        "key_url": "https://platform.minimaxi.com/user-center/basic-information/interface-key",
        "docs_url": "https://platform.minimaxi.com/docs/api-reference/api-overview",
        "note": "M3 / M2.7 系列",
        "models": [
            {"id": "MiniMax-M3", "label": "MiniMax M3", "desc": "最新旗舰，1M 上下文"},
            {"id": "MiniMax-M2.7", "label": "MiniMax M2.7"},
            {"id": "MiniMax-M2.7-highspeed", "label": "MiniMax M2.7 高速版"},
            {"id": "MiniMax-M2.5", "label": "MiniMax M2.5"},
        ],
    },
    {
        "id": "qwen",
        "name": "通义千问",
        "short": "千问",
        "mark": "Q",
        "icon": "providers/qwen.png",
        "color": "#2563eb",
        "kind": "openai",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "key_url": "https://bailian.console.aliyun.com/?apiKey=1",
        "docs_url": "https://help.aliyun.com/zh/model-studio/text-generation-model/",
        "note": "Qwen3.8 / 3.7",
        "models": [
            {"id": "qwen3.8-max", "label": "Qwen3.8 Max", "desc": "旗舰"},
            {"id": "qwen3.8-flash", "label": "Qwen3.8 Flash", "desc": "成本优先"},
            {"id": "qwen3.7-max", "label": "Qwen3.7 Max"},
            {"id": "qwen3.7-plus", "label": "Qwen3.7 Plus", "desc": "均衡之选"},
            {"id": "qwen3-coder-plus", "label": "Qwen3 Coder Plus"},
            {"id": "qwen-max", "label": "Qwen Max（稳定版）"},
        ],
    },
]

CUSTOM_PROVIDER: dict = {
    "id": "custom",
    "name": "自定义",
    "short": "自定义",
    "mark": "+",
    "icon": "",
    "color": "#64748b",
    "kind": "openai",
    "base_url": "",
    "key_url": "",
    "docs_url": "",
    "note": "OpenAI / Anthropic 兼容接口",
    "models": [],
}

BUILTIN_IDS = tuple(item["id"] for item in BUILTIN_PROVIDERS)
_INDEX = {item["id"]: item for item in BUILTIN_PROVIDERS}
_INDEX[CUSTOM_PROVIDER["id"]] = CUSTOM_PROVIDER


def catalog() -> list[dict]:
    """返回完整目录（含自定义槽位），供前端渲染九宫格。"""
    items = copy.deepcopy(BUILTIN_PROVIDERS)
    items.append(copy.deepcopy(CUSTOM_PROVIDER))
    return items


def get(provider_id: str) -> dict | None:
    item = _INDEX.get(str(provider_id or ""))
    return copy.deepcopy(item) if item else None


def is_builtin(provider_id: str) -> bool:
    return str(provider_id or "") in BUILTIN_IDS


def default_model(provider_id: str) -> str:
    item = _INDEX.get(str(provider_id or ""))
    if not item or not item.get("models"):
        return ""
    return str(item["models"][0]["id"])


def model_label(provider_id: str, model_id: str) -> str:
    item = _INDEX.get(str(provider_id or ""))
    for model in (item or {}).get("models") or []:
        if model.get("id") == model_id:
            return str(model.get("label") or model_id)
    return str(model_id or "")


def default_base_url(provider_id: str) -> str:
    item = _INDEX.get(str(provider_id or ""))
    return str((item or {}).get("base_url") or "")

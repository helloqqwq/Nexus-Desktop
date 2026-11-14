"""系统诊断工具（只读）+ 需确认的修复动作。"""
from __future__ import annotations

from .. import diag
from ..config import Config
from ..safety import Safety
from .registry import Registry, Tool


def register(reg: Registry, config: Config, safety: Safety) -> None:
    def net_diag_tool(args: dict) -> dict:
        res = diag.net_diag(
            action=str(args.get("action") or "ipconfig"),
            target=str(args.get("target") or ""),
            port=args.get("port"),
            limit=args.get("limit"),
        )
        safety.audit("net_diag", {"action": args.get("action"), "target": args.get("target"),
                                  "ok": res.get("ok")})
        return res

    def proc_list_tool(args: dict) -> dict:
        return diag.proc_list(sort=str(args.get("sort") or "mem"), limit=args.get("limit") or 15)

    def sys_info_tool(args: dict) -> dict:
        return diag.sys_info()

    def service_list_tool(args: dict) -> dict:
        return diag.service_list(keyword=str(args.get("filter") or ""), limit=args.get("limit") or 30)

    reg.add(Tool(
        name="net_diag",
        description=(
            "网络诊断（只读）。action 可选：ping/dns/ipconfig/route/arp/wifi/proxy/ports/tcp。"
            "ping/dns 用 target 指定域名或 IP；ports 用 port 过滤端口；tcp 用 target+port 测连通。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["ping", "dns", "ipconfig", "route", "arp", "wifi", "proxy", "ports", "tcp"],
                },
                "target": {"type": "string", "description": "域名或 IP"},
                "port": {"type": "integer", "description": "端口号"},
                "limit": {"type": "integer", "description": "最多返回条数"},
            },
            "required": ["action"],
        },
        handler=net_diag_tool,
        tag="diag",
    ))
    reg.add(Tool(
        name="proc_list",
        description="列出正在运行的程序与内存占用，用于判断卡顿、内存占用异常。",
        parameters={
            "type": "object",
            "properties": {
                "sort": {"type": "string", "enum": ["mem", "name", "pid"]},
                "limit": {"type": "integer"},
            },
        },
        handler=proc_list_tool,
        tag="diag",
    ))
    reg.add(Tool(
        name="sys_info",
        description="查看本机系统信息：系统版本、CPU、内存、磁盘、本机 IP。",
        parameters={"type": "object", "properties": {}},
        handler=sys_info_tool,
        tag="diag",
    ))
    reg.add(Tool(
        name="service_list",
        description="查看 Windows 服务及其运行状态。filter 在完整服务列表中匹配，limit 只限制显示条数；返回总服务数与匹配数。",
        parameters={
            "type": "object",
            "properties": {
                "filter": {"type": "string", "description": "服务名关键词"},
                "limit": {"type": "integer"},
            },
        },
        handler=service_list_tool,
        tag="diag",
    ))

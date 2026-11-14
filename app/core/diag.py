"""系统诊断：只读命令白名单、结果解析与修复动作。"""
from __future__ import annotations

import csv
import ctypes
import io
import os
import re
import socket
import subprocess
import time
from ctypes import wintypes
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
MAX_OUTPUT = 6000


def _decode(data: bytes) -> str:
    for enc in ("utf-8", "gbk", "mbcs"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", "replace")


def run_cmd(args: list[str], timeout: int = 20, max_output: int = MAX_OUTPUT) -> dict:
    """执行白名单命令（由调用方保证 args 来自本模块），返回可展示文本。"""
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        )
        out = _decode(proc.stdout).strip()
        err = _decode(proc.stderr).strip()
        text = out if out else err
        return {
            "ok": proc.returncode == 0,
            "code": proc.returncode,
            "output": text[:max_output] if max_output > 0 else text,
            "truncated": bool(max_output > 0 and len(text) > max_output),
            "cmd": " ".join(args),
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "code": -1, "output": f"命令超时（{timeout}s）：{' '.join(args)}", "cmd": " ".join(args)}
    except FileNotFoundError:
        return {"ok": False, "code": -1, "output": f"系统命令不存在：{args[0]}", "cmd": " ".join(args)}
    except OSError as e:
        return {"ok": False, "code": -1, "output": f"命令执行失败：{e}", "cmd": " ".join(args)}


def _grab(text: str, *patterns: str) -> list[str]:
    found: list[str] = []
    for pat in patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            val = m.group(1).strip()
            if val and val not in found:
                found.append(val)
    return found


_ADDR = re.compile(r"^[0-9A-Fa-f:.%]+$")


def _addr_tokens(text: str) -> list[str]:
    out = []
    for token in re.split(r"[\s,，]+", text or ""):
        token = token.split("(")[0].strip()
        if token and _ADDR.match(token) and ("." in token or ":" in token):
            out.append(token)
    return out


def _values_after(lines: list[str], *labels: str) -> list[str]:
    """取标签行及其后续缩进续行里的地址（ipconfig 的网关/ DNS 会换行）。"""
    found: list[str] = []
    collecting = False
    for line in lines:
        matched = False
        for label in labels:
            if re.search(label, line, re.IGNORECASE):
                found.extend(_addr_tokens(line.split(":", 1)[-1] if ":" in line else
                                          line.split("：", 1)[-1]))
                collecting = True
                matched = True
                break
        if matched:
            continue
        if not collecting:
            continue
        stripped = line.strip()
        if not stripped:
            collecting = False
            continue
        if _addr_tokens(stripped) and len(_addr_tokens(stripped)) == len(stripped.split()):
            found.extend(_addr_tokens(stripped))
            continue
        collecting = False
    seen: list[str] = []
    for item in found:
        if item not in seen:
            seen.append(item)
    return seen


def _adapters(text: str) -> list[list[str]]:
    """按“适配器标题行”切分；ipconfig /all 在标题后紧跟着一个空行。"""
    blocks: list[list[str]] = []
    cur: list[str] | None = None
    for line in text.splitlines():
        if line and line[0] not in (" ", "\t") and line.rstrip().endswith((":", "：")):
            if cur:
                blocks.append(cur)
            cur = [line]
        elif cur is not None:
            cur.append(line)
    if cur:
        blocks.append(cur)
    return blocks


def ipconfig_summary(text: str) -> dict:
    adapters = []
    all_ipv4: list[str] = []
    gateways: list[str] = []
    dns: list[str] = []
    connected: list[str] = []
    offline: list[str] = []
    dhcp_values: list[bool] = []
    for block in _adapters(text):
        name = block[0].rstrip(":：").strip()
        body = "\n".join(block[1:])
        is_off = ("媒体已断开" in body) or ("Media disconnected" in body)
        ipv4 = [v for v in _values_after(block, r"IPv4 地址", r"IPv4 Address") if "." in v]
        gateway = _values_after(block, r"默认网关", r"Default Gateway")
        servers = _values_after(block, r"DNS 服务器", r"DNS Servers")
        dhcp_flag = None
        m = re.search(r"DHCP 已启用[^:：]*[:：]\s*(\S+)", body) or \
            re.search(r"DHCP Enabled[^:]*:\s*(\S+)", body, re.IGNORECASE)
        if m:
            dhcp_flag = m.group(1).lower() in ("是", "yes", "true")
        item = {
            "name": name,
            "connected": not is_off,
            "ipv4": ipv4,
            "gateway": gateway,
            "dns": servers,
            "dhcp": dhcp_flag,
        }
        adapters.append(item)
        for value in ipv4:
            if value not in all_ipv4:
                all_ipv4.append(value)
        if is_off:
            offline.append(name)
            dhcp_values.append(False)
            continue
        connected.append(name)
        if dhcp_flag is not None:
            dhcp_values.append(dhcp_flag)
        for value in gateway:
            if value not in gateways:
                gateways.append(value)
        for value in servers:
            if value not in dns:
                dns.append(value)
    dhcp = None
    if dhcp_values:
        dhcp = True if any(dhcp_values) else False
    return {
        "adapters": adapters,
        "ipv4": all_ipv4,
        "gateway": gateways,
        "dns": dns,
        "connected_adapters": connected,
        "disconnected_adapters": offline,
        "disconnected": not connected,
        "dhcp": dhcp,
    }


_PING_FIELDS = {
    "sent": (re.compile(r"已发送\s*=\s*(\d+)"), re.compile(r"Sent\s*=\s*(\d+)", re.IGNORECASE)),
    "received": (re.compile(r"已接收\s*=\s*(\d+)"), re.compile(r"Received\s*=\s*(\d+)", re.IGNORECASE)),
    "lost": (re.compile(r"丢失\s*=\s*(\d+)"), re.compile(r"Lost\s*=\s*(\d+)", re.IGNORECASE)),
}


def _ping_stat(text: str, key: str) -> int | None:
    for pattern in _PING_FIELDS[key]:
        m = pattern.search(text)
        if m:
            return int(m.group(1))
    return None


_PING_OK = re.compile(r"(?:TTL[=＝]\d+|时间[=<＝]\s*\d+\s*ms|time[=<]\s*\d+\s*ms)", re.IGNORECASE)
_PING_BAD = re.compile(
    r"无法访问目标主机|无法访问目标网络|请求超时|传输失败|一般故障|"
    r"Destination (?:host|net|port) unreachable|Request timed out|TTL expired|General failure",
    re.IGNORECASE,
)


def _ping_counts(text: str, count: int) -> dict:
    """按应答正文统计；Windows 不可达时会由本机回 ICMP 错误，统计行仍算“已接收”。"""
    ok_replies = 0
    bad_replies = 0
    for line in text.splitlines():
        if not re.search(r"(?:来自|Reply from|From)\s", line, re.IGNORECASE):
            continue
        if _PING_BAD.search(line):
            bad_replies += 1
        elif _PING_OK.search(line):
            ok_replies += 1
    sent = _ping_stat(text, "sent")
    lost = _ping_stat(text, "lost")
    if ok_replies or bad_replies:
        received = ok_replies
        sent = sent if sent is not None else ok_replies + bad_replies
        lost = max(0, sent - ok_replies)
    else:
        received = _ping_stat(text, "received")
        if received is None:
            received = 0
        sent = sent if sent is not None else count
        lost = lost if lost is not None else max(0, sent - received)
    stats = {"sent": sent, "received": received, "lost": lost}
    if bad_replies:
        stats["icmp_errors"] = bad_replies
    m = re.search(r"(平均|Average)\s*=\s*(\d+)\s*ms", text, re.IGNORECASE)
    if m and received:
        stats["avg_ms"] = int(m.group(2))
    return stats


def net_ping(host: str, count: int = 4) -> dict:
    host = (host or "223.5.5.5").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.:\-]{1,80}", host):
        return {"ok": False, "output": "主机名不合法"}
    count = max(1, min(int(count or 4), 10))
    res = run_cmd(["ping", "-n", str(count), host], timeout=30)
    stats = _ping_counts(res["output"], count)
    reachable = stats["received"] > 0
    res.update(stats)
    res.update({
        "ok": reachable,
        "success": reachable,
        "reachable": reachable,
        "host": host,
    })
    if not reachable:
        res["error"] = f"{host} 不可达（收到 {res['received']}/{res['sent']} 个有效回复）"
        if res.get("icmp_errors"):
            res["hint"] = (
                "本机收到的是 ICMP 错误回复（无法访问目标主机/请求超时），不是目标本身的应答；"
                "说明目标不在线、被防火墙拦截或网段不通。"
            )
        else:
            res["hint"] = "确认目标地址与网络连接；若对方禁 ping，改用 net_diag 的 tcp 动作测端口。"
    peer = re.search(r"(?:来自|From)\s+([0-9A-Fa-f:.]+)", res["output"])
    if peer:
        res["peer"] = peer.group(1)
        res["family"] = "IPv6" if ":" in peer.group(1) else "IPv4"
        if not reachable:
            res["peer_note"] = "该地址是本机回送错误信息的来源，不是目标地址本身"
    is_ip_literal = bool(re.fullmatch(r"[0-9.]+", host)) or ":" in host
    if not is_ip_literal:
        # 主机名会由系统挑一个协议栈；再测另一栈，避免“IPv6 通、IPv4 不通”被漏掉。
        other = "-4" if res.get("family") == "IPv6" else "-6"
        key = "ipv4" if other == "-4" else "ipv6"
        probe = run_cmd(["ping", other, "-n", str(count), host], timeout=30)
        pstats = _ping_counts(probe["output"], count)
        res[key] = {"ok": pstats["received"] > 0, **pstats}
    res["exit_code"] = res.get("code")
    res["code"] = 0 if reachable else 1
    return res


_DNS_FAIL = re.compile(
    r"\*\*\*|can't find|non-existent domain|找不到|不存在的域|请求超时|timed out",
    re.IGNORECASE,
)


def _dns_answers(text: str) -> list[str]:
    """只取“名称/Name”应答段里的地址，避免把 DNS 服务器地址当成解析结果。"""
    lines = text.splitlines()
    start = -1
    for idx, line in enumerate(lines):
        if re.match(r"\s*(名称|Name)\s*[:：]", line, re.IGNORECASE):
            start = idx
            break
    if start < 0:
        return []
    answers: list[str] = []
    in_address = False
    for line in lines[start + 1:]:
        stripped = line.strip()
        if re.match(r"(Aliases|别名)\s*[:：]", stripped, re.IGNORECASE):
            break
        m = re.match(r"(Addresses|Address|地址)\s*[:：]\s*(.+)$", stripped, re.IGNORECASE)
        if m:
            in_address = True
            answers.extend(x for x in m.group(2).split() if re.fullmatch(r"[0-9A-Fa-f:.]+", x))
            continue
        if in_address and stripped:
            if re.fullmatch(r"[0-9A-Fa-f:.]+", stripped):
                answers.append(stripped)
                continue
            break
    return answers


def net_dns(domain: str = "www.baidu.com") -> dict:
    domain = (domain or "www.baidu.com").strip()
    if not re.fullmatch(r"[A-Za-z0-9.\-]{1,120}", domain):
        return {"ok": False, "output": "域名不合法"}
    res = run_cmd(["nslookup", domain], timeout=20)
    answers = _dns_answers(res["output"])
    resolved = bool(answers)
    res.update({
        "ok": resolved,
        "success": resolved,
        "resolved": resolved,
        "domain": domain,
        "addresses": answers,
    })
    if not resolved:
        res["error"] = f"无法解析 {domain}：DNS 没有返回地址记录"
        if _DNS_FAIL.search(res["output"]):
            res["hint"] = "域名可能不存在或返回了 NXDOMAIN；确认拼写后重试，或换已知域名判断 DNS 是否可用。"
        else:
            res["hint"] = "输出里只有 DNS 服务器信息，没有应答地址；可能是 DNS 超时或该域名没有 A/AAAA 记录。"
    res["exit_code"] = res.get("code")
    res["code"] = 0 if resolved else 1
    return res


def net_ipconfig() -> dict:
    res = run_cmd(["ipconfig", "/all"], timeout=25)
    res["summary"] = ipconfig_summary(res["output"])
    return res


def net_route(limit: int = 0) -> dict:
    res = run_cmd(["route", "print", "-4"], timeout=25, max_output=0)
    entries: list[dict] = []
    collecting = False
    for line in res["output"].splitlines():
        stripped = line.strip()
        if re.match(r"^(活动路由|Active Routes)\s*:?\s*$", stripped, re.IGNORECASE):
            collecting = True
            continue
        if not collecting:
            continue
        if not stripped:
            if entries:
                break
            continue
        if set(stripped) <= set("-= "):
            continue
        parts = stripped.split()
        if len(parts) < 5 or not re.fullmatch(r"[0-9.]+", parts[0]):
            continue
        entries.append({
            "destination": parts[0],
            "netmask": parts[1],
            "gateway": parts[2],
            "interface": parts[3],
            "metric": parts[4],
        })
    total = len(entries)
    res["entries"] = entries
    res["total"] = total
    try:
        cap = int(limit or 0)
    except (TypeError, ValueError):
        cap = 0
    if cap <= 0 or not entries:
        res["truncated"] = False
        return res
    cap = max(1, min(cap, 200))
    shown = entries[:cap]
    lines = [f"路由表共 {total} 条"]
    lines.extend(
        f"{e['destination']:<16} {e['netmask']:<16} {e['gateway']:<16} "
        f"{e['interface']:<16} {e['metric']}" for e in shown
    )
    res["output"] = "\n".join(lines)
    res["entries"] = shown
    res["truncated"] = total > len(shown)
    if res["truncated"]:
        res["hint"] = f"已达到 limit={cap}，仅显示前 {len(shown)} 条（共 {total} 条）；调大 limit 可看全部。"
    return res


_ARP_MAC = re.compile(r"^[0-9a-fA-F]{2}(-[0-9a-fA-F]{2}){5}$")


def net_arp(limit: int = 30) -> dict:
    res = run_cmd(["arp", "-a"], timeout=20, max_output=0)
    entries = []
    iface = ""
    for line in res["output"].splitlines():
        stripped = line.strip()
        m = re.match(r"^(?:接口|Interface)\s*[:：]\s*([0-9.]+)", stripped)
        if m:
            iface = m.group(1)
            continue
        parts = stripped.split()
        if len(parts) < 2 or not re.fullmatch(r"[0-9.]+", parts[0]):
            continue
        if not (_ARP_MAC.match(parts[1]) or parts[1].lower() == "ff-ff-ff-ff-ff-ff"):
            continue
        entries.append({
            "interface": iface,
            "ip": parts[0],
            "mac": parts[1],
            "type": parts[2] if len(parts) > 2 else "",
        })
    total = len(entries)
    limit = max(1, min(int(limit or 30), 200))
    shown = entries[:limit]
    lines = [f"ARP 表共 {total} 条"]
    lines.extend(
        f"{e['interface']:<16} {e['ip']:<16} {e['mac']}  {e['type']}" for e in shown
    )
    result = {
        "ok": res["ok"],
        "output": "\n".join(lines),
        "entries": shown,
        "total": total,
        "truncated": total > len(shown),
        "cmd": res["cmd"],
    }
    if total > len(shown):
        result["hint"] = f"已达到 limit={limit}，仅显示前 {len(shown)} 条（共 {total} 条）；调大 limit 可看全部。"
    return result


def net_wifi() -> dict:
    return run_cmd(["netsh", "wlan", "show", "interfaces"], timeout=20)


def net_proxy() -> dict:
    info = {"enabled": False, "server": "", "bypass": ""}
    try:
        import winreg

        path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            try:
                info["enabled"] = bool(winreg.QueryValueEx(key, "ProxyEnable")[0])
            except FileNotFoundError:
                pass
            try:
                info["server"] = str(winreg.QueryValueEx(key, "ProxyServer")[0])
            except FileNotFoundError:
                pass
            try:
                info["bypass"] = str(winreg.QueryValueEx(key, "ProxyOverride")[0])
            except FileNotFoundError:
                pass
    except OSError as e:
        return {"ok": False, "output": f"读取代理设置失败：{e}", "proxy": info}
    configured = bool(info["server"])
    info["configured"] = configured
    info["active_server"] = info["server"] if info["enabled"] else ""
    if info["enabled"]:
        text = "系统代理：已开启"
        if info["server"]:
            text += f"\n代理服务器：{info['server']}"
    else:
        text = "系统代理：未开启"
        if configured:
            text += f"\n（已配置 {info['server']}，但当前未启用；不要把该地址当成正在使用的代理）"
    return {"ok": True, "output": text, "proxy": info}


def _pid_names() -> dict[int, str]:
    res = run_cmd(["tasklist", "/fo", "csv", "/nh"], timeout=20, max_output=0)
    mapping: dict[int, str] = {}
    for row in csv.reader(io.StringIO(res["output"])):
        if len(row) >= 2:
            try:
                mapping[int(row[1])] = row[0]
            except ValueError:
                continue
    return mapping


def net_ports(port: int | None = None, limit: int = 30) -> dict:
    res = run_cmd(["netstat", "-ano", "-p", "tcp"], timeout=25, max_output=0)
    names = _pid_names()
    rows = []
    for line in res["output"].splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() != "TCP":
            continue
        local, foreign, state, pid_raw = parts[1], parts[2], parts[3], parts[4]
        if state.upper() != "LISTENING":
            continue
        try:
            pid = int(pid_raw)
        except ValueError:
            continue
        local_port = int(local.rsplit(":", 1)[-1]) if ":" in local else -1
        if port and local_port != int(port):
            continue
        rows.append({
            "local": local,
            "port": local_port,
            "pid": pid,
            "process": names.get(pid, "未知"),
        })
    total = len(rows)
    cap = max(1, min(int(limit or 30), 100))
    shown = rows[:cap]
    text = "\n".join(f"{r['local']}  PID {r['pid']}  {r['process']}" for r in shown)
    result = {
        "ok": True,
        "output": text or ("未发现监听端口" if not port else f"端口 {port} 未被监听"),
        "ports": shown,
        "total": total,
        "truncated": total > len(shown),
    }
    hints = []
    if result["truncated"]:
        hints.append(f"已达到 limit={cap}，仅显示前 {len(shown)} 条（共 {total} 条）；调大 limit 可看全部。")
    if any(r["process"] == "未知" for r in shown):
        hints.append("部分进程名显示为“未知”，通常是权限不足；可用 proc_list 按 PID 交叉核对。")
    if hints:
        result["hint"] = " ".join(hints)
    return result


def net_tcp(host: str, port: int) -> dict:
    host = (host or "127.0.0.1").strip()
    try:
        port = int(port)
    except (TypeError, ValueError):
        return {"ok": False, "output": "端口不合法"}
    start = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=4):
            ms = int((time.perf_counter() - start) * 1000)
            return {"ok": True, "output": f"{host}:{port} 可连接（{ms}ms）", "latency_ms": ms}
    except OSError as e:
        return {"ok": False, "output": f"{host}:{port} 无法连接：{e}"}


NET_ACTIONS = {
    "ping": lambda target, port, limit: net_ping(target or "223.5.5.5"),
    "dns": lambda target, port, limit: net_dns(target or "www.baidu.com"),
    "ipconfig": lambda target, port, limit: net_ipconfig(),
    "route": lambda target, port, limit: net_route(limit or 0),
    "arp": lambda target, port, limit: net_arp(limit or 30),
    "wifi": lambda target, port, limit: net_wifi(),
    "proxy": lambda target, port, limit: net_proxy(),
    "ports": lambda target, port, limit: net_ports(port, limit or 30),
    "tcp": lambda target, port, limit: net_tcp(target or "127.0.0.1", port or 80),
}


def net_diag(action: str = "ipconfig", target: str = "", port=None, limit=None) -> dict:
    fn = NET_ACTIONS.get((action or "ipconfig").lower())
    if not fn:
        return {"ok": False, "output": f"不支持的诊断动作：{action}（可用：{', '.join(NET_ACTIONS)}）"}
    res = fn(target, port, limit)
    res["action"] = action
    return res


# ---------------- 进程 / 系统 / 服务 ----------------
def _mem_kb(text: str) -> int:
    digits = re.sub(r"[^0-9]", "", text or "")
    return int(digits) if digits else 0


def proc_list(sort: str = "mem", limit: int = 15) -> dict:
    res = run_cmd(["tasklist", "/fo", "csv", "/nh"], timeout=25, max_output=0)
    items = []
    for row in csv.reader(io.StringIO(res["output"])):
        if len(row) < 5:
            continue
        try:
            pid = int(row[1])
        except ValueError:
            continue
        items.append({
            "name": row[0],
            "pid": pid,
            "session": row[2],
            "mem_kb": _mem_kb(row[4]),
        })
    if sort == "name":
        items.sort(key=lambda x: x["name"].lower())
    elif sort == "pid":
        items.sort(key=lambda x: x["pid"])
    else:
        items.sort(key=lambda x: x["mem_kb"], reverse=True)
    requested = int(limit or 15)
    cap = max(1, min(requested, 60))
    items = items[:cap]
    text = "\n".join(
        f"{i['name']:<28} PID {i['pid']:<7} 内存 {i['mem_kb'] / 1024:.1f} MB" for i in items
    )
    result = {"ok": res["ok"], "output": text, "items": items}
    if requested > 60:
        result["truncated"] = True
        result["hint"] = f"单次最多返回 60 项（limit={requested} 已按上限截断）；可改用 sort 缩小范围。"
    return result


class _MEMSTAT(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _memory() -> dict:
    try:
        stat = _MEMSTAT()
        stat.dwLength = ctypes.sizeof(_MEMSTAT)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            return {
                "total_gb": round(stat.ullTotalPhys / 1024 ** 3, 1),
                "avail_gb": round(stat.ullAvailPhys / 1024 ** 3, 1),
                "percent": int(stat.dwMemoryLoad),
            }
    except OSError:
        pass
    return {}


def sys_info() -> dict:
    import platform
    import shutil

    mem = _memory()
    try:
        disk = shutil.disk_usage(Path.home().anchor or "C:\\")
        disk_info = {
            "total_gb": round(disk.total / 1024 ** 3, 1),
            "free_gb": round(disk.free / 1024 ** 3, 1),
        }
    except OSError:
        disk_info = {}
    try:
        ips = socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        ips = []
    version = platform.version()
    try:
        build = int(version.split(".")[-1])
    except ValueError:
        build = 0
    # Windows 11 从 build 22000 起；platform.release() 在 Win11 上仍返回 10。
    os_name = "Windows 11" if build >= 22000 else f"Windows {platform.release()}"
    info = {
        "hostname": socket.gethostname(),
        "user": os.environ.get("USERNAME", ""),
        "os": f"{os_name} ({version})",
        "cpu": os.environ.get("PROCESSOR_IDENTIFIER", platform.processor() or ""),
        "cpu_count": os.cpu_count(),
        "memory": mem,
        "disk": disk_info,
        "ipv4": ips,
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    lines = [
        f"电脑名称：{info['hostname']}",
        f"用户：{info['user']}",
        f"系统：{info['os']}",
        f"处理器：{info['cpu'] or '未知'}，{info['cpu_count']} 核",
    ]
    if mem:
        lines.append(f"内存：{mem['avail_gb']} GB 可用 / {mem['total_gb']} GB（已用 {mem['percent']}%）")
    if disk_info:
        lines.append(f"磁盘 {Path.home().anchor}：{disk_info['free_gb']} GB 可用 / {disk_info['total_gb']} GB")
    if ips:
        lines.append(f"本机 IP：{', '.join(ips)}")
    return {"ok": True, "output": "\n".join(lines), "info": info}


def service_list(keyword: str = "", limit: int = 30) -> dict:
    # 先取完整服务列表再过滤；run_cmd 默认的 6000 字截断只够十几项，
    # 会把 C 开头的服务全部截掉，导致按名字过滤永远查不到。
    res = run_cmd(["sc", "query", "type=", "service", "state=", "all"],
                  timeout=30, max_output=0)
    services = []
    name = None
    for line in res["output"].splitlines():
        line = line.strip()
        if line.upper().startswith("SERVICE_NAME:"):
            name = line.split(":", 1)[1].strip()
        elif line.upper().startswith("STATE") and name:
            raw = line.split(":", 1)[1].strip()
            m = re.match(r"(\d+)\s+(\S+)", raw)
            state = m.group(2) if m else raw
            code = int(m.group(1)) if m else None
            services.append({"name": name, "state": state, "state_code": code})
            name = None
    total = len(services)
    matched = total
    if keyword:
        kw = keyword.lower()
        services = [s for s in services if kw in s["name"].lower() or kw in s["state"].lower()]
        matched = len(services)
    limit = max(1, min(int(limit or 30), 200))
    shown = services[:limit]
    lines = [f"服务总数：{total}"]
    if keyword:
        lines.append(f"匹配「{keyword}」：{matched} 项")
    lines.extend(f"{s['name']:<40} {s['state']}" for s in shown)
    if matched > len(shown):
        lines.append(f"（仅显示前 {len(shown)} 项，可用 filter 缩小范围或调大 limit）")
    result = {
        "ok": res["ok"],
        "output": "\n".join(lines),
        "services": shown,
        "total": total,
        "matched": matched,
    }
    if keyword and matched == 0:
        result["hint"] = "已检索完整服务列表，确实没有匹配项；可换关键词或查看全部服务。"
    return result

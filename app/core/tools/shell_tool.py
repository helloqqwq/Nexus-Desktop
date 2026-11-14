"""受控命令执行：程序白名单 + 参数校验，禁止 shell 拼接。"""
from __future__ import annotations

import os
import re
import subprocess
import threading
import time

from ..config import Config
from ..diag import CREATE_NO_WINDOW, _decode
from ..safety import Safety
from .registry import Registry, Tool

MAX_OUTPUT = 6000


def _run_process(cmd: list[str], timeout: int, cancel_event=None,
                 cwd: str | None = None, env: dict | None = None) -> tuple[int, str, bool, bool]:
    """运行命令并支持取消；返回 (退出码, 输出, 是否取消, 是否超时)。"""
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        cwd=cwd, env=env, creationflags=CREATE_NO_WINDOW,
    )
    chunks: list[bytes] = []

    def reader() -> None:
        try:
            chunks.append(proc.stdout.read() if proc.stdout else b"")
        except OSError:
            pass

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    deadline = time.time() + timeout
    cancelled = timed_out = False
    while proc.poll() is None:
        if cancel_event is not None and cancel_event.is_set():
            proc.terminate()
            cancelled = True
            break
        if time.time() > deadline:
            proc.kill()
            timed_out = True
            break
        time.sleep(0.1)
    try:
        code = proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        code = -1
    thread.join(timeout=2)
    return code, _decode(b"".join(chunks)).strip(), cancelled, timed_out

# program -> (允许的参数白名单校验函数, 说明)
def _basic(token_pat: str, max_args: int = 6):
    rx = re.compile(token_pat)

    def check(args: list[str]) -> str | None:
        if len(args) > max_args:
            return "参数过多"
        for a in args:
            if not rx.fullmatch(a):
                return f"不允许的参数：{a}"
        return None

    return check


ALLOWED: dict[str, tuple] = {
    "ping": (_basic(r"[-A-Za-z0-9_.:]{1,64}", 6), "测试网络连通性"),
    "nslookup": (_basic(r"[-A-Za-z0-9_.:]{1,120}", 4), "查询域名解析"),
    "tracert": (_basic(r"[-A-Za-z0-9_.:]{1,120}", 5), "路由追踪"),
    "ipconfig": (_basic(r"/(all|displaydns)", 2), "查看网络配置"),
    "netstat": (_basic(r"-?[a-z0-9]{1,4}", 8), "查看网络连接"),
    "route": (_basic(r"(print|-4|-6)", 4), "查看路由表"),
    "arp": (_basic(r"(-a|-g|\*|[0-9.]+)", 4), "查看 ARP 缓存"),
    "getmac": (_basic(r"(/v|/fo|table|list|/nh)", 6), "查看网卡地址"),
    "tasklist": (_basic(r"([/A-Za-z0-9_.=-]{1,32})", 8), "查看进程列表"),
    "systeminfo": (_basic(r"([/A-Za-z0-9_.=-]{1,32})", 4), "查看系统信息"),
    "sc": (_basic(r"[A-Za-z0-9_=./-]{1,64}", 6), "查看服务状态（只读）"),
    "netsh": (_basic(r"[A-Za-z0-9_./=-]{1,64}", 8), "查看无线/网络接口状态（只读）"),
    "whoami": (_basic(r"[-/A-Za-z0-9_.\\]{1,80}", 3), "查看当前用户"),
    "hostname": (_basic(r"[-A-Za-z0-9_]{1,64}", 1), "查看电脑名称"),
}

FORBIDDEN_WORDS = (
    "/flushdns", "reset", "renew", "release", "stop", "start", "delete", "remove",
    "kill", "taskkill", "shutdown", "format", "reg ", "sc config", "sc create",
    "sc delete", "netsh advfirewall", "netsh int", "netsh interface ip set",
)

NETSH_ALLOWED_PREFIX = (
    ("wlan", "show"),
    ("interface", "show"),
    ("int", "show"),
    ("winsock", "show"),
    ("winhttp", "show"),
)


def register(reg: Registry, config: Config, safety: Safety) -> None:
    def shell_run(args: dict) -> dict:
        program = str(args.get("program") or "").strip().lower()
        prog_args = args.get("args") or []
        if isinstance(prog_args, str):
            prog_args = prog_args.split()
        prog_args = [str(a) for a in prog_args]
        timeout = max(3, min(int(args.get("timeout") or 20), 60))
        note = ""
        if prog_args and prog_args[0].strip().lower() == program:
            # 有些调用会把程序名同时写进 args；去掉重复项，避免执行成 "whoami whoami"。
            prog_args = prog_args[1:]
            note = "args 里重复的程序名已自动去掉"

        if program not in ALLOWED:
            return {
                "ok": False,
                "error": f"程序不在白名单：{program}。可用：{', '.join(sorted(ALLOWED))}",
            }
        check, desc = ALLOWED[program]
        low_args = " ".join(prog_args).lower()
        for word in FORBIDDEN_WORDS:
            if word in low_args:
                return {"ok": False, "error": f"参数包含不允许的操作：{word}（修改系统请在诊断建议中确认后执行）"}
        err = check(prog_args)
        if err:
            return {"ok": False, "error": err}
        if program == "netsh":
            head = tuple(a.lower() for a in prog_args[:2])
            if head not in NETSH_ALLOWED_PREFIX:
                return {"ok": False, "error": "netsh 仅允许查看类子命令"}

        cmd = [program] + prog_args
        safety.audit("shell_run", {"cmd": cmd})
        try:
            code, text, cancelled, timed_out = _run_process(
                cmd, timeout, getattr(reg, "cancel_event", None)
            )
        except OSError as e:
            return {"ok": False, "error": f"命令执行失败：{e}"}
        if cancelled:
            return {"ok": False, "error": "命令已停止", "cancelled": True, "cmd": " ".join(cmd)}
        if timed_out:
            return {"ok": False, "error": f"命令超时（{timeout}s）：{' '.join(cmd)}",
                    "cmd": " ".join(cmd)}
        result = {
            "ok": code == 0,
            "code": code,
            "cmd": " ".join(cmd),
            "output": text[:MAX_OUTPUT],
            "truncated": len(text) > MAX_OUTPUT,
        }
        if note:
            result["note"] = note
        if result["truncated"]:
            result["warning"] = (
                f"输出超过 {MAX_OUTPUT} 字符已截断，结果不完整；"
                "请缩小查询范围或改用对应的专用工具。"
            )
        return result

    def shell_exec(args: dict) -> dict:
        if str(config.get("mode") or "supervised").lower() == "safe":
            return {"ok": False, "error": "安全模式下不能执行命令"}
        command = str(args.get("command") or "").strip()
        if not command:
            return {"ok": False, "error": "缺少 command"}
        if len(command) > 4000:
            return {"ok": False, "error": "命令过长"}
        timeout = max(3, min(int(args.get("timeout") or 60), 180))
        env = os.environ.copy()
        env.pop("NEXUS_API_KEY", None)
        safety.audit("shell_exec", {"command": command[:1000], "timeout": timeout})
        try:
            code, text, cancelled, timed_out = _run_process(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                timeout, getattr(reg, "cancel_event", None),
                cwd=str(config.output_dir), env=env,
            )
        except OSError as e:
            return {"ok": False, "error": f"命令启动失败：{e}"}
        if cancelled:
            return {"ok": False, "cancelled": True, "error": "命令已停止"}
        if timed_out:
            return {"ok": False, "error": f"命令超时（{timeout}s）"}
        result = {
            "ok": code == 0,
            "code": code,
            "output": text[:MAX_OUTPUT],
            "truncated": len(text) > MAX_OUTPUT,
            "output_text": text[:MAX_OUTPUT],
        }
        if result["truncated"]:
            result["warning"] = (
                f"输出超过 {MAX_OUTPUT} 字符已截断，结果不完整；"
                "请缩小查询范围或减少输出内容。"
            )
        return result

    reg.add(Tool(
        name="shell_run",
        description=(
            "执行只读的系统诊断命令。仅允许 ping/nslookup/tracert/ipconfig/netstat/route/arp/"
            "getmac/tasklist/systeminfo/sc query/netsh show/whoami/hostname，需要用户确认。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "program": {"type": "string", "description": "程序名，如 ping"},
                "args": {"type": "array", "items": {"type": "string"}, "description": "参数列表"},
                "timeout": {"type": "integer", "description": "超时秒数，默认 20"},
            },
            "required": ["program", "args"],
        },
        handler=shell_run,
        needs_confirm=True,
        tag="shell",
    ))
    reg.add(Tool(
        name="shell_exec",
        description=(
            "执行任意 PowerShell 命令（监管模式下需要用户确认）。"
            "会修改系统或文件，务必让用户看清完整命令。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "完整 PowerShell 命令"},
                "timeout": {"type": "integer", "description": "超时秒数 3-180，默认 60"},
            },
            "required": ["command"],
        },
        handler=shell_exec,
        needs_confirm=True,
        tag="shell",
    ))

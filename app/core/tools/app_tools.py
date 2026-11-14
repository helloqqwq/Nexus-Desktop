"""应用级工具：打开文件/网页、截图、待办清单。"""
from __future__ import annotations

import base64
import csv
import io
import os
import subprocess
import time
from pathlib import Path

from ..config import Config
from ..safety import Safety
from .registry import Registry, Tool

OPEN_EXT = {
    ".txt", ".md", ".html", ".htm", ".pdf", ".csv", ".png", ".jpg", ".jpeg",
    ".gif", ".webp", ".docx", ".xlsx", ".pptx", ".mp4", ".mp3",
}
SCREENSHOT_MAX_B64 = 3 * 1024 * 1024

# 允许直接启动的常用程序；不开放任意可执行文件，避免变成命令执行入口
APPS = {
    "notepad": ("记事本", ["notepad.exe"]),
    "calc": ("计算器", ["calc.exe"]),
    "paint": ("画图", ["mspaint.exe"]),
    "explorer": ("文件资源管理器", ["explorer.exe"]),
    "control": ("控制面板", ["control.exe"]),
    "settings": ("系统设置", ["ms-settings:"]),
    "taskmgr": ("任务管理器", ["taskmgr.exe"]),
}


def _window_for(pid: int, label: str, timeout: float = 6.0) -> dict:
    """启动后定位真实窗口：应用别名/UWP 会让 Popen 的 pid 立刻失效。"""
    try:
        import uiautomation as auto
    except ImportError:
        return {}
    try:
        auto.SetGlobalSearchTimeout(1.0)
        root = auto.GetRootControl()
    except Exception:
        return {}
    started = time.time()
    label_hit: dict = {}
    while time.time() - started < timeout:
        try:
            children = list(root.GetChildren())
        except Exception:
            children = []
        for ctrl in children:
            try:
                hwnd = int(ctrl.NativeWindowHandle or 0)
                wpid = int(ctrl.ProcessId or 0)
                title = (ctrl.Name or "").strip()
            except Exception:
                continue
            if hwnd <= 0:
                continue
            if pid and wpid == pid:
                return {"pid": wpid, "hwnd": hwnd, "title": title}
            if label and label in title and not label_hit:
                label_hit = {"pid": wpid, "hwnd": hwnd, "title": title}
        if label_hit and time.time() - started > 1.5:
            return label_hit
        time.sleep(0.25)
    return label_hit


APP_HINTS = {
    "notepad": ("notepad",),
    "calc": ("calculator",),
    "paint": ("mspaint", "paint"),
    "explorer": ("explorer",),
    "control": ("control",),
    "settings": ("systemsettings", "settings"),
    "taskmgr": ("taskmgr",),
}


def _pids() -> dict[int, str]:
    """当前进程表（pid → 进程名），用于识别启动后新增的应用进程。"""
    try:
        out = subprocess.run(
            ["tasklist", "/fo", "csv", "/nh"],
            capture_output=True, timeout=20, creationflags=0x08000000,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return {}
    text = out.decode("mbcs", "replace")
    result: dict[int, str] = {}
    for row in csv.reader(io.StringIO(text)):
        if len(row) >= 2:
            try:
                result[int(row[1])] = row[0]
            except ValueError:
                continue
    return result


def _app_process(before: dict[int, str], app: str) -> tuple[int, str]:
    """在启动前后的进程差集里找应用本体；认不出就返回空，避免误报。"""
    after = _pids()
    hints = APP_HINTS.get(app, ())
    for pid, name in after.items():
        if pid in before or pid == os.getpid():
            continue
        low = name.lower()
        if any(h in low for h in hints):
            return pid, name
    return 0, ""


def register(reg: Registry, config: Config, safety: Safety) -> None:
    def app_open(args: dict) -> dict:
        target = str(args.get("path") or "").strip()
        if not target:
            return {"ok": False, "error": "缺少 path"}
        low = target.lower()
        if low.startswith(("http://", "https://")):
            os.startfile(target)  # noqa: S606 - 用户确认后打开浏览器
            safety.audit("app_open", {"url": target})
            return {"ok": True, "opened": target, "type": "url"}
        path = safety.resolve(target, for_write=False)
        if not path.exists():
            return {"ok": False, "error": f"文件不存在：{path}"}
        if path.suffix.lower() not in OPEN_EXT:
            return {"ok": False, "error": f"出于安全考虑，不打开该类型文件：{path.suffix}"}
        os.startfile(str(path))  # noqa: S606
        safety.audit("app_open", {"path": str(path)})
        return {"ok": True, "opened": str(path), "type": "file"}

    def app_launch(args: dict) -> dict:
        name = str(args.get("app") or "").strip().lower()
        item = APPS.get(name)
        if not item:
            return {
                "ok": False,
                "error": f"不支持的程序：{name}。可用：{', '.join(sorted(APPS))}",
            }
        label, cmd = item
        before = _pids()
        launcher_pid = 0
        try:
            if name == "settings":
                os.startfile(cmd[0])  # noqa: S606 - 打开系统设置页
            else:
                proc = subprocess.Popen(cmd)
                launcher_pid = proc.pid
        except OSError as e:
            return {"ok": False, "error": f"启动失败：{e}"}
        hit = _window_for(launcher_pid, label)
        hwnd = int(hit.get("hwnd") or 0)
        title = str(hit.get("title") or "")
        window_pid = int(hit.get("pid") or 0)
        app_pid, app_name = _app_process(before, name)
        if app_pid:
            pid, kind, verified = app_pid, "app", True
        elif window_pid:
            pid, kind, verified = window_pid, "window_host", False
        else:
            pid, kind, verified = launcher_pid, "launcher", False
        result = {
            "ok": True,
            "app": name,
            "label": label,
            "pid": pid,
            "pid_kind": kind,
            "pid_verified": verified,
            "app_pid": app_pid or None,
            "app_process": app_name or None,
            "window_pid": window_pid or None,
            "hwnd": hwnd,
            "title": title,
            "output": f"已打开{label}（pid {pid}，hwnd {hwnd}）" if hwnd else f"已打开{label}",
        }
        if not verified:
            result["hint"] = (
                "pid 不是应用本体：它是承载窗口的进程" if window_pid else
                "pid 可能只是启动器进程"
            ) + "；需要结束程序时请用 app_process 或按窗口标题定位。"
        safety.audit("app_launch", {"app": name, "cmd": cmd, "pid": pid, "kind": kind,
                                    "hwnd": hwnd, "verified": verified})
        return result

    def screenshot_capture(args: dict) -> dict:
        try:
            from PIL import ImageGrab
        except ImportError:
            return {"ok": False, "error": "缺少截图组件（Pillow）"}
        try:
            img = ImageGrab.grab(all_screens=True)
        except OSError as e:
            return {"ok": False, "error": f"截图失败：{e}"}
        folder = config.output_dir / "screenshots"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"shot_{time.strftime('%Y%m%d_%H%M%S')}.png"
        img.save(path, "PNG")
        safety.audit("screenshot", {"path": str(path), "size": img.size})
        result = {"ok": True, "path": str(path), "width": img.size[0], "height": img.size[1]}
        if args.get("inline"):
            buf = io.BytesIO()
            img.save(buf, "PNG")
            data = buf.getvalue()
            if len(data) <= SCREENSHOT_MAX_B64:
                result["image_base64"] = base64.b64encode(data).decode("ascii")
        return result

    def todo_write(args: dict) -> dict:
        raw = args.get("items") or []
        items = []
        for it in raw:
            if isinstance(it, str):
                items.append({"text": it, "status": "pending"})
            elif isinstance(it, dict) and it.get("text"):
                status = it.get("status") if it.get("status") in ("pending", "doing", "done") else "pending"
                items.append({"text": str(it["text"])[:300], "status": status})
        if not items:
            return {"ok": False, "error": "items 为空"}
        return {"ok": True, "items": items[:30]}

    reg.add(Tool(
        name="app_open",
        description="用系统默认程序打开文件或网页（需要用户确认）。",
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string", "description": "本地文件路径或 http(s) 网址"}},
            "required": ["path"],
        },
        handler=app_open,
        needs_confirm=True,
        tag="app",
    ))
    reg.add(Tool(
        name="app_launch",
        description=(
            "打开常用程序（需要用户确认）：notepad 记事本、calc 计算器、paint 画图、"
            "explorer 文件资源管理器、control 控制面板、settings 系统设置、taskmgr 任务管理器。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "app": {
                    "type": "string",
                    "enum": sorted(APPS),
                    "description": "要打开的程序",
                }
            },
            "required": ["app"],
        },
        handler=app_launch,
        needs_confirm=True,
        tag="app",
    ))
    reg.add(Tool(
        name="screenshot_capture",
        description="截取当前屏幕并保存为图片，用于分析屏幕上的报错或界面。",
        parameters={
            "type": "object",
            "properties": {"inline": {"type": "boolean", "description": "是否把图片数据一并返回"}},
        },
        handler=screenshot_capture,
        tag="app",
    ))
    reg.add(Tool(
        name="todo_write",
        description="维护本次任务的待办清单，让用户看到进度。",
        parameters={
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "status": {"type": "string", "enum": ["pending", "doing", "done"]},
                        },
                        "required": ["text"],
                    },
                }
            },
            "required": ["items"],
        },
        handler=todo_write,
        tag="app",
    ))

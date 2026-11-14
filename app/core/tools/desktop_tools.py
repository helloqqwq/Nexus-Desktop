"""电脑操作工具：基于 Windows UI Automation（UI 树）。

设计要点：
- 只暴露「窗口句柄 + 元素路径」这种稳定引用，每次操作重新解析，避免控件对象失效。
- 读操作（ui_windows/ui_tree/ui_find）不需要确认；写操作（ui_act）必须由用户确认。
- 拒绝操作 UAC、安全中心、凭据管理器等安全桌面，以及 Nexus 自己的窗口。
"""
from __future__ import annotations

import ctypes
import os
import re
import threading
import time
from ctypes import wintypes

from ..config import Config
from ..safety import Safety
from .registry import Registry, Tool

MAX_WINDOWS = 40
MAX_TREE_NODES = 200
MAX_FIND_NODES = 3000
MAX_TEXT = 2000
MAX_OUTPUT = 6000
READ_DEPTH = 6

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SW_RESTORE = 9

# 这些进程/窗口属于系统安全边界，绝不自动化操作
CRITICAL_PROCESSES = {
    "consent.exe", "logonui.exe", "winlogon.exe", "csrss.exe", "lsass.exe",
    "services.exe", "securityhealthservice.exe", "smartscreen.exe",
}
CRITICAL_TITLES = (
    "用户账户控制", "user account control", "windows 安全中心", "windows security",
    "windows defender", "凭据管理器", "credential manager", "安全桌面",
)
BLOCKED_CLASSES = {"Credential Dialog Xaml Host"}

# 允许发送的按键，覆盖日常操作，不提供 Win / Alt+F4 等危险组合
KEY_MAP = {
    "enter": "{Enter}", "tab": "{Tab}", "esc": "{Esc}", "space": " ",
    "up": "{Up}", "down": "{Down}", "left": "{Left}", "right": "{Right}",
    "home": "{Home}", "end": "{End}", "pgup": "{PageUp}", "pgdn": "{PageDown}",
    "backspace": "{Back}", "delete": "{Delete}",
    "ctrl+a": "{Ctrl}a", "ctrl+c": "{Ctrl}c", "ctrl+v": "{Ctrl}v",
    "ctrl+s": "{Ctrl}s", "ctrl+z": "{Ctrl}z", "ctrl+y": "{Ctrl}y",
}

_lock = threading.RLock()
_control_release = None


def set_control_release(fn) -> None:
    """由桌面外壳注入：把屏幕控制权交还给用户。"""
    global _control_release
    _control_release = fn


# ---------------- 基础辅助 ----------------
def _uia():
    """在调用线程初始化 COM 后返回 uiautomation 模块。"""
    try:
        import comtypes

        comtypes.CoInitialize()
    except Exception:
        pass  # 已初始化或公寓模型不同，继续尝试
    import uiautomation as auto

    auto.SetGlobalSearchTimeout(1.2)
    return auto


def _proc_name(pid: int) -> str:
    if not pid:
        return ""
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
    finally:
        kernel32.CloseHandle(handle)
    return ""


def _rect(ctrl) -> list[int]:
    try:
        r = ctrl.BoundingRectangle
        return [int(r.left), int(r.top), int(r.right) - int(r.left), int(r.bottom) - int(r.top)]
    except Exception:
        return [0, 0, 0, 0]


class _WINDOWPLACEMENT(ctypes.Structure):
    _fields_ = [
        ("length", ctypes.c_uint),
        ("flags", ctypes.c_uint),
        ("showCmd", ctypes.c_uint),
        ("ptMinPosition", wintypes.POINT),
        ("ptMaxPosition", wintypes.POINT),
        ("rcNormalPosition", wintypes.RECT),
    ]


def _placement_rect(hwnd: int) -> list[int]:
    """最小化窗口的 UIA 矩形是 0 或屏幕外，用 GetWindowPlacement 取还原后的位置。"""
    wp = _WINDOWPLACEMENT()
    wp.length = ctypes.sizeof(_WINDOWPLACEMENT)
    try:
        if ctypes.windll.user32.GetWindowPlacement(hwnd, ctypes.byref(wp)):
            r = wp.rcNormalPosition
            return [int(r.left), int(r.top), int(r.right - r.left), int(r.bottom - r.top)]
    except OSError:
        pass
    return [0, 0, 0, 0]


def _type_name(ctrl) -> str:
    raw = getattr(ctrl, "ControlTypeName", "") or ""
    return raw[:-7] if raw.endswith("Control") else raw


def _children(ctrl) -> list:
    try:
        return list(ctrl.GetChildren())
    except Exception:
        return []


def _foreground() -> int:
    try:
        return int(ctypes.windll.user32.GetForegroundWindow() or 0)
    except OSError:
        return 0


def _critical_reason(title: str, proc: str, cls: str) -> str:
    low_title = (title or "").lower()
    low_proc = (proc or "").lower()
    if low_proc in CRITICAL_PROCESSES:
        return f"系统安全进程 {proc}"
    if any(word in low_title for word in CRITICAL_TITLES):
        return f"系统安全窗口「{title}」"
    if cls in BLOCKED_CLASSES:
        return "系统凭据对话框"
    return ""


def _check_root(root) -> None:
    """校验目标窗口是否允许操作。"""
    try:
        title = (root.Name or "").strip()
        cls = root.ClassName or ""
        pid = int(root.ProcessId or 0)
    except Exception as e:
        raise PermissionError(f"无法识别目标窗口：{e}") from e
    if pid and pid == os.getpid():
        raise PermissionError("Nexus 不会操作自己的窗口")
    reason = _critical_reason(title, _proc_name(pid), cls)
    if reason:
        raise PermissionError(f"出于安全考虑，不操作该窗口：{reason}")


def _window(hwnd, auto=None):
    try:
        hwnd = int(hwnd)
    except (TypeError, ValueError):
        hwnd = 0
    if hwnd <= 0:
        raise ValueError("请提供窗口句柄 hwnd（可先用 ui_windows 查看）")
    auto = auto or _uia()
    try:
        root = auto.ControlFromHandle(hwnd)
    except Exception as e:
        raise LookupError(f"找不到窗口 {hwnd}：{e}") from e
    if root is None:
        raise LookupError(f"找不到窗口 {hwnd}")
    return root


def _resolve(root, path: str):
    cur = root
    parts = [p for p in str(path or "").split(".") if p != ""]
    if not parts:
        raise ValueError("缺少 path（可先用 ui_tree/ui_find 查看元素路径）")
    for seg in parts:
        if not seg.isdigit():
            raise ValueError(f"元素路径格式不正确：{path}")
        kids = _children(cur)
        idx = int(seg)
        if idx >= len(kids):
            raise LookupError(f"元素路径已失效（{path}），请重新用 ui_tree 查看")
        cur = kids[idx]
    return cur


def _node(ctrl, path: str) -> dict:
    name = (ctrl.Name or "").strip().replace("\n", " ").replace("\r", " ")
    try:
        enabled = bool(ctrl.IsEnabled)
    except Exception:
        enabled = True
    try:
        offscreen = bool(ctrl.IsOffscreen)
    except Exception:
        offscreen = False
    return {
        "p": path,
        "t": _type_name(ctrl),
        "n": name[:60],
        "i": (ctrl.AutomationId or "").strip()[:40],
        "r": _rect(ctrl),
        "e": enabled,
        "o": offscreen,
    }


def _line(item: dict) -> str:
    flags = []
    if not item.get("e", True):
        flags.append("禁用")
    if item.get("o"):
        flags.append("不可见")
    tail = f" [{'/'.join(flags)}]" if flags else ""
    ident = f" id={item['i']}" if item.get("i") else ""
    return f"{item['p']} ({item['t']}) \"{item['n']}\"{ident}{tail}"


def _activate(hwnd: int) -> None:
    try:
        user32 = ctypes.windll.user32
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
    except OSError:
        pass
    time.sleep(0.12)


def _match(item: dict, name: str, ctype: str, aid: str, cls: str, exact: bool) -> bool:
    if name:
        target = item["n"].lower()
        needle = name.lower()
        if (target != needle) if exact else (needle not in target):
            return False
    if ctype:
        want = ctype.lower()
        if want.endswith("control"):
            want = want[:-7]
        if item["t"].lower() != want:
            return False
    if aid and aid.lower() not in item.get("i", "").lower():
        return False
    if cls and cls.lower() not in item.get("_cls", "").lower():
        return False
    return True


# ---------------- 读：窗口 / UI 树 / 查找 ----------------
def _list_windows(auto) -> list[dict]:
    root = auto.GetRootControl()
    active = _foreground()
    items = []
    for ctrl in _children(root):
        try:
            hwnd = int(ctrl.NativeWindowHandle or 0)
            if hwnd <= 0:
                continue
            title = (ctrl.Name or "").strip()
            cls = ctrl.ClassName or ""
            if not title and cls in ("Chrome_WidgetWin_1", "MicrosoftWindowsTooltip"):
                continue
            minimized = bool(ctypes.windll.user32.IsIconic(hwnd))
            if minimized:
                x, y, w, h = _placement_rect(hwnd)
            else:
                x, y, w, h = _rect(ctrl)
                if w <= 0 or h <= 0:
                    continue
            if ctrl.IsOffscreen and not title and not minimized:
                continue
            pid = int(ctrl.ProcessId or 0)
            proc = _proc_name(pid)
            reason = _critical_reason(title, proc, cls)
            is_self = pid == os.getpid()
            items.append({
                "hwnd": hwnd,
                "title": title or cls,
                "class": cls,
                "pid": pid,
                "proc": proc,
                "x": x, "y": y, "w": w, "h": h,
                "minimized": minimized,
                "active": hwnd == active,
                "self": is_self,
                "blocked": bool(reason or is_self),
                "reason": reason or ("Nexus 自身窗口" if is_self else ""),
            })
        except Exception:
            continue
    items.sort(key=lambda i: (not i["active"], i["self"], not i["title"], -i["w"] * i["h"]))
    return items[:MAX_WINDOWS]


def _tree(root, depth: int, max_nodes: int, start_path: str = "") -> dict:
    start = root if not start_path else _resolve(root, start_path)
    nodes, lines = [], []
    queue = [(start, start_path, 0)]
    while queue and len(nodes) < max_nodes:
        ctrl, path, level = queue.pop(0)
        if path:
            item = _node(ctrl, path)
            nodes.append(item)
            lines.append(_line(item))
        if level >= depth:
            continue
        for idx, kid in enumerate(_children(ctrl)):
            child_path = f"{path}.{idx}" if path else str(idx)
            queue.append((kid, child_path, level + 1))
    text = "\n".join(lines)
    return {
        "ok": True,
        "nodes": nodes,
        "count": len(nodes),
        "truncated": bool(queue),
        "output": text[:MAX_OUTPUT] or "（这个窗口没有可读取的子元素）",
    }


def _find(root, name: str, ctype: str, aid: str, cls: str, exact: bool,
          max_results: int, max_depth: int) -> dict:
    results = []
    queue = [(root, "", 0)]
    scanned = 0
    while queue and scanned < MAX_FIND_NODES and len(results) < max_results:
        ctrl, path, level = queue.pop(0)
        scanned += 1
        if path:
            try:
                item = _node(ctrl, path)
                item["_cls"] = ctrl.ClassName or ""
                if _match(item, name, ctype, aid, cls, exact):
                    item.pop("_cls", None)
                    results.append(item)
            except Exception:
                pass
        if level >= max_depth:
            continue
        for idx, kid in enumerate(_children(ctrl)):
            queue.append((kid, f"{path}.{idx}" if path else str(idx), level + 1))
    text = "\n".join(_line(i) for i in results)
    return {
        "ok": True,
        "items": results,
        "scanned": scanned,
        "truncated": bool(queue) and len(results) < max_results,
        "output": text[:MAX_OUTPUT] or "没有找到匹配的元素，可放宽条件或改用 ui_tree 查看结构",
    }


# ---------------- 对外：给确认弹窗用的描述 ----------------
def describe(args: dict) -> dict:
    """尽量无副作用地描述一次 ui_act 的目标，供确认弹窗展示。"""
    try:
        with _lock:
            auto = _uia()
            root = _window(args.get("hwnd"), auto)
            _check_root(root)
            path = str(args.get("path") or "")
            ctrl = _resolve(root, path) if path else root
            return {
                "window": (root.Name or "").strip()[:60],
                "process": _proc_name(int(root.ProcessId or 0)),
                "control": (ctrl.Name or "").strip()[:80],
                "type": _type_name(ctrl),
                "action": str(args.get("action") or "click"),
                "text": str(args.get("text") or args.get("keys") or "")[:120],
            }
    except Exception as e:
        return {"error": str(e)}


def _force_foreground(hwnd: int) -> None:
    """绕过前台锁，把窗口真正切到前台。"""
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    try:
        foreground = int(user32.GetForegroundWindow() or 0)
        if foreground == hwnd:
            return
        fg_tid = int(user32.GetWindowThreadProcessId(foreground, None) or 0)
        cur_tid = int(kernel32.GetCurrentThreadId())
        attached = False
        if fg_tid and fg_tid != cur_tid:
            attached = bool(user32.AttachThreadInput(cur_tid, fg_tid, True))
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.SetFocus(hwnd)
        if attached:
            user32.AttachThreadInput(cur_tid, fg_tid, False)
    except OSError:
        pass


def _window_bounds(hwnd: int) -> tuple[int, int, int, int]:
    rect = wintypes.RECT()
    try:
        ctypes.windll.dwmapi.DwmGetWindowAttribute(
            hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect)
        )
        if rect.right > rect.left and rect.bottom > rect.top:
            return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
    except Exception:
        pass
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top


class _BmiHeader(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class _Bmi(ctypes.Structure):
    _fields_ = [("bmiHeader", _BmiHeader), ("bmiColors", wintypes.DWORD * 3)]


def _print_window(hwnd: int, width: int, height: int):
    """优先用 PrintWindow 截窗口内容，窗口被遮挡或不在当前桌面时也能拿到画面。"""
    try:
        from PIL import Image
    except ImportError:
        return None
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    hdc = 0
    mem = 0
    bmp = 0
    try:
        user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
        user32.PrintWindow.restype = wintypes.BOOL
        hdc = user32.GetWindowDC(hwnd)
        mem = gdi32.CreateCompatibleDC(hdc)
        bmi = _Bmi()
        bmi.bmiHeader.biSize = ctypes.sizeof(_BmiHeader)
        bmi.bmiHeader.biWidth = width
        bmi.bmiHeader.biHeight = -height
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0
        bits = ctypes.c_void_p()
        bmp = gdi32.CreateDIBSection(
            hdc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0
        )
        if not bmp or not bits:
            return None
        gdi32.SelectObject(mem, bmp)
        if not user32.PrintWindow(hwnd, mem, 2):
            return None
        raw = ctypes.string_at(bits, width * height * 4)
        return Image.frombuffer("RGBA", (width, height), raw, "raw", "BGRA", 0, 1).convert("RGB")
    except Exception:
        return None
    finally:
        try:
            if bmp:
                gdi32.DeleteObject(bmp)
            if mem:
                gdi32.DeleteDC(mem)
            if hdc:
                user32.ReleaseDC(hwnd, hdc)
        except Exception:
            pass


def app_focus_capture_tool(args: dict, config: Config, safety: Safety) -> dict:
    hwnd = int(args.get("hwnd") or 0)
    title = str(args.get("title") or "").strip()
    action = str(args.get("action") or "restore").lower()
    capture = bool(args.get("capture", True))
    auto = _uia()
    match: dict = {}
    if not hwnd:
        if not title:
            return {"ok": False, "error": "请提供 hwnd 或 title"}
        items = _list_windows(auto)
        needle = title.lower()
        found = next((it for it in items if needle in it["title"].lower()), None)
        if not found:
            found = next((it for it in items if needle in (it["proc"] or "").lower()), None)
        if not found:
            return {"ok": False, "error": f"没有找到窗口「{title}」"}
        hwnd = int(found["hwnd"])
        match = found
    else:
        try:
            ctrl = auto.ControlFromHandle(hwnd)
        except Exception:
            ctrl = None
        if not ctrl:
            return {"ok": False, "error": f"窗口不存在：{hwnd}"}
        title = (ctrl.Name or "").strip() or str(hwnd)
        pid = int(ctrl.ProcessId or 0)
        match = {
            "title": title, "class": ctrl.ClassName or "", "pid": pid,
            "proc": _proc_name(pid),
        }
    reason = _critical_reason(match.get("title", ""), match.get("proc", ""),
                              match.get("class", ""))
    if reason:
        return {"ok": False, "error": f"出于安全考虑不能操作：{reason}"}
    if int(match.get("pid") or 0) == os.getpid():
        return {"ok": False, "error": "不能操作 Nexus 自己的窗口"}

    user32 = ctypes.windll.user32
    try:
        if action == "maximize":
            user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
        elif action != "focus":
            user32.ShowWindow(hwnd, SW_RESTORE)
        _force_foreground(hwnd)
    except OSError as e:
        return {"ok": False, "error": f"切换窗口失败：{e}"}
    time.sleep(0.45)
    if not capture:
        return {"ok": True, "hwnd": hwnd, "title": match.get("title", ""), "captured": False,
                "output": f"已切换到「{match.get('title', '')}」"}

    x, y, w, h = _window_bounds(hwnd)
    if w <= 2 or h <= 2:
        return {"ok": False, "error": "窗口尺寸无效，可能仍在最小化"}
    img = _print_window(hwnd, w, h)
    method = "print"
    if img is None or all(lo == hi == 0 for lo, hi in img.getextrema()):
        try:
            from PIL import ImageGrab
            img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
            method = "screen"
        except Exception as e:
            return {"ok": False, "error": f"截图失败：{e}"}

    safe = re.sub(r'[\\/:*?"<>|]+', "_", str(match.get("title") or "窗口"))[:40]
    name = f"窗口截图_{safe}_{time.strftime('%H%M%S')}.png"
    path = config.output_dir / name
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        img.save(path, "PNG")
    except OSError as e:
        return {"ok": False, "error": f"保存截图失败：{e}"}
    safety.audit("app_focus_capture", {
        "hwnd": hwnd, "title": match.get("title"), "method": method,
    })
    return {
        "ok": True, "hwnd": hwnd, "title": match.get("title", ""),
        "path": str(path), "name": name,
        "width": img.width, "height": img.height, "method": method,
        "output": f"已聚焦「{match.get('title', '')}」并截图：{path}",
    }


def register(reg: Registry, config: Config, safety: Safety) -> None:
    def ui_windows_tool(args: dict) -> dict:
        with _lock:
            auto = _uia()
            items = _list_windows(auto)
        lines = []
        for idx, item in enumerate(items, 1):
            flags = []
            if item["active"]:
                flags.append("当前")
            if item["minimized"]:
                flags.append("最小化")
            if item["blocked"]:
                flags.append("禁止操作")
            tail = f" [{'/'.join(flags)}]" if flags else ""
            lines.append(
                f"{idx}. {item['title']} | {item['proc'] or '未知程序'} | "
                f"{item['w']}x{item['h']} | hwnd={item['hwnd']}{tail}"
            )
        safety.audit("ui_windows", {"count": len(items)})
        return {
            "ok": True,
            "items": items,
            "output": "\n".join(lines) or "没有找到可见窗口",
        }

    def ui_tree_tool(args: dict) -> dict:
        depth = max(1, min(int(args.get("depth") or 3), READ_DEPTH))
        max_nodes = max(20, min(int(args.get("max_nodes") or 80), MAX_TREE_NODES))
        with _lock:
            auto = _uia()
            root = _window(args.get("hwnd"), auto)
            _check_root(root)
            result = _tree(root, depth, max_nodes, str(args.get("path") or ""))
        result["window"] = (root.Name or "").strip()[:60]
        safety.audit("ui_tree", {"hwnd": args.get("hwnd"), "nodes": result.get("count"),
                                 "window": result["window"]})
        return result

    def ui_find_tool(args: dict) -> dict:
        name = str(args.get("name") or "").strip()
        ctype = str(args.get("control_type") or "").strip()
        aid = str(args.get("automation_id") or "").strip()
        cls = str(args.get("class_name") or "").strip()
        if not any((name, ctype, aid, cls)):
            return {"ok": False, "error": "请至少提供 name / control_type / automation_id / class_name 之一"}
        max_results = max(1, min(int(args.get("max_results") or 10), 30))
        max_depth = max(1, min(int(args.get("depth") or READ_DEPTH), READ_DEPTH))
        with _lock:
            auto = _uia()
            root = _window(args.get("hwnd"), auto)
            _check_root(root)
            result = _find(root, name, ctype, aid, cls, bool(args.get("exact")),
                           max_results, max_depth)
        result["window"] = (root.Name or "").strip()[:60]
        safety.audit("ui_find", {"hwnd": args.get("hwnd"), "name": name,
                                 "found": len(result.get("items") or [])})
        return result

    def ui_act_tool(args: dict) -> dict:
        try:
            return _ui_act(args)
        except LookupError as e:
            return {"ok": False, "error": f"元素路径已失效：{e}",
                    "hint": "重新调用 ui_tree 获取最新路径后再操作。"}
        except TypeError as e:
            return {"ok": False,
                    "error": "这个控件不支持该操作（可能不可见或没有可点击区域）",
                    "hint": f"可改用 invoke，或先用 ui_tree 确认控件状态。原始错误：{e}"}
        except Exception as e:
            return {"ok": False, "error": f"操作失败：{type(e).__name__}: {e}",
                    "hint": "控件可能已变化，重新读取 ui_tree 后再试。"}

    def _ui_act(args: dict) -> dict:
        action = str(args.get("action") or "click").lower()
        if action not in ("click", "double_click", "right_click", "focus",
                          "invoke", "set_text", "send_keys"):
            return {"ok": False, "error": f"不支持的动作：{action}"}
        with _lock:
            auto = _uia()
            root = _window(args.get("hwnd"), auto)
            _check_root(root)
            ctrl = _resolve(root, str(args.get("path") or ""))
            info = {
                "window": (root.Name or "").strip()[:60],
                "control": (ctrl.Name or "").strip()[:80],
                "type": _type_name(ctrl),
            }
            _activate(int(args.get("hwnd")))
            if action == "click":
                ctrl.Click()
            elif action == "double_click":
                ctrl.DoubleClick()
            elif action == "right_click":
                ctrl.RightClick()
            elif action == "focus":
                ctrl.SetFocus()
            elif action == "invoke":
                try:
                    ctrl.GetInvokePattern().Invoke()
                except Exception:
                    ctrl.Click()
            elif action == "set_text":
                text = str(args.get("text") or "")[:MAX_TEXT]
                if not text:
                    return {"ok": False, "error": "缺少 text"}
                done = False
                try:
                    ctrl.GetValuePattern().SetValue(text)
                    done = True
                except Exception:
                    pass
                if not done:
                    ctrl.SetFocus()
                    auto.SendKeys("{Ctrl}a")
                    auto.SendKeys(text.replace("{", "{{}").replace("}", "{}}"))
                info["text"] = text[:120]
            elif action == "send_keys":
                keys = str(args.get("keys") or "").strip().lower()
                if not keys:
                    return {"ok": False, "error": "缺少 keys"}
                tokens = [t for t in keys.replace(",", " ").split() if t]
                unknown = [t for t in tokens if t not in KEY_MAP]
                if unknown:
                    return {
                        "ok": False,
                        "error": f"不支持的按键：{', '.join(unknown)}。可用：{', '.join(KEY_MAP)}",
                    }
                ctrl.SetFocus()
                auto.SendKeys("".join(KEY_MAP[t] for t in tokens))
                info["keys"] = " ".join(tokens)
        safety.audit("ui_act", {"hwnd": args.get("hwnd"), "path": args.get("path"),
                                "action": action, **info})
        return {
            "ok": True,
            "action": action,
            "control": info,
            "output": f"已在「{info['window']}」对「{info['control'] or info['type']}」执行 {action}",
        }

    def release_control_tool(args: dict) -> dict:
        fn = _control_release
        if fn is None:
            return {"ok": False, "error": "当前没有正在进行的屏幕接管",
                    "hint": "只有在 AI 控制屏幕时才能交还控制权。"}
        try:
            fn()
        except Exception as e:
            return {"ok": False, "error": f"交还控制权失败：{e}"}
        return {"ok": True, "output": "已把电脑控制权交还给用户"}

    reg.add(Tool(
        name="release_control",
        description=(
            "把电脑控制权交还给用户：结束屏幕接管状态，隐藏边缘光晕并恢复用户的键鼠输入。"
            "一串界面操作做完、或用户需要自己接手时应主动调用。"
        ),
        parameters={"type": "object", "properties": {}},
        handler=release_control_tool,
        tag="ui",
    ))
    reg.add(Tool(
        name="ui_windows",
        description=(
            "电脑操作第一步：列出当前打开的窗口（标题、程序、窗口句柄 hwnd）。"
            "拿到 hwnd 后才能用 ui_tree / ui_find / ui_act 操作具体窗口。"
        ),
        parameters={"type": "object", "properties": {}},
        handler=ui_windows_tool,
        tag="desktop",
    ))
    reg.add(Tool(
        name="ui_tree",
        description=(
            "读取窗口的 UI 树（元素路径 path、类型、名称、位置）。用于了解软件界面结构。"
            "元素很多时优先用 ui_find。depth 默认 3，max_nodes 默认 80。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "hwnd": {"type": "integer", "description": "窗口句柄，来自 ui_windows"},
                "depth": {"type": "integer", "description": "展开层数 1-6，默认 3"},
                "max_nodes": {"type": "integer", "description": "最多返回元素数 20-200，默认 80"},
                "path": {"type": "string", "description": "可选：从某个元素开始展开，如 0.2"},
            },
            "required": ["hwnd"],
        },
        handler=ui_tree_tool,
        tag="desktop",
    ))
    reg.add(Tool(
        name="ui_find",
        description=(
            "在窗口的 UI 树里按名称/类型/自动化 ID 查找控件，返回元素路径 path。"
            "name 默认模糊匹配（包含即可），exact=true 时精确匹配；control_type 如 Button、Edit、MenuItem。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "hwnd": {"type": "integer", "description": "窗口句柄，来自 ui_windows"},
                "name": {"type": "string", "description": "控件名称/文字"},
                "control_type": {"type": "string", "description": "控件类型，如 Button、Edit"},
                "automation_id": {"type": "string", "description": "自动化 ID"},
                "class_name": {"type": "string", "description": "窗口类名片段"},
                "exact": {"type": "boolean", "description": "名称是否精确匹配"},
                "depth": {"type": "integer", "description": "搜索深度 1-6，默认 6"},
                "max_results": {"type": "integer", "description": "最多返回条数，默认 10"},
            },
            "required": ["hwnd"],
        },
        handler=ui_find_tool,
        tag="desktop",
    ))
    reg.add(Tool(
        name="ui_act",
        description=(
            "对 UI 元素执行操作（需要用户确认）：click 单击、double_click 双击、"
            "right_click 右键、focus 聚焦、invoke 触发默认动作、set_text 写入文字、"
            "send_keys 发送按键（enter/tab/esc/up/down/left/right/backspace/delete/"
            "ctrl+a/ctrl+c/ctrl+v/ctrl+s/ctrl+z/ctrl+y）。path 来自 ui_tree/ui_find。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "hwnd": {"type": "integer", "description": "窗口句柄"},
                "path": {"type": "string", "description": "元素路径，如 0.2.1"},
                "action": {
                    "type": "string",
                    "enum": ["click", "double_click", "right_click", "focus",
                             "invoke", "set_text", "send_keys"],
                },
                "text": {"type": "string", "description": "set_text 时要写入的文字"},
                "keys": {"type": "string", "description": "send_keys 时的按键，空格分隔"},
            },
            "required": ["hwnd", "path", "action"],
        },
        handler=ui_act_tool,
        needs_confirm=True,
        tag="desktop",
    ))
    reg.add(Tool(
        name="app_focus_capture",
        description=(
            "把指定软件窗口从最小化恢复、聚焦到前台并截图，适合需要查看某个应用当前画面的任务。"
            "title 为窗口标题或程序名关键字；也可以先用 ui_windows 拿到 hwnd。"
            "action=restore 恢复、maximize 最大化、focus 仅聚焦；capture=false 时只切换不截图。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "窗口标题或程序名关键字，如 记事本、chrome"},
                "hwnd": {"type": "integer", "description": "可选：窗口句柄，优先于 title"},
                "action": {
                    "type": "string",
                    "enum": ["restore", "maximize", "focus"],
                },
                "capture": {"type": "boolean", "description": "是否截图，默认 true"},
            },
        },
        handler=lambda args: app_focus_capture_tool(args, config, safety),
        tag="desktop",
    ))

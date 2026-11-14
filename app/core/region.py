"""屏幕区域框选：独立子进程运行，避免阻塞 WebView2 主线程。"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from .win32util import set_window_pos

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

MIN_SIZE = 8


def _dpi_aware() -> None:
    try:
        user32 = ctypes.windll.user32
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user32.SetProcessDpiAwarenessContext.restype = ctypes.c_bool
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass


def virtual_screen() -> dict:
    user32 = ctypes.windll.user32
    return {
        "left": int(user32.GetSystemMetrics(SM_XVIRTUALSCREEN)),
        "top": int(user32.GetSystemMetrics(SM_YVIRTUALSCREEN)),
        "width": int(user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)),
        "height": int(user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)),
    }


def normalize_region(region: dict | None, bounds: dict | None = None) -> dict | None:
    """把框选结果裁剪到虚拟屏幕范围内，并保证最小尺寸。"""
    if not region:
        return None
    b = bounds or virtual_screen()
    try:
        left = int(region.get("left"))
        top = int(region.get("top"))
        right = int(region.get("right"))
        bottom = int(region.get("bottom"))
    except (TypeError, ValueError):
        return None
    if right < left:
        left, right = right, left
    if bottom < top:
        top, bottom = bottom, top
    x2 = b["left"] + b["width"]
    y2 = b["top"] + b["height"]
    left = max(b["left"], min(left, x2))
    top = max(b["top"], min(top, y2))
    right = max(b["left"], min(right, x2))
    bottom = max(b["top"], min(bottom, y2))
    if right - left < MIN_SIZE or bottom - top < MIN_SIZE:
        return None
    return {
        "left": left,
        "top": top,
        "right": right,
        "bottom": bottom,
        "width": right - left,
        "height": bottom - top,
    }


def _place_window(root, x: int, y: int, width: int, height: int) -> int:
    """Tk 的 geometry 把负偏移解释为距右边/底边，多屏下需用 Win32 绝对定位。"""
    hwnd = 0
    try:
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
        set_window_pos(hwnd, -1, x, y, width, height, 0x0040)
    except OSError:
        try:
            root.geometry(f"{width}x{height}+0+0")
        except Exception:
            pass
    return hwnd


def _client_origin(hwnd: int) -> tuple[int, int]:
    pt = wintypes.POINT(0, 0)
    ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return int(pt.x), int(pt.y)


def _client_size(hwnd: int) -> tuple[int, int]:
    rect = wintypes.RECT()
    ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(rect))
    return max(1, int(rect.right)), max(1, int(rect.bottom))


def pick_region() -> dict | None:
    """全屏半透明遮罩上拖框，返回绝对屏幕坐标；取消返回 None。"""
    _dpi_aware()
    try:
        import tkinter as tk
    except ImportError:
        return None

    bounds = virtual_screen()
    vx, vy, vw, vh = bounds["left"], bounds["top"], bounds["width"], bounds["height"]
    if vw <= 0 or vh <= 0:
        return None

    root = tk.Tk()
    root.overrideredirect(True)
    try:
        # 关闭 Tk 的 DPI 缩放，保证 canvas 坐标就是物理屏幕像素
        root.tk.call("tk", "scaling", 1.0)
    except Exception:
        pass
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.28)
    root.configure(bg="black")
    root.geometry(f"{vw}x{vh}+0+0")
    canvas = tk.Canvas(root, bg="black", highlightthickness=0, cursor="crosshair")
    canvas.pack(fill="both", expand=True)
    canvas.create_text(
        vw // 2, 48, text="拖动鼠标框选区域，按 Esc 取消",
        fill="#FFFFFF", font=("Microsoft YaHei UI", 14),
    )
    hint = canvas.create_text(
        vw // 2, 82, text="", fill="#BFD4FF", font=("Microsoft YaHei UI", 11)
    )

    state = {"start": None, "start_screen": None, "rect": None, "result": None, "hwnd": 0}

    def on_press(event) -> None:
        try:
            root.grab_set()
        except Exception:
            pass
        x, y = float(event.x), float(event.y)
        state["start"] = (x, y)
        # x_root/y_root 是事件发生时的屏幕坐标，不受事件处理延迟影响
        state["start_screen"] = (float(event.x_root), float(event.y_root))
        if state["rect"]:
            canvas.delete(state["rect"])
        state["rect"] = canvas.create_rectangle(
            x, y, x, y, outline="#4C8DFF", width=2
        )

    def on_move(event) -> None:
        if not state["start"] or not state["rect"]:
            return
        x, y = float(event.x), float(event.y)
        sx, sy = state["start"]
        canvas.coords(state["rect"], sx, sy, x, y)
        w = abs(int(x) - int(sx))
        h = abs(int(y) - int(sy))
        canvas.itemconfigure(hint, text=f"{w} × {h}")

    def on_release(event) -> None:
        if not state["start"]:
            return
        sx, sy = state.get("start_screen") or (vx + state["start"][0], vy + state["start"][1])
        ex, ey = float(event.x_root), float(event.y_root)
        if state["rect"]:
            canvas.coords(state["rect"], state["start"][0], state["start"][1],
                          float(event.x), float(event.y))
        region = {
            "left": min(sx, ex),
            "top": min(sy, ey),
            "right": max(sx, ex),
            "bottom": max(sy, ey),
        }
        state["result"] = normalize_region(region, bounds)
        try:
            root.grab_release()
        except Exception:
            pass
        root.destroy()

    def on_cancel(_event=None) -> None:
        state["result"] = None
        try:
            root.grab_release()
        except Exception:
            pass
        root.destroy()

    def on_ready() -> None:
        state["hwnd"] = _place_window(root, vx, vy, vw, vh)
        try:
            root.update_idletasks()
        except Exception:
            pass
        # 窗口被系统按 DPI 缩放时，强制 canvas 使用客户区物理尺寸
        if state["hwnd"]:
            cw, ch = _client_size(state["hwnd"])
            try:
                canvas.pack_forget()
                canvas.place(x=0, y=0, width=cw, height=ch)
            except Exception:
                pass
        root.focus_force()

    root.bind("<ButtonPress-1>", on_press)
    root.bind("<B1-Motion>", on_move)
    root.bind("<ButtonRelease-1>", on_release)
    root.bind("<Escape>", on_cancel)
    root.after(10, on_ready)
    try:
        root.mainloop()
    finally:
        try:
            root.destroy()
        except Exception:
            pass
    return state["result"]

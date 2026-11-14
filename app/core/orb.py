"""悬浮球：分层窗口 + 3 倍超采样渲染，圆形边缘完全抗锯齿。"""
from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes

from .win32util import set_window_pos
from .glow import (
    AC_SRC_ALPHA,
    AC_SRC_OVER,
    BLENDFUNCTION,
    SW_HIDE,
    SW_SHOWNOACTIVATE,
    SWP_NOACTIVATE,
    SWP_SHOWWINDOW,
    WNDCLASSW,
    WNDPROC,
    WS_EX_LAYERED,
    WS_EX_TOOLWINDOW,
    WS_EX_TOPMOST,
    WS_POPUP,
    _make_surface,
    _paint,
)

WM_DESTROY = 0x0002
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_MOUSELEAVE = 0x02A3
TME_LEAVE = 0x00000002
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SUPERSAMPLE = 3
FRAME_INTERVAL = 0.033
ACCENT = (65, 118, 230)
WARN = (245, 158, 11)
ERROR = (239, 68, 68)
INK = (15, 17, 21)


class TRACKMOUSEEVENT(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("hwndTrack", wintypes.HWND),
        ("dwHoverTime", wintypes.DWORD),
    ]


def _render(side: int, status: str, hover: bool, t: float):
    """绘制球体、圆环、状态点，返回 BGRA（已预乘 alpha）。"""
    import numpy as np
    from PIL import Image, ImageDraw

    s = SUPERSAMPLE
    n = side * s
    center = (n - 1) / 2.0
    radius = n / 2.0

    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
    gx = (xx - n * 0.5) / (n * 0.78)
    gy = (yy - n * 0.22) / (n * 0.78)
    gr = np.clip(np.sqrt(gx * gx + gy * gy), 0.0, 1.0)[..., None]
    c0 = np.array([255, 255, 255], np.float32)
    c1 = np.array([251, 252, 254], np.float32)
    c2 = np.array([243, 245, 248], np.float32)
    col = np.where(
        gr < 0.62,
        c0 + (c1 - c0) * (gr / 0.62),
        c1 + (c2 - c1) * ((gr - 0.62) / 0.38),
    )
    if hover:
        col = np.clip(col * 1.03, 0.0, 255.0)

    dist = np.sqrt((xx - center) ** 2 + (yy - center) ** 2)
    rgba = np.zeros((n, n, 4), np.uint8)
    rgba[..., :3] = col.astype(np.uint8)
    rgba[..., 3] = np.where(dist <= radius, 255, 0).astype(np.uint8)
    img = Image.fromarray(rgba, "RGBA")
    draw = ImageDraw.Draw(img)

    border = (*ERROR, 232) if status == "error" else (*INK, 210)
    draw.ellipse((0, 0, n - 1, n - 1), outline=border, width=s)

    # 与主界面左上角品牌图标一致：24/43 直径的细圆环 + 右下蓝色状态点
    scale = 1.0
    ring_alpha = 228
    if status == "thinking":
        scale = 1.0 + 0.06 * np.sin(t * 6.2831853 / 1.8)
        ring_alpha = int(190 + 60 * (0.5 + 0.5 * np.sin(t * 6.2831853 / 1.8)))
    r_ring = n * (12.0 / 43.0) * scale
    draw.ellipse(
        (center - r_ring, center - r_ring, center + r_ring, center + r_ring),
        outline=(*border[:3], ring_alpha), width=max(1, int(round(1.6 * s))),
    )
    if status == "working":
        start = (t * 360.0 / 3.2) % 360.0
        draw.arc(
            (center - r_ring, center - r_ring, center + r_ring, center + r_ring),
            start=start, end=start + 80, fill=(*ACCENT, 255), width=max(2, int(round(1.6 * s))),
        )

    # 状态点：中心在圆环右下方，与品牌 Logo 的偏移一致（+12,+8）
    dot_color = {"thinking": WARN, "working": ACCENT, "error": ERROR}.get(status, ACCENT)
    pulse = 1.0
    if status in ("thinking", "working"):
        pulse = 1.0 + 0.18 * (0.5 + 0.5 * np.sin(t * 6.2831853 / 0.9))
    r_dot = n * (3.0 / 43.0) * pulse
    dx = center + n * (12.0 / 43.0) * scale
    dy = center + n * (8.0 / 43.0) * scale
    halo = max(s, int(round(2.0 * s)))
    draw.ellipse(
        (dx - r_dot - halo, dy - r_dot - halo, dx + r_dot + halo, dy + r_dot + halo),
        fill=(255, 255, 255, 240),
    )
    draw.ellipse((dx - r_dot, dy - r_dot, dx + r_dot, dy + r_dot),
                 fill=(*dot_color, 255))

    # 预乘 alpha 后降采样，得到平滑的圆边
    arr = np.array(img)
    arr[..., :3] = (arr[..., :3].astype(np.uint16) * arr[..., 3:4] // 255).astype(np.uint8)
    small = np.array(Image.fromarray(arr, "RGBA").resize((side, side), Image.LANCZOS))
    bgra = np.empty_like(small)
    bgra[..., 0] = small[..., 2]
    bgra[..., 1] = small[..., 1]
    bgra[..., 2] = small[..., 0]
    bgra[..., 3] = small[..., 3]
    return bgra


class OrbWindow:
    """独立线程运行的悬浮球：3 倍超采样分层窗口，支持点击/拖动/右键菜单。"""

    def __init__(self, base_size: int, on_click=None, on_menu=None, on_move_end=None):
        self.base_size = base_size
        self.on_click = on_click
        self.on_menu = on_menu
        self.on_move_end = on_move_end
        self._side = 0
        self._status = "idle"
        self._hover = False
        self._visible = False
        self._dirty = True
        self._pos: tuple[int, int] | None = None
        self._drag = None
        self._tracked = False
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None
        self._hwnd = 0

    # ---------------- 对外 ----------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="nexus-orb")
        self._thread.start()
        self._ready.wait(2)

    def hwnd(self) -> int:
        return self._hwnd

    def show_at(self, x: int, y: int) -> None:
        self._pos = (int(x), int(y))
        self._visible = True

    def hide(self) -> None:
        self._visible = False

    def set_status(self, status: str) -> None:
        status = str(status or "idle")
        if status != self._status:
            self._status = status
            self._dirty = True

    def close(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    # ---------------- 内部 ----------------
    def _run(self) -> None:
        import numpy as np

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        hwnd = 0
        mem_dc = 0
        hbmp = 0
        screen_dc = 0
        try:
            kernel32.GetModuleHandleW.restype = ctypes.c_void_p
            hinst = kernel32.GetModuleHandleW(None)
            dpi = int(user32.GetDpiForSystem() or 96)
            self._side = max(24, int(round(self.base_size * dpi / 96.0)))
            side = self._side

            user32.DefWindowProcW.argtypes = [
                wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
            ]
            user32.DefWindowProcW.restype = ctypes.c_ssize_t
            user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
            user32.ShowWindow.restype = wintypes.BOOL
            user32.DestroyWindow.argtypes = [wintypes.HWND]
            user32.DestroyWindow.restype = wintypes.BOOL
            user32.SetCapture.argtypes = [wintypes.HWND]
            user32.SetCapture.restype = wintypes.HWND
            user32.ReleaseCapture.restype = wintypes.BOOL
            user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
            user32.GetCursorPos.restype = wintypes.BOOL
            user32.TrackMouseEvent.argtypes = [ctypes.POINTER(TRACKMOUSEEVENT)]
            user32.TrackMouseEvent.restype = wintypes.BOOL

            def wndproc(h, msg, wparam, lparam):
                if msg == WM_LBUTTONDOWN:
                    self._on_down(h)
                    return 0
                if msg == WM_MOUSEMOVE:
                    self._on_move(h)
                    return 0
                if msg == WM_LBUTTONUP:
                    self._on_up(h)
                    return 0
                if msg == WM_RBUTTONUP:
                    self._on_right()
                    return 0
                if msg == WM_MOUSELEAVE:
                    self._hover = False
                    self._tracked = False
                    self._dirty = True
                    return 0
                return user32.DefWindowProcW(h, msg, wparam, lparam)

            proc = WNDPROC(wndproc)
            class_name = "NexusOrbLayer"
            wc = WNDCLASSW(0, proc, 0, 0, hinst, None, None, None, None, class_name)
            user32.RegisterClassW(ctypes.byref(wc))
            user32.CreateWindowExW.argtypes = [
                wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p,
            ]
            user32.CreateWindowExW.restype = wintypes.HWND
            ex = WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_TOPMOST
            hwnd = user32.CreateWindowExW(
                ex, class_name, "NexusOrbLayer", WS_POPUP,
                0, 0, side, side, None, None, hinst, None,
            )
            if not hwnd:
                return
            self._hwnd = int(hwnd)

            screen_dc, mem_dc, hbmp, bits = _make_surface(ctypes.windll.gdi32, user32,
                                                          side, side)
            if not hbmp or not bits:
                return
            blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
            self._ready.set()

            shown = False
            shown_pos = None
            started = time.perf_counter()
            last = 0.0
            msg = wintypes.MSG()
            while not self._stop.is_set():
                if self._visible and not shown:
                    x, y = self._pos or (0, 0)
                    set_window_pos(hwnd, -1, x, y, side, side,
                                   SWP_NOACTIVATE | SWP_SHOWWINDOW)
                    user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
                    shown = True
                    shown_pos = (x, y)
                    last = 0.0
                    self._dirty = True
                elif not self._visible and shown:
                    user32.ShowWindow(hwnd, SW_HIDE)
                    shown = False
                elif shown and self._pos and self._pos != shown_pos:
                    set_window_pos(hwnd, -1, self._pos[0], self._pos[1], side, side,
                                   SWP_NOACTIVATE)
                    shown_pos = self._pos
                if shown:
                    now = time.perf_counter()
                    animating = self._status in ("thinking", "working")
                    if (animating or self._dirty) and now - last >= FRAME_INTERVAL:
                        last = now
                        self._dirty = False
                        frame = _render(side, self._status, self._hover, now - started)
                        ctypes.memmove(bits, frame.tobytes(), frame.nbytes)
                        # UpdateLayeredWindow 的 pptDst 会同时设定窗口位置，必须传真实坐标
                        rect = wintypes.RECT()
                        user32.GetWindowRect(hwnd, ctypes.byref(rect))
                        _paint(user32, hwnd, screen_dc, mem_dc,
                               rect.left, rect.top, side, side, blend)
                while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0x0001):
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
                time.sleep(0.016)
        finally:
            self._ready.set()
            try:
                if hwnd:
                    user32.DestroyWindow(hwnd)
                if hbmp:
                    ctypes.windll.gdi32.DeleteObject(hbmp)
                if mem_dc:
                    ctypes.windll.gdi32.DeleteDC(mem_dc)
                if screen_dc:
                    user32.ReleaseDC(None, screen_dc)
            except Exception:
                pass
            self._hwnd = 0

    # ---------------- 鼠标 ----------------
    def _cursor(self) -> tuple[int, int]:
        pt = wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y

    def _inside(self, hwnd: int, mx: int, my: int) -> bool:
        rect = wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
        cx = rect.left + (rect.right - rect.left) / 2.0
        cy = rect.top + (rect.bottom - rect.top) / 2.0
        return (mx - cx) ** 2 + (my - cy) ** 2 <= ((rect.right - rect.left) / 2.0) ** 2

    def _on_down(self, hwnd: int) -> None:
        mx, my = self._cursor()
        if not self._inside(hwnd, mx, my):
            return
        rect = wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
        self._drag = {"ox": mx - rect.left, "oy": my - rect.top,
                      "sx": mx, "sy": my, "moved": 0}
        ctypes.windll.user32.SetCapture(hwnd)

    def _on_move(self, hwnd: int) -> None:
        mx, my = self._cursor()
        drag = self._drag
        if drag:
            drag["moved"] += abs(mx - drag["sx"]) + abs(my - drag["sy"])
            drag["sx"], drag["sy"] = mx, my
            set_window_pos(hwnd, -1, mx - drag["ox"], my - drag["oy"], 0, 0,
                           SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
            self._pos = (mx - drag["ox"], my - drag["oy"])
            return
        if not self._hover:
            self._hover = True
            self._dirty = True
        if not self._tracked:
            track = TRACKMOUSEEVENT(ctypes.sizeof(TRACKMOUSEEVENT), TME_LEAVE, hwnd, 0)
            ctypes.windll.user32.TrackMouseEvent(ctypes.byref(track))
            self._tracked = True

    def _on_up(self, hwnd: int) -> None:
        ctypes.windll.user32.ReleaseCapture()
        drag = self._drag
        self._drag = None
        if not drag:
            return
        if drag["moved"] < 5:
            if self.on_click:
                try:
                    self.on_click()
                except Exception:
                    pass
            return
        rect = wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
        if self.on_move_end:
            try:
                self.on_move_end(rect.left, rect.top)
            except Exception:
                pass

    def _on_right(self) -> None:
        if not self.on_menu:
            return
        x, y = self._cursor()
        try:
            self.on_menu(x, y)
        except Exception:
            pass

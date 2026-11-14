"""AI 控制屏幕时的全屏边缘光晕：蓝白渐变沿边框流转、置顶、点击穿透、ESC 重新接管。"""
from __future__ import annotations

import ctypes
import os
import threading
import time
from ctypes import wintypes

from .win32util import set_window_pos

WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOPMOST = 0x00000008
WS_POPUP = 0x80000000
SW_SHOWNOACTIVATE = 4
SW_HIDE = 0
ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01
PM_REMOVE = 0x0001
VK_ESCAPE = 0x1B
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14
LLKHF_INJECTED = 0x10
LLMHF_INJECTED = 0x01
WM_QUIT = 0x0012


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", wintypes.POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


HOOKPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
)

TAU = 6.283185307179586
# 蓝白渐变沿边框流转的速度（周期/秒）与目标帧间隔
WAVE_SPEED = 0.10
FRAME_INTERVAL = 0.033
# 光晕厚度占屏幕短边的比例
EDGE_RATIO = 0.05
CORE_BLUE = (64, 136, 255)
CORE_WHITE = (232, 244, 255)

WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_ubyte),
        ("BlendFlags", ctypes.c_ubyte),
        ("SourceConstantAlpha", ctypes.c_ubyte),
        ("AlphaFormat", ctypes.c_ubyte),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


def _strip_bgra(xs, ys, edge, screen_w, screen_h, phase):
    """按屏幕全局坐标渲染一条边缘带，返回 BGRA（已预乘 alpha）像素。

    xs / ys 是这条带覆盖的全局坐标，因此四条带在四角重叠处的结果完全一致。
    """
    import numpy as np

    x = xs[None, :]
    y = ys[:, None]
    dx = np.minimum(x, screen_w - 1 - x)
    dy = np.minimum(y, screen_h - 1 - y)
    dist = np.minimum(dx, dy)
    near = np.clip(1.0 - dist / edge, 0.0, 1.0)
    fade = near ** 1.55

    u = x / max(screen_w - 1, 1)
    v = y / max(screen_h - 1, 1)
    s_top = 0.25 * u
    s_bottom = 0.5 + 0.25 * (1.0 - u)
    s_h = np.where(v < 0.5, s_top, s_bottom)
    s_left = 0.75 + 0.25 * (1.0 - v)
    s_right = 0.25 + 0.25 * v
    s_v = np.where(x < (screen_w - 1) / 2, s_left, s_right)

    # 对角线附近平滑混合两组周长参数，避免接缝
    wd = dx + dy + 1e-6
    s_v = s_v + np.round(s_h - s_v)
    s = ((dx / wd) * s_h + (dy / wd) * s_v) % 1.0

    # 只保留蓝白渐变流转，亮度恒定
    shift = 0.5 + 0.5 * np.sin(TAU * (s - phase))
    mix = np.clip(0.30 * near + 0.70 * shift, 0.0, 1.0)[..., None]
    alpha = fade * 196.0
    a = alpha.astype(np.uint8)

    color = (
        np.array(CORE_BLUE, np.float32) * (1.0 - mix)
        + np.array(CORE_WHITE, np.float32) * mix
    )
    rgb = (color * alpha[..., None] / 255.0).astype(np.uint8)

    out = np.empty(a.shape + (4,), np.uint8)
    out[..., 0] = rgb[..., 2]
    out[..., 1] = rgb[..., 1]
    out[..., 2] = rgb[..., 0]
    out[..., 3] = a
    return out


_BADGE_GEOM = {}
_BADGE_SCALE = 3


def _render_badge(phase: float):
    """渲染底部提示条：蓝白渐变描边随时间流转，返回 BGRA（已预乘 alpha）图像。

    以 3 倍尺寸绘制再降采样，圆角与描边边缘达到抗锯齿效果。
    """
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

    geom = _BADGE_GEOM.get("value")
    if geom is None:
        text = "AI 正在控制您的电脑屏幕，按下 ESC 重新接管"
        try:
            font1 = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 18)
        except OSError:
            font1 = ImageFont.load_default()
        probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
        bbox1 = probe.textbbox((0, 0), text, font=font1)
        w = bbox1[2] - bbox1[0] + 40
        h = bbox1[3] - bbox1[1] + 20
        S = _BADGE_SCALE
        try:
            font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 18 * S)
        except OSError:
            font = font1
        base = Image.new("RGBA", (w * S, h * S), (0, 0, 0, 0))
        draw = ImageDraw.Draw(base)
        draw.rounded_rectangle(
            (0, 0, w * S - 1, h * S - 1), radius=15 * S, fill=(15, 17, 21, 176)
        )
        bbox = draw.textbbox((0, 0), text, font=font)
        draw.text(
            ((w * S - (bbox[2] - bbox[0])) // 2 - bbox[0],
             (h * S - (bbox[3] - bbox[1])) // 2 - bbox[1]),
            text, font=font, fill=(238, 244, 255, 242),
        )
        geom = (text, w, h, base)
        _BADGE_GEOM["value"] = geom
    text, w, h, base = geom
    S = _BADGE_SCALE

    img = base.copy()

    # 蓝白渐变描边：颜色沿宽度方向缓慢流动，与屏幕光晕一致
    W, H = w * S, h * S
    t = 0.5 + 0.5 * np.sin(TAU * (np.arange(W, dtype=np.float32) / max(W - 1, 1) - phase))
    mix = (0.25 + 0.75 * t)[:, None]
    cols = (
        np.array(CORE_BLUE, np.float32) * (1.0 - mix)
        + np.array(CORE_WHITE, np.float32) * mix
    ).astype(np.uint8)
    grad = np.zeros((H, W, 4), np.uint8)
    grad[..., 0] = cols[None, :, 0]
    grad[..., 1] = cols[None, :, 1]
    grad[..., 2] = cols[None, :, 2]
    grad[..., 3] = 220
    grad_img = Image.fromarray(grad, "RGBA")
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, W - 1, H - 1), radius=15 * S, outline=255, width=2 * S
    )
    img.paste(grad_img, (0, 0), mask)

    # 预乘 alpha 后降采样，保证边缘抗锯齿且不发灰
    arr = np.array(img)
    arr[..., :3] = (arr[..., :3].astype(np.uint16) * arr[..., 3:4] // 255).astype(np.uint8)
    small = np.array(
        Image.fromarray(arr, "RGBA").resize((w, h), Image.LANCZOS)
    )
    bgra = np.empty_like(small)
    bgra[..., 0] = small[..., 2]
    bgra[..., 1] = small[..., 1]
    bgra[..., 2] = small[..., 0]
    bgra[..., 3] = small[..., 3]
    return bgra


def _make_surface(gdi32, user32, width: int, height: int):
    """创建承载位图的兼容 DC 与 DIB，返回 (screen_dc, mem_dc, hbmp, bits)。"""
    # 句柄是 64 位值，必须声明 restype，否则会被截断成 int 导致 OverflowError
    user32.GetDC.restype = wintypes.HDC
    user32.GetDC.argtypes = [wintypes.HWND]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateDIBSection.restype = wintypes.HBITMAP
    gdi32.CreateDIBSection.argtypes = [
        wintypes.HDC, ctypes.POINTER(BITMAPINFO), wintypes.UINT,
        ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD,
    ]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    screen_dc = user32.GetDC(None)
    mem_dc = gdi32.CreateCompatibleDC(screen_dc)
    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = width
    bmi.bmiHeader.biHeight = -height
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0
    bits = ctypes.c_void_p()
    hbmp = gdi32.CreateDIBSection(
        mem_dc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0
    )
    if hbmp and bits:
        gdi32.SelectObject(mem_dc, hbmp)
    return screen_dc, mem_dc, hbmp, bits


def _paint(user32, hwnd, screen_dc, mem_dc, x, y, width, height, blend):
    user32.UpdateLayeredWindow.argtypes = [
        wintypes.HWND, wintypes.HDC, ctypes.POINTER(wintypes.POINT),
        ctypes.POINTER(wintypes.SIZE), wintypes.HDC, ctypes.POINTER(wintypes.POINT),
        wintypes.DWORD, ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD,
    ]
    user32.UpdateLayeredWindow.restype = wintypes.BOOL
    dst = wintypes.POINT(x, y)
    src = wintypes.POINT(0, 0)
    size = wintypes.SIZE(width, height)
    user32.UpdateLayeredWindow(
        hwnd, screen_dc, ctypes.byref(dst), ctypes.byref(size),
        mem_dc, ctypes.byref(src), 0, ctypes.byref(blend), ULW_ALPHA,
    )


class ScreenGlow:
    """独立线程运行的置顶光晕窗口，不拦截鼠标，也不抢焦点。"""

    def __init__(self, on_escape=None, block_input: bool = False):
        self.on_escape = on_escape
        self.block_input = block_input
        self._visible = False
        self._blocked = False
        self._hook_ok = False
        self._esc_pressed = False
        self._guard_thread: threading.Thread | None = None
        self._guard_stop: threading.Event | None = None
        self._guard_tid = 0
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None

    def _set_block(self, on: bool) -> None:
        """接管期间屏蔽用户的鼠标键盘；ESC 与程序注入的输入仍然放行。"""
        if not self.block_input or on == self._blocked:
            return
        self._blocked = bool(on)
        if on:
            self._guard_stop = threading.Event()
            self._guard_thread = threading.Thread(
                target=self._guard_run, args=(self._guard_stop,),
                daemon=True, name="nexus-input-guard",
            )
            self._guard_thread.start()
        else:
            if self._guard_stop:
                self._guard_stop.set()
            tid = self._guard_tid
            if tid:
                try:
                    ctypes.windll.user32.PostThreadMessageW(tid, WM_QUIT, 0, 0)
                except OSError:
                    pass
            if self._guard_thread:
                self._guard_thread.join(timeout=0.8)
            self._guard_thread = None
            self._guard_stop = None
            self._esc_pressed = False

    def _guard_run(self, stop: threading.Event) -> None:
        """独立线程装低级键鼠钩子：物理输入吞掉，ESC 与注入事件放行。"""
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        try:
            # 模块句柄是 64 位值，必须声明 restype，否则会被截断导致钩子安装失败
            kernel32.GetModuleHandleW.restype = ctypes.c_void_p
            hinst = kernel32.GetModuleHandleW(None)
            self._guard_tid = int(kernel32.GetCurrentThreadId())
            user32.SetWindowsHookExW.argtypes = [
                ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD
            ]
            user32.SetWindowsHookExW.restype = wintypes.HHOOK
            user32.CallNextHookEx.argtypes = [
                wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
            ]
            user32.CallNextHookEx.restype = ctypes.c_ssize_t

            def kb_proc(code: int, wparam, lparam):
                if code >= 0:
                    info = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                    physical = not (info.flags & LLKHF_INJECTED)
                    if physical and info.vkCode == VK_ESCAPE and wparam in (0x0100, 0x0104):
                        # 只有真实按键才算“用户接管”；模型注入的 ESC 不能触发。
                        self._esc_pressed = True
                    if physical and info.vkCode != VK_ESCAPE:
                        return 1
                return user32.CallNextHookEx(None, code, wparam, lparam)

            def mouse_proc(code: int, wparam, lparam):
                if code >= 0:
                    info = ctypes.cast(lparam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                    if not (info.flags & LLMHF_INJECTED):
                        return 1
                return user32.CallNextHookEx(None, code, wparam, lparam)

            kb = HOOKPROC(kb_proc)
            ms = HOOKPROC(mouse_proc)
            h_kb = user32.SetWindowsHookExW(WH_KEYBOARD_LL, kb, hinst, 0)
            h_ms = user32.SetWindowsHookExW(WH_MOUSE_LL, ms, hinst, 0)
            self._hook_ok = bool(h_kb)
            if os.environ.get("NEXUS_GLOW_TRACE"):
                print(f"[glow] hooks kb={h_kb} ms={h_ms}", flush=True)
            try:
                msg = wintypes.MSG()
                while not stop.is_set():
                    ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                    if ret <= 0:
                        break
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
            finally:
                if h_kb:
                    user32.UnhookWindowsHookEx(h_kb)
                if h_ms:
                    user32.UnhookWindowsHookEx(h_ms)
        finally:
            self._hook_ok = False
            self._guard_tid = 0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="nexus-glow")
        self._thread.start()
        self._ready.wait(3)

    def show(self) -> None:
        self._visible = True

    def alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def hide(self) -> None:
        self._visible = False

    def close(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        self._set_block(False)

    def _run(self) -> None:
        import numpy as np

        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        hwnd = 0
        badge_hwnd = 0
        dst_dc = badge_dc = 0
        dst_bmp = badge_bmp = 0
        dst_screen = badge_screen = 0
        try:
            kernel32 = ctypes.windll.kernel32
            kernel32.GetModuleHandleW.restype = ctypes.c_void_p
            hinst = kernel32.GetModuleHandleW(None)
            user32.DefWindowProcW.argtypes = [
                wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
            ]
            user32.DefWindowProcW.restype = ctypes.c_ssize_t
            user32.CreateWindowExW.argtypes = [
                wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p,
            ]
            user32.CreateWindowExW.restype = wintypes.HWND
            user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
            user32.ShowWindow.restype = wintypes.BOOL
            user32.DestroyWindow.argtypes = [wintypes.HWND]
            user32.DestroyWindow.restype = wintypes.BOOL
            class_name = "NexusGlowWnd"
            proc = WNDPROC(lambda h, m, w, l: user32.DefWindowProcW(h, m, w, l))
            wc = WNDCLASSW(0, proc, 0, 0, hinst, None, None, None, None, class_name)
            user32.RegisterClassW(ctypes.byref(wc))

            vx = user32.GetSystemMetrics(76)
            vy = user32.GetSystemMetrics(77)
            vw = user32.GetSystemMetrics(78)
            vh = user32.GetSystemMetrics(79)
            if vw <= 0 or vh <= 0:
                return
            ex_style = (WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW
                        | WS_EX_NOACTIVATE | WS_EX_TOPMOST)
            hwnd = user32.CreateWindowExW(
                ex_style, class_name, "NexusGlow", WS_POPUP,
                vx, vy, vw, vh, None, None, hinst, None,
            )
            if not hwnd:
                return

            # 全屏帧缓冲直接映射到 DIB 内存，只逐帧覆盖四条边缘带，中间始终透明
            dst_screen, dst_dc, dst_bmp, dst_bits = _make_surface(
                gdi32, user32, vw, vh
            )
            if not dst_bmp or not dst_bits:
                return
            buf = np.ctypeslib.as_array(
                ctypes.cast(dst_bits, ctypes.POINTER(ctypes.c_ubyte)),
                shape=(vh * vw * 4,),
            ).reshape(vh, vw, 4)

            edge = max(28, int(min(vw, vh) * EDGE_RATIO))
            edge = min(edge, vw // 2, vh // 2)
            xs = np.arange(vw, dtype=np.float32)
            ys = np.arange(vh, dtype=np.float32)

            def render(phase):
                buf[0:edge] = _strip_bgra(xs, ys[:edge], edge, vw, vh, phase)
                buf[vh - edge:vh] = _strip_bgra(xs, ys[vh - edge:], edge, vw, vh, phase)
                buf[:, 0:edge] = _strip_bgra(xs[:edge], ys, edge, vw, vh, phase)
                buf[:, vw - edge:vw] = _strip_bgra(xs[vw - edge:], ys, edge, vw, vh, phase)

            render(0.0)

            # 提示条单独一个全分辨率小窗，文字保持清晰
            badge = _render_badge(0.0)
            bh, bw = badge.shape[0], badge.shape[1]
            bx = vx + (vw - bw) // 2
            by = vy + vh - bh - 44
            badge_hwnd = user32.CreateWindowExW(
                ex_style, class_name, "NexusGlowTip", WS_POPUP,
                bx, by, bw, bh, None, None, hinst, None,
            )
            if not badge_hwnd:
                return
            badge_screen, badge_dc, badge_bmp, badge_bits = _make_surface(
                gdi32, user32, bw, bh
            )
            if not badge_bmp or not badge_bits:
                return
            ctypes.memmove(badge_bits, badge.tobytes(), badge.nbytes)

            blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
            _paint(user32, hwnd, dst_screen, dst_dc, vx, vy, vw, vh, blend)
            _paint(user32, badge_hwnd, badge_screen, badge_dc, bx, by, bw, bh, blend)
            self._ready.set()

            shown = False
            last_esc = False
            started = time.perf_counter()
            msg = wintypes.MSG()
            while not self._stop.is_set():
                if self._visible and not shown:
                    user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
                    set_window_pos(hwnd, -1, vx, vy, vw, vh,
                                   SWP_NOACTIVATE | SWP_SHOWWINDOW)
                    user32.ShowWindow(badge_hwnd, SW_SHOWNOACTIVATE)
                    set_window_pos(badge_hwnd, -1, bx, by, bw, bh,
                                   SWP_NOACTIVATE | SWP_SHOWWINDOW)
                    self._set_block(True)
                    shown = True
                elif not self._visible and shown:
                    user32.ShowWindow(hwnd, SW_HIDE)
                    user32.ShowWindow(badge_hwnd, SW_HIDE)
                    self._set_block(False)
                    shown = False
                frame_started = time.perf_counter()
                if shown:
                    phase = (frame_started - started) * WAVE_SPEED
                    render(phase)
                    _paint(user32, hwnd, dst_screen, dst_dc, vx, vy, vw, vh, blend)
                    badge = _render_badge(phase)
                    ctypes.memmove(badge_bits, badge.tobytes(), badge.nbytes)
                    _paint(user32, badge_hwnd, badge_screen, badge_dc, bx, by, bw, bh, blend)
                    if os.environ.get("NEXUS_GLOW_DEBUG"):
                        with open(os.environ["NEXUS_GLOW_DEBUG"], "a", encoding="utf-8") as fh:
                            fh.write(f"{time.time():.3f}\n")
                    # 优先用低级钩子识别“物理 ESC”；钩子不可用时才退回轮询，
                    # 避免模型通过 ui_act 注入的 ESC 被当成用户接管。
                    if self._hook_ok:
                        down = self._esc_pressed
                        self._esc_pressed = False
                    else:
                        down = bool(user32.GetAsyncKeyState(VK_ESCAPE) & 0x8000)
                    if down and not last_esc:
                        self._visible = False
                        self._set_block(False)
                        user32.ShowWindow(hwnd, SW_HIDE)
                        user32.ShowWindow(badge_hwnd, SW_HIDE)
                        shown = False
                        if self.on_escape:
                            try:
                                self.on_escape()
                            except Exception:
                                pass
                    last_esc = down
                while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
                spent = time.perf_counter() - frame_started
                if spent < FRAME_INTERVAL:
                    time.sleep(FRAME_INTERVAL - spent)
        finally:
            self._ready.set()
            self._set_block(False)
            try:
                if hwnd:
                    user32.DestroyWindow(hwnd)
                if badge_hwnd:
                    user32.DestroyWindow(badge_hwnd)
                for hbmp in (dst_bmp, badge_bmp):
                    if hbmp:
                        gdi32.DeleteObject(hbmp)
                for dc in (dst_dc, badge_dc):
                    if dc:
                        gdi32.DeleteDC(dc)
                for dc in (dst_screen, badge_screen):
                    if dc:
                        user32.ReleaseDC(None, dc)
            except Exception:
                pass

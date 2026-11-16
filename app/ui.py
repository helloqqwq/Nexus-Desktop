"""桌面外壳：WebView2 窗口、悬浮球、全局热键、托盘、Win32 辅助。"""
from __future__ import annotations

import base64
import ctypes
import io
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from ctypes import wintypes
from pathlib import Path

import webview

from .core.agent import Agent
from .core import avatar as avatar_store
from .core.browser import BrowserHost
from .core.compress import COMPRESS_RATIO
from .core.config import Config
from .core.asr import SpeechRecognizer
from .core.glow import ScreenGlow
from .core.i18n import get_language, set_language, t
from .core.orb import OrbWindow
from .core.office import docx_doc, kind_of, pdf_doc, pptx_doc, xlsx_doc
from .core.perf import ResourceMonitor
from .core.llm import LLMClient, LLMError
from .core import providers as provider_catalog
from .core.safety import Safety
from .core.scheduler import Scheduler, register_tools as register_schedule_tools
from .core.store import Store
from .core.term import TerminalHub
from .core.tools import Registry, desktop_tools
from .core.updater import Updater, normalize_repo
from .core.win32util import set_window_pos

log = logging.getLogger("nexus.ui")

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
WEB = ROOT / "app" / "web"
MAIN_TITLE = "Nexus"
ORB_TITLE = "NexusOrb"
QUICK_TITLE = "NexusQuick"
ONBOARD_TITLE = "NexusOnboarding"
WHATSNEW_TITLE = "NexusWhatsNew"
ICON_PATH = WEB / "assets" / "nexus.ico"
ORB_SIZE = 43  # 悬浮球逻辑直径（px，约为旧版 86 的一半）

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010


def browser_target(raw: str) -> str | None:
    """把用户输入变成可打开的目标：网址、localhost 或本地文件路径。"""
    text = str(raw or "").strip().strip('"')
    if not text:
        return None
    if re.match(r"^(https?|file)://", text, re.I):
        return text
    if re.match(r"^(localhost|127\.0\.0\.1)(:\d{1,5})?(/.*)?$", text, re.I):
        return "http://" + text
    path = Path(os.path.expandvars(os.path.expanduser(text)))
    try:
        if path.is_file():
            return path.resolve().as_uri()
    except OSError:
        pass
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.\-]*\.[A-Za-z]{2,}(:\d{1,5})?(/[\S]*)?", text):
        return "https://" + text
    return None


def browser_exe() -> Path | None:
    env = os.environ
    candidates = [
        Path(env.get("ProgramFiles(x86)") or r"C:\Program Files (x86)")
        / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(env.get("ProgramFiles") or r"C:\Program Files")
        / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(env.get("LOCALAPPDATA") or "")
        / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(env.get("ProgramFiles") or r"C:\Program Files")
        / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(env.get("ProgramFiles(x86)") or r"C:\Program Files (x86)")
        / "Google" / "Chrome" / "Application" / "chrome.exe",
    ]
    for item in candidates:
        try:
            if item and item.is_file():
                return item
        except OSError:
            continue
    return None


class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


def _hwnd(title: str) -> int:
    try:
        user32 = ctypes.windll.user32
        user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        user32.FindWindowW.restype = wintypes.HWND
        return int(user32.FindWindowW(None, title) or 0)
    except OSError:
        return 0


def _cursor() -> tuple[int, int]:
    pt = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def _window_rect(hwnd: int) -> tuple[int, int, int, int]:
    rect = RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top


def _move_window(hwnd: int, x: int, y: int) -> None:
    if hwnd:
        set_window_pos(hwnd, 0, x, y, 0, 0,
                       SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)


def _raise_window(hwnd: int) -> None:
    """把窗口提到最前，但不长期置顶；避免抢焦点接口在部分环境触发崩溃。"""
    if not hwnd:
        return
    try:
        user32 = ctypes.windll.user32
        user32.SetWindowPos.argtypes = [
            wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, ctypes.c_uint,
        ]
        user32.SetWindowPos.restype = wintypes.BOOL
        user32.SetWindowPos(
            hwnd, wintypes.HWND(-1), 0, 0, 0, 0,
            SWP_NOSIZE | SWP_NOMOVE | SWP_SHOWWINDOW,
        )

        def drop() -> None:
            try:
                user32.SetWindowPos(
                    hwnd, wintypes.HWND(-2), 0, 0, 0, 0,
                    SWP_NOSIZE | SWP_NOMOVE,
                )
            except Exception:
                pass

        threading.Timer(0.9, drop).start()
    except Exception:
        pass


def _work_area() -> tuple[int, int, int, int]:
    rect = RECT()
    ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0)
    return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top


def _dpi_scale(hwnd: int) -> float:
    """返回窗口所在显示器的缩放比例（100% = 1.0）。"""
    try:
        dpi = int(ctypes.windll.user32.GetDpiForWindow(hwnd) or 0)
        if dpi > 0:
            return dpi / 96.0
    except Exception:
        pass
    return 1.0


def _force_foreground(hwnd: int) -> None:
    """绕过 Windows 前台锁，把窗口真正切到前台（语音输入依赖焦点）。"""
    if not hwnd:
        return
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
        user32.ShowWindow(hwnd, 9)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.SetFocus(hwnd)
        if attached:
            user32.AttachThreadInput(cur_tid, fg_tid, False)
    except OSError:
        pass


def _is_maximized(hwnd: int) -> bool:
    return bool(hwnd) and bool(ctypes.windll.user32.IsZoomed(hwnd))


def _ensure_on_screen(hwnd: int) -> None:
    """窗口完全不在工作区时移回中央，避免显示到屏幕外。"""
    if not hwnd:
        return
    wx, wy, ww, wh = _work_area()
    x, y, w, h = _window_rect(hwnd)
    if wx <= x and wy <= y and x + w <= wx + ww and y + h <= wy + wh:
        return
    user32 = ctypes.windll.user32
    try:
        if user32.IsZoomed(hwnd):
            user32.ShowWindow(hwnd, 9)
    except OSError:
        pass
    x = max(wx, min(x, wx + max(0, ww - w)))
    y = max(wy, min(y, wy + max(0, wh - h)))
    _move_window(hwnd, x, y)


def _round_window(hwnd: int, radius: int = 16) -> None:
    if not hwnd:
        return
    x, y, w, h = _window_rect(hwnd)
    try:
        dpi = ctypes.windll.user32.GetDpiForWindow(hwnd) or 96
    except OSError:
        dpi = 96
    r = max(2, int(radius * dpi / 96) * 2)
    try:
        region = ctypes.windll.gdi32.CreateRoundRectRgn(0, 0, w + 1, h + 1, r, r)
        ctypes.windll.user32.SetWindowRgn(hwnd, region, True)
    except OSError:
        pass


def _set_dwm_corners(hwnd: int, rounded: bool) -> None:
    """Windows 11 的 DWM 圆角在最大化/全屏时会露出白边，需要显式关闭。"""
    if not hwnd:
        return
    try:
        value = ctypes.c_int(2 if rounded else 1)  # ROUND / DONOTROUND
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 33, ctypes.byref(value), ctypes.sizeof(value)
        )
    except Exception:
        pass


def _hide_dwm_border(hwnd: int) -> None:
    """去掉 DWM 绘制的 1px 窗口边框，避免全屏边缘出现白线。"""
    if not hwnd:
        return
    try:
        value = ctypes.c_int(0xFFFFFFFE)  # DWMWA_COLOR_NONE
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 34, ctypes.byref(value), ctypes.sizeof(value)
        )
    except Exception:
        pass


def _parse_hotkey(text: str) -> tuple[int, int]:
    mods, vk = 0, 0x20
    names = {
        "space": 0x20, "enter": 0x0D, "tab": 0x09, "esc": 0x1B,
        "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75,
        "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
    }
    for part in (text or "").lower().replace(" ", "").split("+"):
        if part == "ctrl":
            mods |= MOD_CONTROL
        elif part == "alt":
            mods |= MOD_ALT
        elif part == "shift":
            mods |= MOD_SHIFT
        elif part in ("win", "meta"):
            mods |= MOD_WIN
        elif part in names:
            vk = names[part]
        elif len(part) == 1:
            vk = ord(part.upper())
    return mods, vk


class NexusApp:
    def __init__(self, config: Config, store: Store, safety: Safety,
                 registry: Registry, debug: bool = False):
        self.config = config
        self.store = store
        self.safety = safety
        self.registry = registry
        self.debug = debug
        set_language(config.get("ui.language"))
        self.updater = Updater(config)
        self.agent = Agent(config, store, safety, registry)
        self.scheduler = Scheduler(config, store, safety, registry)
        register_schedule_tools(registry, self.scheduler)
        self.scheduler.set_runner(self.run_scheduled_task)
        self.speech = SpeechRecognizer(config.dir, self._voice_progress)
        self.terminals = TerminalHub(self.push)
        self.embedded = BrowserHost(lambda: _hwnd(MAIN_TITLE))
        self._mic = None
        self._mic_chunks: list = []
        self._mic_lock = threading.Lock()
        self._voice_timer: threading.Timer | None = None
        self._voice_level = 0.0
        self._voice_bands: list[float] = []
        self._live_stop: threading.Event | None = None
        self._live_text = ""
        self._live_done = 0
        self._voice_token = 0
        self.glow = ScreenGlow(self._escape_control, block_input=True)
        self.orb_win = OrbWindow(
            ORB_SIZE, on_click=self._orb_clicked,
            on_menu=self._orb_menu_at, on_move_end=self._orb_moved,
        )
        self._orb_visible = False
        self._control_active = False
        self._control_prev = 0
        # 模型可通过 release_control 工具主动把控制权交还给用户
        desktop_tools.set_control_release(lambda: self._set_control(False))
        self.api = NexusApi(self)

        self.main: webview.Window | None = None
        self.orb: webview.Window | None = None
        self._loaded_main = False
        self._loaded_orb = False
        self._cancel: threading.Event | None = None
        self._running = False
        self._run_session_id: int | None = None
        self.perf = ResourceMonitor()
        self._pending: dict[str, dict] = {}
        self._pending_asks: dict[str, dict] = {}
        self._drag: dict[str, tuple] = {}
        self._hotkey_thread: threading.Thread | None = None
        self._hotkey_tid = 0
        self._tray = None
        self._quitting = False
        self._fullscreen = False
        self._lock = threading.Lock()
        self.quick: webview.Window | None = None
        self._loaded_quick = False
        self._quick_visible = False
        self._quick_capture = False
        self._quick_grace_until = 0.0
        self._voice_target = "main"
        self.onboarding: webview.Window | None = None
        self.whatsnew: webview.Window | None = None
        self._loaded_onboard = False
        self._loaded_whatsnew = False
        self._pending_onboard = False
        self._pending_whatsnew = False
        self._update_checking = False
        self._update_info: dict = {}

    # ---------------- 启动 ----------------
    def launch(self) -> int:
        try:
            # 固定 AppUserModelID，任务栏才会用我们自己的图标而不是 python.exe 的
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "Nexus.Desktop.AI"
            )
        except OSError:
            pass
        # 必须声明 argtypes，否则 64 位句柄参数可能被截断，DPI 感知会静默失败，
        # 导致悬浮球、提示条等窗口被系统放大后发虚。
        try:
            user32 = ctypes.windll.user32
            user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
            user32.SetProcessDpiAwarenessContext.restype = ctypes.c_bool
            if not user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
                raise OSError
        except (OSError, AttributeError):
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except (OSError, AttributeError):
                pass

        self.main = webview.create_window(
            MAIN_TITLE,
            url=str(WEB / "index.html"),
            js_api=self.api,
            width=460,
            height=700,
            frameless=True,
            easy_drag=False,
            resizable=True,
            on_top=False,
            hidden=True,
            background_color="#FFFFFF",
            text_select=True,
            shadow=True,
        )
        self.orb = webview.create_window(
            ORB_TITLE,
            url=str(WEB / "orb.html"),
            js_api=self.api,
            width=32,
            height=32,
            frameless=True,
            easy_drag=False,
            resizable=False,
            on_top=True,
            hidden=True,
            background_color="#FFFFFF",
            shadow=False,
            text_select=False,
            min_size=(96, 96),
        )
        self.main.events.loaded += self._on_main_loaded
        self.orb.events.loaded += self._on_orb_loaded
        self.main.events.closing += self._on_main_closing

        self.quick = webview.create_window(
            QUICK_TITLE,
            url=str(WEB / "quick.html"),
            js_api=self.api,
            width=420,
            height=132,
            frameless=True,
            easy_drag=True,
            resizable=False,
            on_top=True,
            hidden=True,
            background_color="#FFFFFF",
            shadow=True,
            text_select=True,
        )
        self.quick.events.loaded += self._on_quick_loaded

        self.onboarding = webview.create_window(
            ONBOARD_TITLE,
            url=str(WEB / "onboarding.html"),
            js_api=self.api,
            width=760,
            height=640,
            frameless=True,
            easy_drag=False,
            resizable=False,
            on_top=False,
            hidden=True,
            background_color="#FFFFFF",
            shadow=True,
            text_select=True,
        )
        self.onboarding.events.loaded += self._on_onboard_loaded
        self.onboarding.events.closing += self._on_onboard_closing

        self.whatsnew = webview.create_window(
            WHATSNEW_TITLE,
            url=str(WEB / "whatsnew.html"),
            js_api=self.api,
            width=680,
            height=580,
            frameless=True,
            easy_drag=False,
            resizable=False,
            on_top=False,
            hidden=True,
            background_color="#FFFFFF",
            shadow=True,
            text_select=True,
        )
        self.whatsnew.events.loaded += self._on_whatsnew_loaded
        self.whatsnew.events.closing += self._on_whatsnew_closing

        webview.start(
            self._after_start,
            gui="edgechromium",
            debug=self.debug,
            # 右侧栏的浏览器用于网站测试：每次启动都用全新的临时配置，
            # 不残留 Cookie / 缓存 / 登录态（设置 storage_path 会让私密模式失效）。
            private_mode=True,
        )
        return 0

    def _after_start(self) -> None:
        self._place_orb()
        self._place_main()
        self._start_hotkey()
        self._start_tray()
        self.glow.start()
        self.orb_win.start()
        self.scheduler.start(self._notify)
        version = self._version()
        onboarded = bool(self.config.get("ui.onboarded"))
        last_seen = str(self.config.get("ui.last_seen_version") or "")
        if not onboarded and not self.config.has_key():
            # 全新用户：先走独立引导，引导结束再打开主界面。
            threading.Timer(0.35, self.show_onboarding).start()
        else:
            show_notes = False
            if not onboarded:
                # 老用户已经配置过 Key，不再打扰引导，也不展示新功能页。
                self.config.set("ui.onboarded", True)
                self.config.set("ui.last_seen_version", version)
                self.config.save()
            elif last_seen != version:
                if last_seen:
                    # 已安装过旧版本：展示本次更新的功能页，关闭后再进主界面。
                    log.info("检测到版本更新：%s -> %s", last_seen, version)
                    show_notes = True
                else:
                    # 版本记录缺失时静默补齐，避免首次运行就弹窗。
                    self.config.set("ui.last_seen_version", version)
                    self.config.save()
            if show_notes:
                threading.Timer(0.6, self.show_whatsnew).start()
            else:
                self.show_orb()
        if self.config.get("update.auto_check", True) and self.updater.enabled():
            threading.Timer(7.0, self._auto_check_update).start()
        log.info("启动完成：onboarded=%s last_seen=%s", onboarded, last_seen)

    @staticmethod
    def _version() -> str:
        try:
            from app import __version__
        except Exception:
            __version__ = "0.0.0"
        return str(__version__)

    def _on_main_loaded(self) -> None:
        self._loaded_main = True
        info = self._update_info or {}
        if info.get("has_update") and not info.get("skipped"):
            # 自动检查可能早于主窗加载，加载完成后补发一次
            threading.Timer(1.0, lambda: self.push({"type": "update_available", "info": info})).start()
        threading.Timer(0.35, lambda: _round_window(_hwnd(MAIN_TITLE), 16)).start()
        threading.Timer(0.3, self._apply_icon).start()

    def _on_orb_loaded(self) -> None:
        self._loaded_orb = True
        threading.Timer(0.2, self._shape_orb).start()
        self._hide_from_taskbar(_hwnd(ORB_TITLE))
        threading.Timer(0.3, self._apply_icon).start()

    def _apply_icon(self) -> None:
        """给所有 pywebview 窗口换成 Nexus 自己的图标，避免任务栏显示 Python。"""
        try:
            from System.Drawing import Icon
            from webview.platforms import winforms as wf
        except Exception:
            return
        if not ICON_PATH.exists():
            return
        try:
            icon = Icon(str(ICON_PATH))
        except Exception:
            log.exception("读取应用图标失败")
            return
        for win in (self.main, self.orb, self.quick, self.onboarding, self.whatsnew):
            if not win:
                continue
            form = wf.BrowserView.instances.get(win.uid)
            if form is None:
                continue
            try:
                form.Icon = icon
            except Exception:
                log.debug("设置窗口图标失败", exc_info=True)

    def _hide_from_taskbar(self, hwnd: int) -> None:
        """悬浮球、快捷输入这类工具窗不占用任务栏按钮。"""
        if not hwnd:
            return
        try:
            user32 = ctypes.windll.user32
            user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
            user32.GetWindowLongW.restype = wintypes.LONG
            user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int,
                                              wintypes.LONG]
            user32.SetWindowLongW.restype = wintypes.LONG
            style = int(user32.GetWindowLongW(hwnd, -20))
            # 同时去掉 APPWINDOW、加上 TOOLWINDOW，确保不生成任务栏按钮
            user32.SetWindowLongW(hwnd, -20, (style | 0x00000080) & ~0x00040000)
        except OSError:
            pass

    def _on_main_closing(self) -> bool:
        if self._quitting:
            return True
        self.main.hide()
        self.show_orb()
        return False

    # ---------------- 窗口 ----------------
    def _shape_orb(self) -> None:
        """把悬浮球窗口裁成圆形，避免依赖 WebView2 透明。"""
        hwnd = _hwnd(ORB_TITLE)
        if not hwnd:
            return
        _, _, w, h = _window_rect(hwnd)
        if w <= 0 or h <= 0:
            return
        try:
            region = ctypes.windll.gdi32.CreateEllipticRgn(0, 0, w + 1, h + 1)
            ctypes.windll.user32.SetWindowRgn(hwnd, region, True)
        except OSError:
            pass

    def _fix_orb_size(self) -> None:
        """用 WinForms 把悬浮球窗口强制改成正方形（按 DPI 换算为物理像素）。"""
        if not self.orb:
            return
        try:
            from System import Action
            from System.Drawing import Size
            from webview.platforms import winforms as wf
        except Exception:
            return
        form = wf.BrowserView.instances.get(self.orb.uid)
        if form is None:
            return

        def apply() -> None:
            try:
                # 只解除 pywebview 的 min_size 限制；尺寸统一交给 SetWindowPos，
                # 避免 WinForms 在 DPI 自动缩放时按逻辑像素二次换算导致窗口变小。
                form.MinimumSize = Size(0, 0)
            except Exception:
                log.exception("设置悬浮球窗口尺寸失败")

        try:
            form.Invoke(Action(apply))
        except Exception:
            log.exception("悬浮球窗口线程调用失败")

    def _place_orb(self, retry: int = 0) -> None:
        hwnd = _hwnd(ORB_TITLE)
        if not hwnd:
            threading.Timer(0.4, self._place_orb).start()
            return
        self._fix_orb_size()
        # 直接按 DPI 设置窗口物理尺寸，避免被上一次的外框尺寸覆盖
        side = max(24, int(round(ORB_SIZE * _dpi_scale(hwnd))))
        saved = self.config.get("ui.orb_pos") or []
        wx, wy, ww, wh = _work_area()
        if isinstance(saved, list) and len(saved) == 2:
            x, y = int(saved[0]), int(saved[1])
        else:
            x = wx + ww - side - 20
            y = wy + int(wh * 0.55)
        x = max(wx, min(x, wx + ww - side))
        y = max(wy, min(y, wy + wh - side))
        set_window_pos(hwnd, 0, x, y, side, side,
                       SWP_NOZORDER | SWP_NOACTIVATE)
        self._shape_orb()
        # WebView2 加载完成后可能按自己的初始尺寸重排一次，延后补偿一轮
        if retry < 1:
            threading.Timer(1.6, lambda: self._place_orb(retry + 1)).start()

    def _place_main(self) -> None:
        hwnd = _hwnd(MAIN_TITLE)
        if not hwnd:
            threading.Timer(0.4, self._place_main).start()
            return
        if self._fullscreen or _is_maximized(hwnd):
            return
        saved = self.config.get("ui.win_pos") or []
        wx, wy, ww, wh = _work_area()
        _, _, mw, mh = _window_rect(hwnd)
        x = y = None
        if isinstance(saved, list) and len(saved) == 2:
            sx, sy = int(saved[0]), int(saved[1])
            # 保存的位置若让窗口大部分落在工作区外，则丢弃，避免窗口"消失"在屏幕外
            if (wx <= sx + mw / 2 <= wx + ww) and (wy <= sy + mh / 2 <= wy + wh):
                x, y = sx, sy
        if x is None:
            x = wx + ww - mw - 28
            y = wy + wh - mh - 28
        x = max(wx, min(x, wx + ww - mw))
        y = max(wy, min(y, wy + wh - mh))
        _move_window(hwnd, x, y)

    def show_main(self) -> None:
        self.hide_quick()
        for win in (self.onboarding, self.whatsnew):
            try:
                if win:
                    log.info("显示主窗时隐藏设置窗口")
                    win.hide()
            except Exception:
                pass
        try:
            if self.orb:
                self.orb.hide()
        except Exception:
            pass
        self.orb_win.hide()
        self._orb_visible = False
        hwnd = _hwnd(MAIN_TITLE)
        try:
            self.main.show()
            if hwnd and ctypes.windll.user32.IsIconic(hwnd):
                self.main.restore()
        except Exception:
            pass
        log.info("显示主窗口 hwnd=%s", hwnd)
        self._place_main()
        if hwnd:
            _ensure_on_screen(hwnd)
            _force_foreground(hwnd)
            # 窗口刚 show 时 WebView2 可能还没完成布局，稍后再校正一次位置
            threading.Timer(0.45, lambda: _ensure_on_screen(_hwnd(MAIN_TITLE))).start()
            threading.Timer(1.1, lambda: _ensure_on_screen(_hwnd(MAIN_TITLE))).start()

    def _orb_pos(self) -> tuple[int, int]:
        try:
            scale = float(ctypes.windll.user32.GetDpiForSystem() or 96) / 96.0
        except OSError:
            scale = 1.0
        side = max(24, int(round(ORB_SIZE * scale)))
        wx, wy, ww, wh = _work_area()
        saved = self.config.get("ui.orb_pos") or []
        if isinstance(saved, list) and len(saved) == 2:
            x, y = int(saved[0]), int(saved[1])
        else:
            x = wx + ww - side - 20
            y = wy + int(wh * 0.55)
        x = max(wx, min(x, wx + ww - side))
        y = max(wy, min(y, wy + wh - side))
        return x, y

    def show_orb(self) -> None:
        try:
            if self.main:
                self.main.hide()
        except Exception:
            pass
        for win in (self.onboarding, self.whatsnew):
            try:
                if win:
                    win.hide()
            except Exception:
                pass
        self._orb_visible = True
        # 桌面宠物已移除，悬浮球统一由原生 OrbWindow 渲染。
        try:
            if self.orb:
                self.orb.hide()
        except Exception:
            pass
        x, y = self._orb_pos()
        self.orb_win.show_at(x, y)

    def _orb_moved(self, x: int, y: int) -> None:
        self.config.set("ui.orb_pos", [int(x), int(y)])
        self.config.save()

    def _orb_menu_at(self, x: int, y: int) -> dict:
        """分层悬浮球右键：用自身窗口句柄作为菜单 owner。"""
        try:
            cmd = self._popup_orb_menu(int(x), int(y), self.orb_win.hwnd())
        except Exception:
            log.exception("悬浮球菜单弹出失败")
            return {"ok": False, "error": "菜单不可用"}
        return self._run_orb_menu(int(cmd or 0))

    # ---------------- 快捷输入浮窗 ----------------
    def _on_quick_loaded(self) -> None:
        self._loaded_quick = True
        self._hide_from_taskbar(_hwnd(QUICK_TITLE))
        threading.Timer(0.3, self._apply_icon).start()

    # ---------------- 首次引导 / 新功能 ----------------
    def _on_onboard_loaded(self) -> None:
        self._loaded_onboard = True
        log.info("引导窗口已加载，pending=%s", self._pending_onboard)
        threading.Timer(0.3, self._apply_icon).start()
        if self._pending_onboard:
            self.show_onboarding()

    def _on_whatsnew_loaded(self) -> None:
        self._loaded_whatsnew = True
        threading.Timer(0.3, self._apply_icon).start()
        if self._pending_whatsnew:
            self.show_whatsnew()

    def _on_onboard_closing(self) -> bool:
        log.info("引导窗口 closing 事件，quitting=%s", self._quitting)
        if self._quitting:
            return True
        try:
            self.onboarding.hide()
        except Exception:
            pass
        # 直接关闭引导视为跳过，进入主界面。
        self.config.set("ui.onboarded", True)
        self.config.set("ui.last_seen_version", self._version())
        self.config.save()
        self.show_main()
        return False

    def _on_whatsnew_closing(self) -> bool:
        if self._quitting:
            return True
        try:
            self.whatsnew.hide()
        except Exception:
            pass
        self.config.set("ui.last_seen_version", self._version())
        self.config.save()
        self.show_main()
        return False

    def _center_and_show(self, win, title: str, attempt: int = 0) -> None:
        if not win:
            return
        try:
            win.show()
        except Exception:
            pass
        hwnd = _hwnd(title)
        visible = bool(hwnd) and bool(ctypes.windll.user32.IsWindowVisible(hwnd))
        if not visible:
            log.info("设置窗口暂不可见：%s attempt=%s", title, attempt)
            if attempt < 20:
                threading.Timer(
                    0.25, lambda: self._center_and_show(win, title, attempt + 1)
                ).start()
            elif title == ONBOARD_TITLE:
                # 极端情况下引导窗口无法显示，退回主界面，避免进程无可见窗口。
                self.show_main()
            return

        def place() -> None:
            hwnd2 = _hwnd(title)
            if not hwnd2:
                return
            _, _, w, h = _window_rect(hwnd2)
            wx, wy, ww, wh = _work_area()
            _move_window(hwnd2, wx + max(0, (ww - w) // 2), wy + max(0, (wh - h) // 2))
            _raise_window(hwnd2)

        place()
        threading.Timer(0.3, place).start()

    def _hide_setup_windows(self) -> None:
        log.info("隐藏主窗/悬浮球（设置窗口已显示）")
        for win in (self.main, self.orb):
            try:
                if win:
                    win.hide()
            except Exception:
                pass
        self.orb_win.hide()
        self._orb_visible = False

    def show_onboarding(self) -> None:
        if not self._loaded_onboard:
            self._pending_onboard = True
            log.info("引导窗口尚未加载，等待 loaded 事件")
            return
        self._pending_onboard = False
        log.info("显示引导窗口")
        self.hide_quick()
        self._center_and_show(self.onboarding, ONBOARD_TITLE)
        threading.Timer(0.45, self._hide_setup_windows).start()

    def show_whatsnew(self) -> None:
        if not self._loaded_whatsnew:
            self._pending_whatsnew = True
            return
        self._pending_whatsnew = False
        self.hide_quick()
        self._center_and_show(self.whatsnew, WHATSNEW_TITLE)
        threading.Timer(0.45, self._hide_setup_windows).start()

    def _orb_clicked(self) -> None:
        if self._quick_visible:
            self.hide_quick()
        else:
            self.show_quick()

    def show_quick(self) -> None:
        if not self.quick:
            return
        try:
            self.quick.show()
        except Exception:
            pass
        self._quick_visible = True
        hwnd = _hwnd(QUICK_TITLE)
        if hwnd:
            _, _, w, h = _window_rect(hwnd)
            x, y = self._quick_pos(w, h)
            _move_window(hwnd, x, y)
            _force_foreground(hwnd)
        self._quick_grace_until = time.time() + 0.8
        threading.Thread(target=self._quick_watch, daemon=True,
                         name="nexus-quick-watch").start()
        try:
            self.quick.evaluate_js("window.NexusQuick && window.NexusQuick.focus()")
        except Exception:
            pass

    def _quick_pos(self, w: int, h: int) -> tuple[int, int]:
        """放在悬浮球左侧；左边放不下就放右侧，并夹在工作区内。"""
        orb = self.orb_win.hwnd()
        ox, oy, ow, oh = _window_rect(orb) if orb else (0, 0, 0, 0)
        wx, wy, ww, wh = _work_area()
        x = ox - w - 12
        if x < wx:
            x = ox + ow + 12
        x = max(wx, min(x, wx + ww - w))
        y = oy + oh - h
        y = max(wy, min(y, wy + wh - h))
        return int(x), int(y)

    def hide_quick(self) -> None:
        if not self._quick_visible:
            return
        if self._voice_target == "quick":
            self.cancel_voice()
        self._quick_visible = False
        try:
            if self.quick:
                self.quick.hide()
        except Exception:
            pass

    def _quick_watch(self) -> None:
        """点击浮窗以外的区域时自动收起。"""
        time.sleep(0.35)
        while self._quick_visible:
            if self._quick_capture or time.time() < self._quick_grace_until:
                time.sleep(0.05)
                continue
            try:
                fg = int(ctypes.windll.user32.GetForegroundWindow() or 0)
            except OSError:
                fg = 0
            targets = (_hwnd(QUICK_TITLE), self.orb_win.hwnd())
            if fg and fg not in targets:
                self.hide_quick()
                break
            time.sleep(0.18)

    # ---------------- 悬浮球快捷菜单 ----------------
    def _orb_menu(self, payload: dict | None = None) -> dict:
        """在悬浮球上右键弹出原生快捷菜单，不打开主界面。"""
        payload = payload or {}
        try:
            from System import Action
            from webview.platforms import winforms as wf
        except Exception:
            return {"ok": False, "error": "菜单不可用"}
        form = wf.BrowserView.instances.get(self.orb.uid) if self.orb else None
        if form is None:
            return {"ok": False, "error": "悬浮球未就绪"}
        x = int(payload.get("x") or 0)
        y = int(payload.get("y") or 0)
        picked = {"cmd": 0}
        try:
            handle = form.Handle.ToInt64() if hasattr(form.Handle, "ToInt64") else int(form.Handle)
        except Exception:
            return {"ok": False, "error": "无法读取窗口句柄"}

        def show() -> None:
            picked["cmd"] = self._popup_orb_menu(x, y, handle)

        try:
            form.Invoke(Action(show))
        except Exception as e:
            log.exception("悬浮球菜单弹出失败")
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
        return self._run_orb_menu(int(picked["cmd"] or 0))

    def _popup_orb_menu(self, x: int, y: int, owner: int) -> int:
        """弹出快捷菜单并返回选中的命令号。"""
        user32 = ctypes.windll.user32
        user32.CreatePopupMenu.restype = ctypes.c_void_p
        user32.AppendMenuW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                       ctypes.c_size_t, ctypes.c_wchar_p]
        user32.AppendMenuW.restype = ctypes.c_bool
        user32.TrackPopupMenu.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int,
                                          ctypes.c_int, ctypes.c_int,
                                          ctypes.c_void_p, ctypes.c_void_p]
        user32.TrackPopupMenu.restype = ctypes.c_int
        user32.DestroyMenu.argtypes = [ctypes.c_void_p]
        mode = str(self.config.get("mode") or "supervised")
        hmenu = user32.CreatePopupMenu()
        if not hmenu:
            return 0
        try:
            def add(text: str, cid: int, flag: int = 0) -> None:
                user32.AppendMenuW(hmenu, 0x0000 | flag, cid, text)

            add("打开主界面", 1)
            user32.AppendMenuW(hmenu, 0x0800, 0, None)
            add("安全模式（只读）", 6, 0x0008 if mode == "safe" else 0)
            add("监管模式（命令需确认）", 7, 0x0008 if mode == "supervised" else 0)
            add("全部下放（自主执行）", 8, 0x0008 if mode == "full" else 0)
            user32.AppendMenuW(hmenu, 0x0800, 0, None)
            add("隐藏悬浮球", 9)
            add("退出 Nexus", 10)
            user32.SetForegroundWindow(owner)
            cmd = int(user32.TrackPopupMenu(
                hmenu, 0x0100 | 0x0002, x, y, 0, owner, None
            ))
            user32.PostMessageW(owner, 0x0000, 0, 0)
            return cmd
        finally:
            user32.DestroyMenu(hmenu)

    def _run_orb_menu(self, cmd: int) -> dict:
        if cmd == 1:
            self.show_main()
        elif cmd in (6, 7, 8):
            mode = {6: "safe", 7: "supervised", 8: "full"}[cmd]
            self.api.settings_save({"mode": mode})
            self.push({"type": "notify", "title": "Nexus",
                       "message": "已切换到" + {"safe": "安全模式",
                                                "supervised": "监管模式",
                                                "full": "全部下放"}[mode]})
        elif cmd == 9:
            try:
                self.orb.hide()
            except Exception:
                pass
            self.orb_win.hide()
            self._orb_visible = False
        elif cmd == 10:
            self.quit()
        return {"ok": True, "cmd": cmd}

    def _capture_for_main(self, region: bool) -> None:
        """从悬浮球截图，并把结果送到主界面附件栏。"""
        try:
            res = self.api.capture_screen({"mode": "region"} if region else None)
        except Exception:
            log.exception("悬浮球截图失败")
            return
        if not res or not res.get("ok"):
            return
        self.show_main()
        self.push({
            "type": "attach_image",
            "base64": res.get("base64") or "",
            "data_url": res.get("data_url") or "",
        })

    def _capture_for_quick(self) -> None:
        """快捷浮窗截图：先隐藏浮窗避免拍到它，完成后把缩略图回填到浮窗。"""
        try:
            if self._voice_target == "quick":
                self.cancel_voice()
            try:
                if self.quick:
                    self.quick.hide()
            except Exception:
                pass
            time.sleep(0.18)
            res = self.api.capture_screen(None)
        except Exception:
            log.exception("快捷浮窗截图失败")
            res = None
        finally:
            try:
                if self.quick and self._quick_visible:
                    self.quick.show()
                    time.sleep(0.15)
                    hwnd = _hwnd(QUICK_TITLE)
                    if hwnd:
                        _, _, w, h = _window_rect(hwnd)
                        x, y = self._quick_pos(w, h)
                        _move_window(hwnd, x, y)
                        _force_foreground(hwnd)
                    self._quick_grace_until = time.time() + 0.9
                    self.quick.evaluate_js(
                        "window.NexusQuick && window.NexusQuick.focus()")
            except Exception:
                log.debug("恢复快捷浮窗失败", exc_info=True)
            self._quick_capture = False
        if res and res.get("ok"):
            self.push({
                "type": "quick_shot",
                "base64": res.get("base64") or "",
                "data_url": res.get("data_url") or "",
            })
        else:
            self.push({
                "type": "quick_toast",
                "text": (res or {}).get("error") or "截图失败",
            })

    def hide_main(self) -> None:
        if self._fullscreen:
            self.toggle_fullscreen_main()
        try:
            self.main.hide()
        except Exception:
            pass
        self.show_orb()

    def minimize_main(self) -> None:
        if self._fullscreen:
            self.toggle_fullscreen_main()
        try:
            self.main.minimize()
        except Exception:
            pass

    def toggle_maximize_main(self) -> None:
        hwnd = _hwnd(MAIN_TITLE)
        if not hwnd:
            return
        user32 = ctypes.windll.user32
        if _is_maximized(hwnd):
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            _set_dwm_corners(hwnd, True)
            threading.Timer(0.25, lambda: _round_window(hwnd, 16)).start()
        else:
            if self._fullscreen:
                self.toggle_fullscreen_main()
            self._paint_window_frame()
            # 无边框窗口直接 SW_MAXIMIZE 会盖住任务栏，先限定最大化边界到工作区
            self._fit_maximized_bounds()
            _set_dwm_corners(hwnd, False)
            _hide_dwm_border(hwnd)
            user32.SetWindowRgn(hwnd, None, True)  # 最大化时去掉圆角裁切
            user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE

    def _paint_window_frame(self) -> None:
        """让窗口底色跟随主题，避免最大化/全屏时四角露出白边。"""
        try:
            from System import Action
            from System.Drawing import Color
            from webview.platforms import winforms as wf
        except Exception:
            return
        form = wf.BrowserView.instances.get(self.main.uid) if self.main else None
        if form is None:
            return
        dark = str(self.config.get("ui.theme") or "light") == "dark"
        color = Color.FromArgb(21, 21, 23) if dark else Color.White

        def apply() -> None:
            try:
                form.BackColor = color
                form.Region = None
            except Exception:
                pass

        try:
            form.Invoke(Action(apply))
        except Exception:
            log.debug("设置窗口底色失败", exc_info=True)

    def _fit_maximized_bounds(self) -> None:
        """把无边框窗口的最大化边界限制在任务栏上方的工作区。"""
        try:
            from System import Action
            from System.Drawing import Rectangle
            from System.Windows.Forms import Screen
            from webview.platforms import winforms as wf
        except Exception:
            log.debug("无法导入 WinForms，跳过多显示器最大化边界", exc_info=True)
            return
        form = wf.BrowserView.instances.get(self.main.uid) if self.main else None
        if form is None:
            return

        def apply() -> None:
            try:
                work = Screen.FromHandle(form.Handle).WorkingArea
                form.MaximizedBounds = Rectangle(work.X, work.Y, work.Width, work.Height)
            except Exception:
                log.exception("设置最大化边界失败")

        try:
            form.Invoke(Action(apply))
        except Exception:
            log.exception("设置最大化边界失败")

    def toggle_fullscreen_main(self) -> None:
        if not self.main:
            return
        self._fullscreen = not self._fullscreen
        self._apply_fullscreen(self._fullscreen)
        hwnd = _hwnd(MAIN_TITLE)
        if self._fullscreen:
            if hwnd:
                ctypes.windll.user32.SetWindowRgn(hwnd, None, True)
                _set_dwm_corners(hwnd, False)
        else:
            if hwnd:
                _set_dwm_corners(hwnd, True)
            threading.Timer(0.35, lambda: _round_window(hwnd, 16)).start()

    def _apply_fullscreen(self, enable: bool) -> None:
        """真正的全屏：铺满当前显示器的工作区，Windows 任务栏保持可见。"""
        try:
            from System import Action
            from System.Drawing import Rectangle
            from System.Windows.Forms import FormWindowState, Screen
            from webview.platforms import winforms as wf
        except Exception:
            try:
                self.main.toggle_fullscreen()
            except Exception:
                log.exception("切换全屏失败")
            return
        form = wf.BrowserView.instances.get(self.main.uid)
        if form is None:
            try:
                self.main.toggle_fullscreen()
            except Exception:
                log.exception("切换全屏失败")
            return

        def apply() -> None:
            try:
                from System.Drawing import Color

                handle = form.Handle
                handle_value = handle.ToInt64() if hasattr(handle, "ToInt64") else int(handle)
                dark = str(self.config.get("ui.theme") or "light") == "dark"
                form.BackColor = Color.FromArgb(21, 21, 23) if dark else Color.White
                form.Region = None
                ctypes.windll.user32.SetWindowRgn(handle_value, None, True)
                _set_dwm_corners(handle_value, not enable)
                _hide_dwm_border(handle_value)
                if enable:
                    self._fs_rect = (form.Left, form.Top, form.Width, form.Height)
                    self._fs_max = form.WindowState == FormWindowState.Maximized
                    self._fs_top = bool(form.TopMost)
                    screen = Screen.FromHandle(handle)
                    bounds = screen.WorkingArea
                    # 退出时若恢复到最大化，也要受工作区边界约束
                    form.MaximizedBounds = Rectangle(
                        bounds.X, bounds.Y, bounds.Width, bounds.Height
                    )
                    form.WindowState = FormWindowState.Normal
                    form.Bounds = Rectangle(bounds.X, bounds.Y, bounds.Width, bounds.Height)
                    form.TopMost = True
                    form.BringToFront()
                    _force_foreground(_hwnd(MAIN_TITLE))
                else:
                    form.TopMost = bool(getattr(self, "_fs_top", False))
                    if getattr(self, "_fs_max", False):
                        form.WindowState = FormWindowState.Maximized
                    else:
                        form.WindowState = FormWindowState.Normal
                        rect = getattr(self, "_fs_rect", None)
                        if rect:
                            form.Bounds = Rectangle(*rect)
            except Exception:
                log.exception("应用全屏尺寸失败")

        try:
            form.Invoke(Action(apply))
        except Exception:
            log.exception("全屏窗口线程调用失败")

    def save_positions(self) -> None:
        for key, title in (("ui.win_pos", MAIN_TITLE), ("ui.orb_pos", ORB_TITLE)):
            hwnd = _hwnd(title)
            if not hwnd:
                continue
            if key == "ui.win_pos" and (self._fullscreen or _is_maximized(hwnd)):
                continue
            if key == "ui.orb_pos" and self._orb_visible:
                # 分层悬浮球的位置在拖动结束时已经保存，这里跳过隐藏的 WebView 窗口
                continue
            x, y, _, _ = _window_rect(hwnd)
            self.config.set(key, [x, y])
        self.config.save()

    # ---------------- 拖动 ----------------
    def drag_start(self, which: str) -> None:
        title = ORB_TITLE if which == "orb" else MAIN_TITLE
        hwnd = _hwnd(title)
        if not hwnd:
            return
        if which == "main" and _is_maximized(hwnd):
            return
        x, y, _, _ = _window_rect(hwnd)
        cx, cy = _cursor()
        self._drag[which] = (hwnd, x - cx, y - cy)

    def drag_move(self, which: str) -> None:
        item = self._drag.get(which)
        if not item:
            return
        hwnd, ox, oy = item
        cx, cy = _cursor()
        _move_window(hwnd, cx + ox, cy + oy)

    def drag_end(self, which: str) -> None:
        item = self._drag.pop(which, None)
        if not item:
            return
        hwnd, _, _ = item
        if which == "orb":
            x, y, w, h = _window_rect(hwnd)
            wx, wy, ww, wh = _work_area()
            if x - wx < 30:
                x = wx + 8
            elif wx + ww - (x + w) < 30:
                x = wx + ww - w - 8
            y = max(wy, min(y, wy + wh - h))
            _move_window(hwnd, x, y)
        self.save_positions()

    # ---------------- 热键 ----------------
    def _start_hotkey(self) -> None:
        self._stop_hotkey()
        hotkey = self.config.get("ui.hotkey") or "ctrl+alt+space"
        mods, vk = _parse_hotkey(hotkey)
        voice_hotkey = self.config.get("ui.voice_hotkey") or "ctrl+alt+v"
        v_mods, v_vk = _parse_hotkey(voice_hotkey)
        same = (mods, vk) == (v_mods, v_vk)

        def loop():
            self._hotkey_tid = ctypes.windll.kernel32.GetCurrentThreadId()
            user32 = ctypes.windll.user32
            registered = []
            if user32.RegisterHotKey(None, 1, mods, vk):
                registered.append(1)
            else:
                log.warning("全局热键注册失败：%s", hotkey)
            if not same and user32.RegisterHotKey(None, 2, v_mods, v_vk):
                registered.append(2)
            elif not same:
                log.warning("语音热键注册失败：%s", voice_hotkey)
            msg = wintypes.MSG()
            try:
                while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
                    if msg.message == WM_HOTKEY:
                        if msg.wParam == 1:
                            self.show_main()
                        elif msg.wParam == 2:
                            self.start_voice()
            finally:
                for hotkey_id in registered:
                    user32.UnregisterHotKey(None, hotkey_id)

        self._hotkey_thread = threading.Thread(target=loop, daemon=True, name="nexus-hotkey")
        self._hotkey_thread.start()

    def start_voice(self) -> None:
        """本地语音输入：首次按下开始录音，再次按下结束并识别。"""
        self.toggle_voice()

    def _voice_progress(self, percent: int, text: str) -> None:
        last = getattr(self, "_voice_progress_last", None)
        if last and last[0] == text and percent - last[1] < 5 and percent < 100:
            return
        self._voice_progress_last = (text, percent)
        self.push({"type": "voice_state", "downloading": True,
                   "percent": percent, "text": text})

    def _start_recording(self) -> bool:
        try:
            import sounddevice as sd
        except ImportError:
            log.warning("未安装 sounddevice，无法录音")
            return False
        self._mic_chunks = []
        self._voice_level = 0.0
        self._voice_bands = [0.0] * 9
        self._live_text = ""
        self._live_done = 0
        self._live_stop = threading.Event()
        self._voice_token += 1
        token = self._voice_token

        def callback(indata, frames, time_info, status):
            with self._mic_lock:
                self._mic_chunks.append(indata.copy())
            try:
                import numpy as np
                rms = float((indata * indata).mean() ** 0.5)
                self._voice_level = min(1.0, (rms * 14.0) ** 0.8)
                mono = indata.reshape(-1)
                spec = np.abs(np.fft.rfft(mono * np.hanning(len(mono))))
                freqs = np.fft.rfftfreq(len(mono), 1 / 16000)
                edges = np.geomspace(90, 7600, 10)
                bands = []
                for i in range(9):
                    mask = (freqs >= edges[i]) & (freqs < edges[i + 1])
                    if mask.any():
                        val = float(spec[mask].mean())
                        bands.append(min(1.0, (val / 5.0) ** 0.7))
                    else:
                        bands.append(0.0)
                self._voice_bands = bands
            except Exception:
                pass

        try:
            self._mic = sd.InputStream(samplerate=16000, channels=1, dtype="float32",
                                       callback=callback, blocksize=1024)
            self._mic.start()
        except Exception:
            log.exception("启动麦克风失败")
            self._mic = None
            return False
        threading.Thread(target=self._live_asr_loop, args=(token,), daemon=True,
                         name="nexus-asr-live").start()
        threading.Thread(target=self._meter_loop, daemon=True,
                         name="nexus-mic-meter").start()
        return True

    def _stop_recording(self):
        if self._live_stop is not None:
            self._live_stop.set()
        mic, self._mic = self._mic, None
        if mic is not None:
            try:
                mic.stop()
                mic.close()
            except Exception:
                pass
        try:
            import numpy as np
        except ImportError:
            return None
        with self._mic_lock:
            chunks = list(self._mic_chunks)
            self._mic_chunks = []
        if not chunks:
            return None
        return np.concatenate(chunks, axis=0).reshape(-1)

    def _live_asr_loop(self, token: int) -> None:
        """录音期间每 1.4 秒识别新增片段，把临时结果实时显示在输入框。"""
        try:
            import numpy as np
        except ImportError:
            return
        stop = self._live_stop
        if stop is None:
            return
        while not stop.wait(1.4):
            if self._mic is None or token != self._voice_token:
                return
            with self._mic_lock:
                chunks = list(self._mic_chunks)
            if not chunks:
                continue
            try:
                samples = np.concatenate(chunks, axis=0).reshape(-1)
            except Exception:
                continue
            pending = samples[self._live_done:]
            if len(pending) < 12000:
                continue
            try:
                text = self.speech.recognize(pending)
            except Exception:
                text = ""
                log.debug("实时语音识别失败", exc_info=True)
            self._live_done = len(samples)
            if text and token == self._voice_token:
                self._live_text = (self._live_text + text).strip()
                self.push({"type": "voice_partial", "text": self._live_text,
                           "target": self._voice_target})

    def _meter_loop(self) -> None:
        while self._mic is not None:
            self.push({"type": "voice_level",
                       "level": round(float(getattr(self, "_voice_level", 0.0)), 3),
                       "bands": [round(float(v), 3) for v in getattr(self, "_voice_bands", [])]})
            time.sleep(0.08)

    def cancel_voice(self) -> bool:
        """停止并丢弃当前录音（关闭快捷浮窗或切到主界面时调用）。"""
        active = self._mic is not None or self._voice_timer is not None
        if self._voice_timer is not None:
            self._voice_timer.cancel()
            self._voice_timer = None
        self._voice_token += 1
        if self._mic is not None:
            self._stop_recording()
        elif self._live_stop is not None:
            self._live_stop.set()
        if active:
            self.push({"type": "voice_state", "recording": False,
                       "cancelled": True, "target": self._voice_target})
        return active

    def toggle_voice(self, show: bool = True) -> dict:
        if self._mic is not None:
            if self._voice_timer is not None:
                self._voice_timer.cancel()
                self._voice_timer = None
            samples = self._stop_recording()
            token = self._voice_token
            self.push({"type": "voice_state", "recording": False, "busy": True,
                       "target": self._voice_target})
            if samples is None or len(samples) < 1600:
                self.push({"type": "voice_state", "recording": False, "empty": True,
                           "target": self._voice_target})
                return {"ok": False, "error": "没有录到声音"}
            threading.Thread(target=self._recognize_voice, args=(samples, token),
                             daemon=True, name="nexus-asr").start()
            return {"ok": True, "recording": False}
        if not self.speech.ready():
            if self.speech.downloading():
                return {"ok": False, "error": "语音模型正在下载，请稍候"}
            threading.Thread(target=self._prepare_speech, daemon=True,
                             name="nexus-asr-download").start()
            return {"ok": False,
                    "error": "语音模型尚未下载，已开始下载，请稍候"}
        self._voice_target = "main" if show else "quick"
        if show:
            main_hwnd = _hwnd(MAIN_TITLE)
            if main_hwnd and ctypes.windll.user32.IsWindowVisible(main_hwnd):
                _force_foreground(main_hwnd)
            else:
                self.show_main()
        if not self._start_recording():
            self.push({"type": "voice_state", "recording": False,
                       "error": "无法启动麦克风", "target": self._voice_target})
            return {"ok": False, "error": "无法启动麦克风，请检查系统麦克风权限"}
        self.push({"type": "voice_state", "recording": True,
                   "target": self._voice_target})
        self._voice_timer = threading.Timer(60.0, self.toggle_voice)
        self._voice_timer.daemon = True
        self._voice_timer.start()
        return {"ok": True, "recording": True}

    def _prepare_speech(self) -> None:
        ok = self.speech.ensure_model()
        self.push({"type": "voice_state", "recording": False, "ready": bool(ok)})

    def _recognize_voice(self, samples, token: int) -> None:
        try:
            text = self.speech.recognize(samples)
        except Exception:
            log.exception("语音识别失败")
            text = ""
        if token != self._voice_token:
            return
        if text:
            self.push({"type": "voice_result", "text": text,
                       "target": self._voice_target})
            self.push({"type": "voice_state", "recording": False,
                       "target": self._voice_target})
        else:
            self.push({"type": "voice_state", "recording": False, "empty": True,
                       "target": self._voice_target})

    def _stop_hotkey(self) -> None:
        if self._hotkey_thread and self._hotkey_thread.is_alive() and self._hotkey_tid:
            try:
                ctypes.windll.user32.PostThreadMessageW(self._hotkey_tid, WM_QUIT, 0, 0)
            except OSError:
                pass
            self._hotkey_tid = 0
            self._hotkey_thread = None

    # ---------------- 托盘 ----------------
    def _start_tray(self) -> None:
        try:
            import pystray
            from PIL import Image, ImageDraw
        except ImportError:
            log.info("未安装托盘组件，跳过托盘")
            return

        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse((4, 4, 60, 60), fill="white", outline="black", width=3)
        draw.ellipse((40, 40, 54, 54), fill="#4176E6")

        menu = pystray.Menu(
            pystray.MenuItem(t("打开对话", "Open Nexus"), lambda: self.show_main(), default=True),
            pystray.MenuItem(t("语音输入", "Voice input"), lambda: self.start_voice()),
            pystray.MenuItem(t("显示悬浮球", "Show floating orb"), lambda: self.show_orb()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(t("退出 Nexus", "Quit Nexus"), lambda: self.quit()),
        )
        self._tray = pystray.Icon("Nexus", img, t("Nexus 桌面助手", "Nexus Desktop Assistant"), menu)
        threading.Thread(target=self._tray.run, daemon=True, name="nexus-tray").start()

    def _rebuild_tray(self) -> None:
        """语言切换后重建托盘菜单。"""
        tray = self._tray
        if tray is None:
            return
        self._tray = None
        try:
            tray.stop()
        except Exception:
            log.debug("旧托盘停止失败", exc_info=True)
        threading.Timer(0.25, self._start_tray).start()

    def quit(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        self.cancel_voice()
        self.terminals.close_all()
        self.embedded.close_all()
        self.scheduler.stop()
        self._stop_hotkey()
        self.save_positions()
        self.glow.close()
        self.orb_win.close()
        # 快捷输入窗也必须销毁，否则 pywebview 主循环不会退出，任务管理器会残留进程。
        for win in (self.quick, self.orb, self.main, self.onboarding, self.whatsnew):
            try:
                if win:
                    win.destroy()
            except Exception:
                pass
        # 兜底：若 WebView2 或托盘线程未及时释放，2.5 秒后强制退出。
        threading.Timer(2.5, lambda: os._exit(0)).start()
        if self._tray:
            threading.Thread(target=self._stop_tray, daemon=True,
                             name="nexus-tray-stop").start()

    def _stop_tray(self) -> None:
        try:
            if self._tray:
                self._tray.stop()
        except Exception:
            log.debug("托盘停止失败", exc_info=True)

    # ---------------- 事件 ----------------
    def _notify(self, title: str, message: str) -> None:
        title = (title or "Nexus")[:60]
        message = (message or "")[:500]
        self.push({"type": "notify", "title": title, "message": message})
        try:
            if self._tray is not None:
                self._tray.notify(message, title)
        except Exception:
            log.debug("托盘通知失败", exc_info=True)

    def _notify_done(self, session_id: int) -> None:
        """主窗口不在前台时，回答结束发一条托盘通知。"""
        if not self.config.get("ui.notify_done", True):
            return
        hwnd = _hwnd(MAIN_TITLE)
        if hwnd and ctypes.windll.user32.IsWindowVisible(hwnd) and not ctypes.windll.user32.IsIconic(hwnd):
            return
        rows = self.store.tail_messages(session_id, 8)
        text = ""
        for row in reversed(rows):
            if row.get("role") == "assistant" and str(row.get("content") or "").strip():
                text = str(row["content"]).strip().replace("\n", " ")[:120]
                break
        self._notify(t("回答已完成", "Reply ready"),
                     text or t("Nexus 已完成本次回答", "Nexus finished the reply"))

    def _auto_check_update(self) -> None:
        if self._update_checking or not self.updater.enabled():
            return
        self._update_checking = True
        try:
            info = self.updater.check(force=False)
            if info.get("has_update") and not info.get("skipped"):
                self._update_info = info
                self.push({"type": "update_available", "info": info})
        except Exception:
            log.debug("自动检查更新失败", exc_info=True)
        finally:
            self._update_checking = False

    def check_updates(self, force: bool = True) -> dict:
        self._update_checking = True
        try:
            info = self.updater.check(force=force)
            if info.get("has_update"):
                self._update_info = info
            return info
        finally:
            self._update_checking = False

    def push(self, payload: dict) -> None:
        if payload.get("type") == "state" and payload.get("status"):
            self.orb_win.set_status(str(payload["status"]))
        data = json.dumps(payload, ensure_ascii=False)
        js = "window.Nexus && window.Nexus.onEvent(" + data + ");"
        quick_js = "window.NexusQuick && window.NexusQuick.onEvent(" + data + ");"
        targets = []
        if self._loaded_main:
            targets.append((self.main, js))
        if self._loaded_orb:
            targets.append((self.orb, js))
        if self._loaded_quick:
            targets.append((self.quick, quick_js))
        for win, code in targets:
            try:
                win.evaluate_js(code)
            except Exception:
                pass

    def on_agent_event(self, event: dict) -> None:
        # 带上会话 id：定时任务同时运行时，前端只渲染当前会话的事件
        if self._run_session_id and not event.get("session_id"):
            event = dict(event, session_id=self._run_session_id)
        self.push(event)

    def run_scheduled_task(self, task: dict) -> str:
        """到点执行：新建一个会话，把 prompt 当作用户消息发给 AI，并把过程推给界面。"""
        # 用户正在对话时先等这一轮结束，避免两路输出互相打断
        deadline = time.time() + 300
        while self._running and time.time() < deadline:
            time.sleep(2)
        title = str(task.get("title") or "定时任务")
        prompt = str(task.get("prompt") or "")
        mode = str(self.config.get("mode") or "supervised")
        session_id = self.store.create_session(f"定时 · {title}"[:40], mode)
        self.scheduler.context_session_id = session_id
        self.push({"type": "schedule_start", "task_id": task.get("id"),
                   "session_id": session_id, "title": title, "prompt": prompt[:400]})
        time.sleep(0.8)
        events: list[dict] = []

        def emit(evt: dict) -> None:
            item = dict(evt)
            item["session_id"] = session_id
            events.append(item)
            self.push(item)

        agent = Agent(self.config, self.store, self.safety, self.registry)
        try:
            agent.run(session_id, prompt, on_event=emit, confirm=None,
                      cancel=threading.Event(), ask=None, notify=self._notify)
        except Exception as e:
            log.exception("定时任务执行失败")
            self.push({"type": "error", "message": f"定时任务执行失败：{e}",
                       "session_id": session_id})
        summary = ""
        for event in reversed(events):
            if event.get("type") == "assistant_done" and event.get("text"):
                summary = str(event["text"])
                break
        if not summary:
            for row in reversed(self.store.tail_messages(session_id, 8)):
                if row.get("role") == "assistant" and str(row.get("content") or "").strip():
                    summary = str(row["content"]).strip()
                    break
        self.push({"type": "run_end", "session_id": session_id})
        self.push({"type": "schedule_done", "task_id": task.get("id"),
                   "session_id": session_id, "title": title, "summary": summary[:400]})
        return summary

    def start_run(self, payload: dict) -> dict:
        with self._lock:
            if self._running:
                return {"ok": False, "error": t("正在回答中，先停止再发送",
                                                "Still replying. Stop the current answer first.")}
            text = (payload.get("text") or "").strip()
            attachments = payload.get("attachments") or []
            skill_id = str(payload.get("skill") or "").strip() or None
            if not text and not attachments:
                return {"ok": False, "error": t("内容为空", "Content is empty")}
            session_id = payload.get("session_id")
            if not session_id:
                session_id = self.store.create_session(text[:18] or t("新对话", "New chat"),
                                                       self.config.get("mode") or "supervised")
            self._cancel = threading.Event()
            self._running = True
            cancel = self._cancel
            self.scheduler.context_session_id = session_id
            self._run_session_id = session_id

        def worker():
            try:
                self.perf.begin_run()
            except Exception:
                log.debug("性能采样启动失败", exc_info=True)
            try:
                self.agent.run(session_id, text, on_event=self.on_agent_event,
                               confirm=self._confirm, cancel=cancel, attachments=attachments,
                               ask=self._ask, notify=self._notify,
                               on_control=self.on_control_active, skill_id=skill_id)
            except Exception as e:
                log.exception("对话执行失败")
                self.push({"type": "error",
                           "message": t(f"执行出错：{e}", f"Execution error: {e}"),
                           "hint": t("可查看日志或重试", "Check the logs or try again"),
                           "session_id": session_id})
            finally:
                try:
                    self.perf.end_run()
                except Exception:
                    log.debug("性能采样结束失败", exc_info=True)
                with self._lock:
                    self._running = False
                self.push({"type": "run_end", "session_id": session_id})
                self._notify_done(session_id)

        threading.Thread(target=worker, daemon=True, name="nexus-agent").start()
        return {"ok": True, "session_id": session_id}

    def _confirm(self, req: dict) -> bool:
        event = threading.Event()
        slot = {"event": event, "allow": False}
        with self._lock:
            self._pending[req["id"]] = slot
        try:
            event.wait(timeout=120)
        finally:
            with self._lock:
                self._pending.pop(req["id"], None)
        return bool(slot["allow"])

    def _ask(self, req: dict) -> dict:
        event = threading.Event()
        slot = {"event": event, "answer": "", "cancelled": True}
        with self._lock:
            self._pending_asks[req["id"]] = slot
        try:
            event.wait(timeout=300)
        finally:
            with self._lock:
                self._pending_asks.pop(req["id"], None)
        return {"answer": slot["answer"], "cancelled": slot["cancelled"]}

    def ask_reply(self, payload: dict) -> dict:
        rid = payload.get("id")
        with self._lock:
            slot = self._pending_asks.get(rid)
            if not slot:
                return {"ok": False, "error": "提问已过期"}
            slot["answer"] = str(payload.get("answer") or "")[:2000]
            slot["cancelled"] = bool(payload.get("cancelled"))
            slot["event"].set()
        return {"ok": True}

    def confirm_reply(self, payload: dict) -> dict:
        rid = payload.get("id")
        with self._lock:
            slot = self._pending.get(rid)
            if not slot:
                return {"ok": False, "error": "确认已过期"}
            slot["allow"] = bool(payload.get("allow"))
            slot["event"].set()
        return {"ok": True}

    def _set_control(self, active: bool) -> None:
        if active == self._control_active:
            return
        self._control_active = active
        if active:
            try:
                self._control_prev = int(ctypes.windll.user32.GetForegroundWindow() or 0)
            except OSError:
                self._control_prev = 0
            self.glow.show()
        else:
            self.glow.hide()
            prev = self._control_prev
            self._control_prev = 0
            if prev:
                try:
                    if ctypes.windll.user32.IsWindow(prev):
                        _force_foreground(prev)
                except OSError:
                    pass
        self.push({"type": "control_state", "active": active})

    def on_control_active(self, active: bool) -> None:
        self._set_control(bool(active))

    def _escape_control(self) -> None:
        """用户按 ESC 重新接管屏幕：停止当前任务并撤掉光晕。"""
        self._set_control(False)
        self.push({"type": "control_state", "active": False, "released": True})
        self.push({"type": "notify", "title": "已重新接管",
                   "message": "AI 已停止控制电脑屏幕"})
        self.stop_run()

    def stop_run(self) -> dict:
        self._set_control(False)
        if self._cancel and self._running:
            self._cancel.set()
            with self._lock:
                asks = list(self._pending_asks.values())
                confirms = list(self._pending.values())
            for slot in asks:
                slot["cancelled"] = True
                slot["event"].set()
            for slot in confirms:
                slot["allow"] = False
                slot["event"].set()
            return {"ok": True}
        return {"ok": False, "error": "当前没有正在进行的回答"}


class NexusApi:
    """暴露给网页的接口。"""

    def __init__(self, app: NexusApp):
        # 下划线开头：避免 pywebview 递归扫描并暴露内部对象
        self._app = app
        self._compressing = False

    # ---------- 基础 ----------
    def _scenes(self) -> list[dict]:
        scenes = __import__("app.core.prompts", fromlist=["SCENES"]).SCENES
        if get_language() != "en":
            return scenes
        names = {
            "net": ("Network check", "My computer cannot connect to the internet. Please help me diagnose it."),
            "files": ("Organize files", "Please inspect my Downloads folder and organize the files by type."),
            "doc": ("Write a document", "Help me write a document about: "),
            "web": ("Build a web page", "Help me build a single-file web page about: "),
            "shot": ("Analyze a screenshot", ""),
        }
        out = []
        for item in scenes:
            title, prompt = names.get(item.get("id"), (item.get("title"), item.get("prompt")))
            copy = dict(item)
            copy["title"] = title
            copy["prompt"] = prompt
            out.append(copy)
        return out

    def get_state(self) -> dict:
        app = self._app
        cfg = app.config
        profile = cfg.get("ui.profile") or {}
        avatar = str(profile.get("avatar") or "default").lower()
        if avatar not in ("default", "custom"):
            avatar = "default"
        assistant_name = str(cfg.get("ui.assistant_name") or "Nexus").strip() or "Nexus"
        avatar_data = avatar_store.data_url(cfg.dir) if avatar == "custom" else ""
        provider_state: dict[str, dict] = {}
        for item in provider_catalog.catalog():
            pid = str(item["id"])
            provider_state[pid] = {
                "configured": cfg.provider_has_key(pid),
                "base_url": cfg.provider_base_url(pid),
                "models": cfg.provider_models(pid),
                "name": cfg.provider_name(pid),
                "kind": cfg.provider_kind(pid),
            }
        return {
            "ok": True,
            "version": __import__("app").__version__,
            "has_key": cfg.has_key(),
            "mode": cfg.get("mode") or "supervised",
            "assistant_name": assistant_name,
            "output_dir": str(cfg.output_dir),
            "data_dir": str(cfg.dir),
            "theme": cfg.get("ui.theme") or "light",
            "accent": cfg.get("ui.accent") or "blue",
            "language": get_language(),
            "profile": {
                "name": str(profile.get("name") or ""),
                "avatar": avatar,
                "color": str(profile.get("color") or "blue"),
                "avatar_data": avatar_data,
            },
            "hotkey": cfg.get("ui.hotkey") or "ctrl+alt+space",
            "scenes": self._scenes(),
            "settings": {
                "base_url": cfg.get("llm.base_url"),
                "model": cfg.get("llm.model"),
                "provider": cfg.active_provider(),
                "active_provider": cfg.active_provider(),
                "active_model": cfg.active_model(),
                "provider_catalog": provider_catalog.catalog(),
                "providers": provider_state,
                "thinking": cfg.get("llm.thinking") or "auto",
                "reasoning_effort": cfg.get("llm.reasoning_effort") or "high",
                "timeout": int(cfg.get("llm.timeout") or 90),
                "max_tokens": int(cfg.get("llm.max_tokens") or 65536),
                "output_dir": str(cfg.output_dir),
                "theme": cfg.get("ui.theme") or "light",
                "accent": cfg.get("ui.accent") or "blue",
                "language": cfg.get("ui.language") or "zh",
                "assistant_name": assistant_name,
                "profile": {
                    "name": str(profile.get("name") or ""),
                    "avatar": avatar,
                    "color": str(profile.get("color") or "blue"),
                },
                "hotkey": cfg.get("ui.hotkey") or "ctrl+alt+space",
                "voice_hotkey": cfg.get("ui.voice_hotkey") or "ctrl+alt+v",
                "voice_ready": self._app.speech.ready(),
                "autostart": bool(cfg.get("ui.autostart")),
                "mode": cfg.get("mode") or "supervised",
                "extra_prompt": cfg.get("prompt.extra") or "",
                "skills_auto": bool(cfg.get("skills.auto", True)),
                "memory_enabled": bool(cfg.get("memory.enabled", True)),
                "notify_done": bool(cfg.get("ui.notify_done", True)),
                "show_api_errors": bool(cfg.get("ui.show_api_errors", True)),
                "context_limit": int(cfg.get("ui.context_limit") or 131072),
                "context_compress": bool(cfg.get("ui.context_compress", True)),
                "update_repo": cfg.get("update.repo") or "",
                "update_base_url": cfg.get("update.base_url") or "",
                "update_auto_check": bool(cfg.get("update.auto_check", True)),
                "update_info": dict(self._app._update_info or {}),
                "last_seen_version": cfg.get("ui.last_seen_version") or "",
                "onboarded": bool(cfg.get("ui.onboarded")),
            },
        }

    def send(self, payload: dict) -> dict:
        return self._app.start_run(payload or {})

    def stop(self) -> dict:
        return self._app.stop_run()

    def confirm_reply(self, payload: dict) -> dict:
        return self._app.confirm_reply(payload or {})

    def ask_reply(self, payload: dict) -> dict:
        return self._app.ask_reply(payload or {})

    # ---------- 窗口 ----------
    def win(self, action: str, payload: dict | None = None) -> dict:
        app = self._app
        payload = payload or {}
        try:
            if action == "hide":
                app.hide_main()
            elif action == "minimize":
                app.minimize_main()
            elif action == "maximize":
                app.toggle_maximize_main()
            elif action == "fullscreen":
                app.toggle_fullscreen_main()
            elif action == "show":
                app.show_main()
            elif action == "drag_start":
                app.drag_start("main")
            elif action == "drag_move":
                app.drag_move("main")
            elif action == "drag_end":
                app.drag_end("main")
        except Exception:
            log.exception("窗口操作失败：%s", action)
            raise
        return {"ok": True}

    def log_js(self, text: str) -> dict:
        """接收前端未捕获异常，写入日志便于定位。"""
        log.warning("前端错误：%s", str(text or "")[:600])
        return {"ok": True}

    def quick(self, action: str, payload: dict | None = None) -> dict:
        """悬浮球快捷输入浮窗。"""
        app = self._app
        payload = payload or {}
        if action == "hide":
            app.hide_quick()
        elif action == "voice":
            app.toggle_voice(show=False)
        elif action == "shot":
            if app._quick_capture:
                return {"ok": True, "busy": True}
            app._quick_capture = True
            threading.Thread(target=app._capture_for_quick, daemon=True,
                             name="nexus-quick-shot").start()
        elif action == "send":
            text = str(payload.get("text") or "").strip()
            image = str(payload.get("image") or "").strip()
            if not text and not image:
                return {"ok": False, "error": "内容为空"}
            app.hide_quick()
            app.show_main()
            event = {"type": "quick_send", "text": text}
            if image:
                event["attachments"] = [{"type": "image", "data": image}]
            app.push(event)
        return {"ok": True}

    def orb(self, action: str, payload: dict | None = None) -> dict:
        app = self._app
        if action == "drag_start":
            app.drag_start("orb")
        elif action == "drag_move":
            app.drag_move("orb")
        elif action == "drag_end":
            app.drag_end("orb")
        elif action == "click":
            app.show_main()
        elif action == "menu":
            return app._orb_menu(payload)
        elif action == "show":
            app.show_orb()
        return {"ok": True}

    def start_voice(self) -> dict:
        self._app.start_voice()
        return {"ok": True}

    def voice_toggle(self) -> dict:
        return self._app.toggle_voice()

    def voice_status(self) -> dict:
        app = self._app
        return {"ok": True, "ready": app.speech.ready(),
                "downloading": app.speech.downloading(),
                "recording": app._mic is not None}

    def voice_download(self) -> dict:
        app = self._app
        if app.speech.ready():
            return {"ok": True, "ready": True}
        if not app.speech.downloading():
            threading.Thread(target=app._prepare_speech, daemon=True,
                             name="nexus-asr-download").start()
        return {"ok": True, "started": True}

    def create_shortcut(self) -> dict:
        """在桌面创建 Nexus 快捷方式。"""
        try:
            import pythoncom
            from win32com.client import Dispatch

            pythoncom.CoInitialize()
            shell = Dispatch("WScript.Shell")
            desktop = Path(shell.SpecialFolders("Desktop"))
            lnk = desktop / "Nexus.lnk"
            if getattr(sys, "frozen", False):
                target = Path(sys.executable)
                args = ""
                workdir = target.parent
            else:
                main_py = Path(__file__).resolve().parents[1] / "main.py"
                pyw = Path(sys.executable).with_name("pythonw.exe")
                target = pyw if pyw.exists() else Path(sys.executable)
                args = f'"{main_py}"'
                workdir = main_py.parent
            shortcut = shell.CreateShortCut(str(lnk))
            shortcut.TargetPath = str(target)
            shortcut.Arguments = args
            shortcut.WorkingDirectory = str(workdir)
            shortcut.IconLocation = f"{target},0"
            shortcut.Description = "Nexus 桌面助手"
            shortcut.Save()
            return {"ok": True, "path": str(lnk)}
        except Exception as e:
            return {"ok": False, "error": f"创建快捷方式失败：{e}"}

    # ---------- 设置 ----------
    def settings_get(self) -> dict:
        return self.get_state()["settings"]

    def settings_save(self, payload: dict) -> dict:
        app = self._app
        cfg = app.config
        patch = payload or {}
        active = cfg.active_provider()
        target = str(patch.get("provider") or active).strip() or active
        if target not in (provider_catalog.BUILTIN_IDS + ("custom",)):
            return {"ok": False, "error": t("未知的模型厂商", "Unknown model provider")}
        if "base_url" in patch:
            url = str(patch["base_url"] or "").strip().rstrip("/")
            if url and not url.startswith(("http://", "https://")):
                return {"ok": False, "error": t(
                    "接口地址需以 http:// 或 https:// 开头",
                    "The API URL must start with http:// or https://",
                )}
            cfg.save_provider(target, {"base_url": url}, save=False)
        if "models" in patch and isinstance(patch.get("models"), list):
            cfg.save_provider(target, {"models": patch.get("models")}, save=False)
        if "model" in patch:
            cfg.set("llm.model", str(patch.get("model") or "").strip())
        if patch.get("api_key"):
            cfg.set_provider_key(target, str(patch["api_key"]), save=False)
        if "thinking" in patch:
            value = str(patch.get("thinking") or "auto").lower()
            cfg.set("llm.thinking", value if value in ("auto", "enabled", "disabled") else "auto")
        if "reasoning_effort" in patch:
            value = str(patch.get("reasoning_effort") or "high").lower()
            cfg.set("llm.reasoning_effort", "max" if value == "max" else "high")
        if "timeout" in patch:
            try:
                cfg.set("llm.timeout", max(15, min(600, int(patch["timeout"]))))
            except (TypeError, ValueError):
                pass
        if "max_tokens" in patch:
            try:
                value = int(patch["max_tokens"])
            except (TypeError, ValueError):
                value = 65536
            cfg.set("llm.max_tokens", 131072 if value >= 98304 else 65536)
        if target != active:
            model = str(patch.get("model") or "").strip()
            if model:
                try:
                    cfg.set_active(target, model)
                except Exception as e:
                    return {"ok": False, "error": str(e)}
            else:
                cfg.set("llm.provider", target)
                cfg.set("llm.base_url", cfg.provider_base_url(target))
        elif cfg.active_provider() == active:
            cfg.set("llm.base_url", cfg.provider_base_url(active))
        cfg.save()
        if "output_dir" in patch and patch["output_dir"]:
            p = Path(str(patch["output_dir"])).expanduser()
            try:
                p.mkdir(parents=True, exist_ok=True)
                cfg.set("paths.output_dir", str(p.resolve()))
            except OSError as e:
                return {"ok": False, "error": t(
                    f"输出目录不可用：{e}", f"Output folder is unavailable: {e}",
                )}
        if "theme" in patch:
            value = str(patch.get("theme") or "light").lower()
            cfg.set("ui.theme", value if value in ("light", "dark", "system") else "light")
        if "accent" in patch:
            value = str(patch.get("accent") or "blue").lower()
            cfg.set("ui.accent", value if value in ("blue", "green", "violet", "orange") else "blue")
        if "language" in patch:
            value = str(patch.get("language") or "zh").lower()
            value = value if value in ("zh", "en", "system") else "zh"
            cfg.set("ui.language", value)
            set_language(value)
            app._rebuild_tray()
        if "profile" in patch and isinstance(patch.get("profile"), dict):
            profile = patch["profile"] or {}
            current = dict(cfg.get("ui.profile") or {})
            name = str(profile.get("name") or "").strip()[:32]
            avatar = str(profile.get("avatar") or "default").lower()
            color = str(profile.get("color") or "blue").lower()
            avatar_data = profile.get("avatar_data")
            if avatar_data:
                try:
                    version = avatar_store.save(cfg.dir, str(avatar_data))
                except ValueError as e:
                    return {"ok": False, "error": str(e)}
                avatar = "custom"
                current["avatar_version"] = version
            elif avatar == "default":
                avatar_store.clear(cfg.dir)
                current["avatar_version"] = 0
            elif avatar not in ("custom",):
                avatar = "default"
            current.update({
                "name": name,
                "avatar": avatar,
                "color": color if color in ("blue", "green", "violet", "orange", "slate") else "blue",
            })
            cfg.set("ui.profile", current)
        if "assistant_name" in patch:
            value = " ".join(str(patch.get("assistant_name") or "").split())[:24]
            cfg.set("ui.assistant_name", value or "Nexus")
        if "notify_done" in patch:
            cfg.set("ui.notify_done", bool(patch.get("notify_done")))
        if "extra_prompt" in patch:
            cfg.set("prompt.extra", str(patch.get("extra_prompt") or "").strip()[:4000])
        if "skills_auto" in patch:
            cfg.set("skills.auto", bool(patch.get("skills_auto")))
        if "memory_enabled" in patch:
            cfg.set("memory.enabled", bool(patch.get("memory_enabled")))
        if "show_api_errors" in patch:
            cfg.set("ui.show_api_errors", bool(patch.get("show_api_errors")))
        if "context_compress" in patch:
            cfg.set("ui.context_compress", bool(patch.get("context_compress")))
        if "context_limit" in patch:
            try:
                value = int(patch["context_limit"])
            except (TypeError, ValueError):
                value = 131072
            cfg.set("ui.context_limit", 1048576 if value >= 600000 else 131072)
        if "update_base_url" in patch:
            raw = str(patch.get("update_base_url") or "").strip().rstrip("/")
            if raw and not re.match(r"^https?://[^\s]+$", raw, flags=re.I):
                return {"ok": False, "error": t(
                    "更新服务地址应以 http:// 或 https:// 开头",
                    "Update service URL must start with http:// or https://",
                )}
            cfg.set("update.base_url", raw)
        if "update_repo" in patch:
            raw = str(patch.get("update_repo") or "").strip()
            repo = normalize_repo(raw)
            if raw and not repo:
                return {"ok": False, "error": t(
                    "GitHub 仓库格式应为 owner/repo",
                    "GitHub repository must be in owner/repo format",
                )}
            cfg.set("update.repo", repo)
        if "update_auto_check" in patch:
            cfg.set("update.auto_check", bool(patch.get("update_auto_check")))
        if "hotkey" in patch and patch["hotkey"]:
            cfg.set("ui.hotkey", str(patch["hotkey"]).strip())
            app._start_hotkey()
        if "voice_hotkey" in patch and patch["voice_hotkey"]:
            cfg.set("ui.voice_hotkey", str(patch["voice_hotkey"]).strip())
            app._start_hotkey()
        if "autostart" in patch:
            ok, msg = self._set_autostart(bool(patch["autostart"]))
            if not ok:
                return {"ok": False, "error": msg}
            cfg.set("ui.autostart", bool(patch["autostart"]))
        if "mode" in patch:
            value = str(patch.get("mode") or "supervised").lower()
            cfg.set("mode", value if value in ("safe", "supervised", "full") else "supervised")
        cfg.save()
        app.push({"type": "settings_changed", "settings": self.get_state()["settings"],
                  "language": get_language()})
        return {"ok": True}

    # ---------- 模型厂商 ----------
    def provider_save(self, payload: dict) -> dict:
        app = self._app
        cfg = app.config
        data = payload or {}
        pid = str(data.get("id") or "").strip()
        if pid not in (provider_catalog.BUILTIN_IDS + ("custom",)):
            return {"ok": False, "error": t("未知的模型厂商", "Unknown model provider")}
        base = data.get("base_url")
        if base is not None:
            base = str(base or "").strip().rstrip("/")
            if base and not base.startswith(("http://", "https://")):
                return {"ok": False, "error": t(
                    "接口地址需以 http:// 或 https:// 开头",
                    "The API URL must start with http:// or https://",
                )}
            if not base and pid == "custom":
                return {"ok": False, "error": t(
                    "自定义厂商需要填写接口地址", "A custom provider needs a base URL",
                )}
        patch: dict = {}
        if base is not None:
            patch["base_url"] = base
        if isinstance(data.get("models"), list):
            patch["models"] = data["models"]
        if pid == "custom":
            if "name" in data:
                patch["name"] = str(data.get("name") or "").strip()[:40]
            if "kind" in data:
                patch["kind"] = "anthropic" if str(data.get("kind")).lower() == "anthropic" else "openai"
        cfg.save_provider(pid, patch, save=False)
        if data.get("clear_key"):
            cfg.set_provider_key(pid, "", save=False)
        elif str(data.get("api_key") or "").strip():
            cfg.set_provider_key(pid, str(data["api_key"]).strip(), save=False)
        key = cfg.provider_key(pid)
        models = cfg.provider_models(pid)
        if pid == cfg.active_provider() and models and cfg.active_model() not in models:
            cfg.set_active(pid, models[0])
        should_activate = bool(data.get("activate"))
        if not should_activate and key and models and not cfg.provider_has_key(cfg.active_provider()):
            # 第一次配置厂商时自动设为当前，避免填了 Key 却没有可用模型。
            should_activate = True
        if should_activate and key and models:
            model = str(data.get("model") or "").strip() or models[0]
            if model not in models:
                model = models[0]
            cfg.set_active(pid, model)
        else:
            cfg.save()
        app.push({"type": "settings_changed", "settings": self.get_state()["settings"],
                  "language": get_language()})
        return {"ok": True, "state": self.get_state()["settings"]}

    def provider_delete(self, payload: dict) -> dict:
        app = self._app
        pid = str((payload or {}).get("id") or "").strip()
        if pid not in (provider_catalog.BUILTIN_IDS + ("custom",)):
            return {"ok": False, "error": t("未知的模型厂商", "Unknown model provider")}
        app.config.delete_provider(pid)
        app.push({"type": "settings_changed", "settings": self.get_state()["settings"],
                  "language": get_language()})
        return {"ok": True, "state": self.get_state()["settings"]}

    def model_select(self, payload: dict) -> dict:
        app = self._app
        cfg = app.config
        data = payload or {}
        pid = str(data.get("provider") or cfg.active_provider()).strip()
        model = str(data.get("model") or "").strip()
        if pid not in (provider_catalog.BUILTIN_IDS + ("custom",)):
            return {"ok": False, "error": t("未知的模型厂商", "Unknown model provider")}
        if not cfg.provider_has_key(pid):
            return {"ok": False, "error": t(
                "这个厂商还没有配置 API Key", "This provider has no API key yet",
            )}
        models = cfg.provider_models(pid)
        if not model:
            model = models[0] if models else ""
        if not model:
            return {"ok": False, "error": t("请先填写模型名称", "Enter a model name first")}
        if models and model not in models:
            return {"ok": False, "error": t("该厂商没有这个模型", "Unknown model for this provider")}
        try:
            cfg.set_active(pid, model)
        except Exception as e:
            return {"ok": False, "error": str(e)}
        app.push({"type": "settings_changed", "settings": self.get_state()["settings"],
                  "language": get_language()})
        return {"ok": True, "provider": pid, "model": model,
                "settings": self.get_state()["settings"]}

    def provider_test(self, payload: dict | None = None) -> dict:
        cfg = self._app.config
        data = payload or {}
        pid = str(data.get("id") or cfg.active_provider()).strip()
        base = str(data.get("base_url") or "").strip().rstrip("/")
        key = str(data.get("api_key") or "").strip()
        model = str(data.get("model") or "").strip()
        kind = str(data.get("kind") or "").strip().lower()
        override = {
            "provider": pid,
            "base_url": base or cfg.provider_base_url(pid),
            "api_key": key or cfg.provider_key(pid),
            "model": model or (cfg.provider_models(pid) or [""])[0],
            "kind": kind or cfg.provider_kind(pid),
        }
        if not override["api_key"]:
            return {"ok": False, "error": t("还没有填写 API Key", "No API key configured")}
        if not override["model"]:
            return {"ok": False, "error": t("还没有选择模型", "No model selected")}
        try:
            client = LLMClient(cfg, override=override)
            prompt = ("This is a connection test. Reply only with: OK"
                      if cfg.get("ui.language") == "en"
                      else "这是一次连接测试，请只回复：连接成功")
            result = client.chat([{"role": "user", "content": prompt}], temperature=0)
            return {"ok": True, "text": (result.get("text") or "").strip()[:80] or t("已连通", "Connected")}
        except LLMError as e:
            return {"ok": False, "error": e.message, "hint": e.hint,
                    "status": e.status, "detail": e.detail}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    def provider_models(self, payload: dict | None = None) -> dict:
        """从厂商 /models 接口读取当前可用模型，便于用户直接勾选。"""
        import urllib.error
        import urllib.request

        cfg = self._app.config
        data = payload or {}
        pid = str(data.get("id") or cfg.active_provider()).strip()
        base = str(data.get("base_url") or cfg.provider_base_url(pid)).strip().rstrip("/")
        key = str(data.get("api_key") or cfg.provider_key(pid)).strip()
        kind = str(data.get("kind") or cfg.provider_kind(pid)).lower()
        if not base:
            return {"ok": False, "error": t("请先填写接口地址", "Enter a base URL first")}
        if not key:
            return {"ok": False, "error": t("请先填写 API Key", "Enter an API key first")}
        if kind == "anthropic":
            url = base + ("/models" if base.endswith("/v1") else "/v1/models")
            headers = {
                "x-api-key": key,
                "Authorization": f"Bearer {key}",
                "anthropic-version": "2023-06-01",
                "Accept": "application/json",
            }
        else:
            url = base if base.endswith("/models") else base + "/models"
            headers = {
                "Authorization": f"Bearer {key}",
                "Accept": "application/json",
            }
        try:
            req = urllib.request.Request(url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=20) as resp:
                obj = json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")[:300]
            except OSError:
                pass
            return {"ok": False, "error": t(
                f"读取模型列表失败（HTTP {e.code}）",
                f"Failed to load models (HTTP {e.code})",
            ), "detail": body}
        except Exception as e:
            return {"ok": False, "error": t(
                f"读取模型列表失败：{e}", f"Failed to load models: {e}",
            )}
        items = obj.get("data") if isinstance(obj, dict) else None
        models = []
        for item in items or []:
            if isinstance(item, dict):
                name = str(item.get("id") or "").strip()
                label = str(item.get("display_name") or item.get("name") or name).strip()
            else:
                name = str(item or "").strip()
                label = name
            if name and name not in [m["id"] for m in models]:
                models.append({"id": name, "label": label or name})
        models.sort(key=lambda m: m["id"].lower())
        return {"ok": True, "models": models, "count": len(models)}

    # ---------- 上下文 ----------
    def perf_stats(self) -> dict:
        """后端、整棵应用进程树与系统的实时资源占用。"""
        try:
            return self._app.perf.snapshot()
        except Exception as e:
            log.warning("读取资源占用失败：%s", e)
            return {"ok": False, "error": str(e)}

    def context_stats(self, payload: dict | None = None) -> dict:
        """当前会话的上下文占用（摘要 + 未摘要消息）。"""
        app = self._app
        sid = int((payload or {}).get("session_id") or 0)
        if not sid:
            limit = int(app.config.get("ui.context_limit") or 131072)
            return {
                "ok": True, "used": 0, "limit": limit, "percent": 0.0,
                "threshold": max(512, int(limit * COMPRESS_RATIO)),
                "summary_tokens": 0, "messages": 0, "summarized": False,
            }
        return {"ok": True, **app.agent.context_usage(sid)}

    def compress_context(self, payload: dict | None = None) -> dict:
        """手动压缩：后台执行，进度通过 context 事件推送。"""
        app = self._app
        sid = int((payload or {}).get("session_id") or 0)
        if not sid:
            return {"ok": False, "error": t("请先打开一个会话", "Open a conversation first")}
        if not app.config.has_key():
            return {"ok": False, "error": t(
                "尚未配置 API Key，无法压缩上下文",
                "Configure an API key before compressing context",
            )}
        with app._lock:
            if app._running:
                return {"ok": False, "error": t(
                    "正在回答中，先停止再压缩",
                    "Still replying. Stop the current answer first.",
                )}
        if self._compressing:
            return {"ok": False, "error": t(
                "正在压缩上下文，请稍候",
                "Context compression is already running",
            )}
        self._compressing = True

        def worker():
            try:
                result = app.agent.compress_session(sid, emit=app.push)
                if result.get("skipped"):
                    app.push({"type": "context", "action": "compress_skipped",
                              "session_id": sid,
                              "message": t("当前会话还没有可压缩的内容",
                                           "There is nothing to compress yet")})
            except Exception as e:
                log.warning("手动压缩上下文失败：%s", e)
                app.push({"type": "context", "action": "compress_failed",
                          "session_id": sid, "message": str(e), "manual": True})
            finally:
                self._compressing = False

        threading.Thread(target=worker, daemon=True, name="nexus-compress").start()
        return {"ok": True, "started": True}

    # ---------- 首次引导 / 新功能 ----------
    def onboarding_complete(self, payload: dict) -> dict:
        app = self._app
        result = self.settings_save(payload or {})
        if not result.get("ok"):
            return result
        app.config.set("ui.onboarded", True)
        app.config.set("ui.last_seen_version", app._version())
        app.config.save()
        try:
            app.onboarding.hide()
        except Exception:
            pass
        app.show_main()
        return {"ok": True}

    def onboarding_skip(self) -> dict:
        app = self._app
        app.config.set("ui.onboarded", True)
        app.config.set("ui.last_seen_version", app._version())
        app.config.save()
        try:
            app.onboarding.hide()
        except Exception:
            pass
        app.show_main()
        return {"ok": True}

    def show_onboarding(self) -> dict:
        self._app.show_onboarding()
        return {"ok": True}

    def whatsnew_done(self) -> dict:
        app = self._app
        app.config.set("ui.last_seen_version", app._version())
        app.config.save()
        try:
            app.whatsnew.hide()
        except Exception:
            pass
        app.show_main()
        return {"ok": True}

    def show_whatsnew(self) -> dict:
        self._app.show_whatsnew()
        return {"ok": True}

    # ---------- 数据 ----------
    def open_data_dir(self) -> dict:
        path = self._app.config.dir
        try:
            if os.name == "nt":
                os.startfile(str(path))
            else:
                subprocess.Popen(["xdg-open", str(path)])
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def clear_history(self) -> dict:
        count = self._app.store.clear_all_sessions()
        self._app.push({"type": "history_cleared"})
        return {"ok": True, "count": count}

    def reset_settings(self) -> dict:
        app = self._app
        app.config.reset_preferences()
        set_language(app.config.get("ui.language"))
        app._rebuild_tray()
        state = self.get_state()
        app.push({"type": "settings_reset", "state": state})
        return {"ok": True, "state": state}

    # ---------- 更新 ----------
    def check_update(self, force: bool = True) -> dict:
        return self._app.check_updates(bool(force))

    def update_skip(self, version: str = "") -> dict:
        app = self._app
        version = str(version or app._update_info.get("latest") or "").strip()
        if version:
            app.config.set("update.skipped_version", version)
            app.config.save()
        return {"ok": True}

    def update_install(self) -> dict:
        app = self._app
        info = app._update_info or {}
        url = str(info.get("asset_url") or "")
        name = str(info.get("asset_name") or "")
        if not url:
            return {"ok": False, "error": t(
                "没有可下载的更新包，请在设置里检查更新服务地址。",
                "No downloadable update package. Check the update service URL in Settings.",
            )}
        if app._update_checking:
            return {"ok": False, "error": t("更新正在进行中", "An update is already in progress")}
        app._update_checking = True

        def worker() -> None:
            try:
                app.push({"type": "update_progress", "phase": "download", "done": 0, "total": 0})
                path = app.updater.download(
                    url, name,
                    progress=lambda done, total: app.push({
                        "type": "update_progress", "phase": "download",
                        "done": done, "total": total,
                    }),
                    digest=str(info.get("digest") or ""),
                )
                if info.get("simulate"):
                    app._update_checking = False
                    app.push({
                        "type": "update_simulated",
                        "message": t(
                            "模拟更新完成：安装包已下载并通过 SHA-256 校验，未执行安装。",
                            "Simulated update finished: package downloaded and verified, installer not run.",
                        ),
                        "path": str(path),
                        "size": path.stat().st_size,
                    })
                    return
                app.push({"type": "update_progress", "phase": "install"})
                app.updater.install(path)
                time.sleep(0.5)
                app.quit()
            except Exception as e:
                log.exception("更新失败")
                app._update_checking = False
                app.push({"type": "update_failed", "message": str(e)})

        threading.Thread(target=worker, daemon=True, name="nexus-update").start()
        return {"ok": True, "started": True}

    def open_release_page(self, url: str = "") -> dict:
        url = str(url or (self._app._update_info or {}).get("page") or "")
        if not url.startswith("https://github.com/"):
            return {"ok": False, "error": t("更新地址无效", "Invalid release URL")}
        webbrowser.open(url)
        return {"ok": True}

    def _set_autostart(self, enable: bool) -> tuple[bool, str]:
        if os.name != "nt":
            return False, "仅支持 Windows"
        try:
            import winreg

            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0,
                                winreg.KEY_SET_VALUE) as key:
                if enable:
                    if getattr(sys, "frozen", False):
                        cmd = f'"{sys.executable}"'
                    else:
                        pyw = Path(sys.executable).with_name("pythonw.exe")
                        exe = pyw if pyw.exists() else Path(sys.executable)
                        cmd = f'"{exe}" "{Path(__file__).resolve().parents[1] / "main.py"}"'
                    winreg.SetValueEx(key, "Nexus", 0, winreg.REG_SZ, cmd)
                else:
                    try:
                        winreg.DeleteValue(key, "Nexus")
                    except FileNotFoundError:
                        pass
            return True, ""
        except OSError as e:
            return False, f"设置开机启动失败：{e}"

    def test_llm(self, payload: dict | None = None) -> dict:
        cfg = self._app.config
        draft = payload or {}
        pid = str(draft.get("provider") or cfg.active_provider()).strip()
        base = str(draft.get("base_url") or "").strip()
        model = str(draft.get("model") or "").strip()
        key = str(draft.get("api_key") or "").strip()
        kind = str(draft.get("kind") or "").strip().lower()
        override = {
            "provider": pid,
            "base_url": base or cfg.provider_base_url(pid),
            "model": model or cfg.active_model(),
            "api_key": key or cfg.provider_key(pid),
            "kind": kind or cfg.provider_kind(pid),
        }
        if not override["api_key"]:
            return {"ok": False, "error": t("还没有填写 API Key", "No API key configured")}
        if not override["model"]:
            return {"ok": False, "error": t("还没有选择模型", "No model selected")}
        try:
            client = LLMClient(cfg, override=override)
            prompt = ("This is a connection test. Reply only with: OK"
                      if cfg.get("ui.language") == "en"
                      else "这是一次连接测试，请只回复：连接成功")
            result = client.chat([{"role": "user", "content": prompt}], temperature=0)
            return {"ok": True, "text": (result.get("text") or "").strip()[:80] or t("已连通", "Connected")}
        except LLMError as e:
            return {"ok": False, "error": e.message, "hint": e.hint,
                    "status": e.status, "detail": e.detail}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    def pick_folder(self) -> dict:
        try:
            result = self._app.main.create_file_dialog(webview.FOLDER_DIALOG)
            if result:
                return {"ok": True, "path": str(result[0])}
        except Exception as e:
            return {"ok": False, "error": str(e)}
        return {"ok": False}

    def pick_files(self) -> dict:
        """选择一个或多个本地文件，返回绝对路径。"""
        try:
            result = self._app.main.create_file_dialog(
                webview.OPEN_DIALOG, allow_multiple=True
            )
            if result:
                return {"ok": True, "paths": [str(p) for p in result]}
        except Exception as e:
            return {"ok": False, "error": str(e)}
        return {"ok": False, "cancelled": True}

    def list_files(self) -> dict:
        """给输入框 @ 引用用的文件候选：最近生成文件 + 输出目录。"""
        app = self._app
        items: list[dict] = []
        seen: set[str] = set()
        try:
            for row in app.store.list_files(40):
                path = str(row.get("path") or "")
                if not path or path in seen or not os.path.exists(path):
                    continue
                seen.add(path)
                items.append({
                    "name": row.get("name") or Path(path).name,
                    "path": path,
                    "size": row.get("size") or 0,
                    "source": "recent",
                })
        except Exception:
            log.debug("读取最近文件失败", exc_info=True)
        try:
            root = app.config.output_dir
            files = [p for p in root.rglob("*") if p.is_file() and not p.name.startswith(".")]
            files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            for p in files[:60]:
                path = str(p)
                if path in seen:
                    continue
                seen.add(path)
                items.append({
                    "name": p.name,
                    "path": path,
                    "size": p.stat().st_size,
                    "source": "output",
                })
        except OSError:
            pass
        return {"ok": True, "items": items[:80], "output_dir": str(app.config.output_dir)}

    IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico"}
    TEXT_EXTS = {
        ".txt", ".md", ".markdown", ".json", ".py", ".js", ".ts", ".html", ".htm",
        ".css", ".csv", ".log", ".yaml", ".yml", ".ini", ".xml", ".toml", ".bat",
        ".ps1", ".sh", ".sql", ".c", ".cpp", ".h", ".cs", ".java", ".go", ".rs",
        ".vue", ".jsx", ".tsx",
    }

    def workspace_tree(self) -> dict:
        """返回输出目录的文件树，供右侧文件面板使用。"""
        root = self._app.config.output_dir
        skip = {"__pycache__", "node_modules", ".git", ".venv", "venv", ".idea", ".vscode"}
        budget = [280]

        def build(path: Path, depth: int) -> list[dict]:
            if depth <= 0 or budget[0] <= 0:
                return []
            try:
                entries = list(path.iterdir())
            except OSError:
                return []
            entries.sort(key=lambda p: (p.is_file(), p.name.lower()))
            out = []
            for p in entries:
                if budget[0] <= 0:
                    break
                if p.name.startswith(".") or p.name in skip:
                    continue
                budget[0] -= 1
                if p.is_dir():
                    out.append({"type": "dir", "name": p.name, "path": str(p),
                                "children": build(p, depth - 1)})
                else:
                    try:
                        size = p.stat().st_size
                    except OSError:
                        size = 0
                    out.append({"type": "file", "name": p.name, "path": str(p), "size": size})
            return out

        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        return {"ok": True, "root": str(root), "items": build(root, 3)}

    def _preview_target(self, raw: str) -> tuple[Path | None, str]:
        text = str(raw or "").strip()
        if not text:
            return None, "路径为空"
        try:
            target = Path(text).expanduser().resolve()
        except OSError:
            return None, "路径无效"
        if not target.is_file():
            return None, "文件不存在"
        root = self._app.config.output_dir.resolve()
        try:
            target.relative_to(root)
            return target, ""
        except ValueError:
            pass
        recent = set()
        for row in self._app.store.list_files(200):
            try:
                recent.add(str(Path(row.get("path") or "").resolve()))
            except OSError:
                continue
        if str(target) in recent:
            return target, ""
        return None, "只能预览输出目录或最近生成的文件"

    def read_preview(self, payload: dict) -> dict:
        """预览输出目录或最近生成的文件，支持 Markdown / 文本 / 图片。"""
        target, error = self._preview_target(str((payload or {}).get("path") or ""))
        if target is None:
            return {"ok": False, "error": error}
        try:
            size = target.stat().st_size
        except OSError as e:
            return {"ok": False, "error": str(e)}
        ext = target.suffix.lower()
        if ext in self.IMAGE_EXTS:
            if size > 12 * 1024 * 1024:
                return {"ok": False, "error": "图片太大，无法预览"}
            try:
                data = base64.b64encode(target.read_bytes()).decode()
            except OSError as e:
                return {"ok": False, "error": str(e)}
            mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                    ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
                    ".ico": "image/x-icon"}.get(ext, "application/octet-stream")
            return {"ok": True, "kind": "image", "name": target.name,
                    "path": str(target), "size": size,
                    "data_url": f"data:{mime};base64,{data}"}
        if ext == ".pdf":
            if size > 120 * 1024 * 1024:
                return {"ok": False, "error": "PDF 超过 120MB，无法预览"}
            try:
                meta = pdf_doc.info(target)
                page = pdf_doc.render_page(target, 0, 1.4)
            except Exception as e:
                return {"ok": False, "error": f"PDF 读取失败：{e}"}
            if not page.get("ok"):
                return page
            return {"ok": True, "kind": "pdf", "name": target.name, "path": str(target),
                    "size": size, "pages": meta["pages"], "doc_width": meta["width"],
                    "doc_height": meta["height"], "page": page}
        if ext == ".docx":
            if size > 40 * 1024 * 1024:
                return {"ok": False, "error": "Word 文件超过 40MB，无法预览"}
            try:
                data = docx_doc.to_html(target)
            except Exception as e:
                return {"ok": False, "error": f"Word 读取失败：{e}"}
            data.update({"kind": "docx", "name": target.name, "path": str(target), "size": size})
            return data
        if ext in (".xlsx", ".xlsm"):
            if size > 40 * 1024 * 1024:
                return {"ok": False, "error": "Excel 文件超过 40MB，无法预览"}
            try:
                data = xlsx_doc.grid(target, max_rows=160, max_cols=28)
            except Exception as e:
                return {"ok": False, "error": f"Excel 读取失败：{e}"}
            if not data.get("ok"):
                return data
            data.update({"kind": "xlsx", "name": target.name, "path": str(target), "size": size})
            return data
        if ext == ".pptx":
            if size > 60 * 1024 * 1024:
                return {"ok": False, "error": "PowerPoint 文件超过 60MB，无法预览"}
            try:
                meta = pptx_doc.info(target)
                slide = pptx_doc.slide_payload(target, 0)
            except Exception as e:
                return {"ok": False, "error": f"PowerPoint 读取失败：{e}"}
            if not slide.get("ok"):
                return slide
            return {"ok": True, "kind": "pptx", "name": target.name, "path": str(target),
                    "size": size, "slides": meta["slides"], "width": meta["width"],
                    "height": meta["height"], "slide": slide}
        if ext in (".doc", ".xls", ".ppt"):
            return {"ok": False, "error": "旧版 Office 格式暂不支持，请先另存为 .docx / .xlsx / .pptx"}
        if ext not in self.TEXT_EXTS:
            return {"ok": True, "kind": "binary", "name": target.name,
                    "path": str(target), "size": size}
        if size > 512 * 1024:
            return {"ok": False, "error": "文件超过 512KB，无法预览"}
        try:
            data = target.read_bytes()
        except OSError as e:
            return {"ok": False, "error": str(e)}
        content = ""
        for enc in ("utf-8", "gbk"):
            try:
                content = data.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if not content:
            content = data.decode("utf-8", errors="replace")
        if ext in (".md", ".markdown"):
            kind = "markdown"
        elif ext in (".html", ".htm"):
            kind = "html"
        else:
            kind = "text"
        return {"ok": True, "kind": kind,
                "name": target.name, "path": str(target), "size": size,
                "content": content[:200000]}

    def save_preview(self, payload: dict) -> dict:
        """把面板里编辑过的文本写回原文件，沿用原编码（UTF-8/BOM/GBK）。"""
        data = payload or {}
        target, error = self._preview_target(str(data.get("path") or ""))
        if target is None:
            return {"ok": False, "error": error}
        content = data.get("content")
        if content is None:
            return {"ok": False, "error": "缺少 content"}
        if target.suffix.lower() in self.IMAGE_EXTS:
            return {"ok": False, "error": "图片不能按文本保存"}
        try:
            raw = target.read_bytes()
        except OSError as e:
            return {"ok": False, "error": f"读取原文件失败：{e}"}
        if raw.startswith(b"\xef\xbb\xbf"):
            encoding = "utf-8-sig"
        else:
            encoding = "utf-8"
            try:
                raw.decode("utf-8")
            except UnicodeDecodeError:
                encoding = "gbk"
        try:
            blob = str(content).encode(encoding)
        except UnicodeEncodeError:
            encoding = "utf-8"
            blob = str(content).encode("utf-8")
        if len(blob) > 1024 * 1024:
            return {"ok": False, "error": "内容超过 1MB，已拒绝保存"}
        try:
            target.write_bytes(blob)
        except OSError as e:
            return {"ok": False, "error": f"保存失败：{e}"}
        log.info("面板保存：%s（%s，%d 字节）", target, encoding, len(blob))
        return {"ok": True, "path": str(target), "bytes": len(blob), "encoding": encoding}

    # ---------- 办公文件（PDF / Word / Excel / PPT） ----------
    def pdf_page(self, payload: dict | None = None) -> dict:
        data = payload or {}
        target, error = self._preview_target(str(data.get("path") or ""))
        if target is None:
            return {"ok": False, "error": error}
        if target.suffix.lower() != ".pdf":
            return {"ok": False, "error": "不是 PDF 文件"}
        try:
            return pdf_doc.render_page(target, int(data.get("page") or 0),
                                       float(data.get("zoom") or 1.4))
        except Exception as e:
            return {"ok": False, "error": f"PDF 渲染失败：{e}"}

    def pptx_slide(self, payload: dict | None = None) -> dict:
        data = payload or {}
        target, error = self._preview_target(str(data.get("path") or ""))
        if target is None:
            return {"ok": False, "error": error}
        if target.suffix.lower() != ".pptx":
            return {"ok": False, "error": "不是 PowerPoint 文件"}
        try:
            return pptx_doc.slide_payload(target, int(data.get("index") or 0))
        except Exception as e:
            return {"ok": False, "error": f"PowerPoint 读取失败：{e}"}

    def xlsx_add_sheet(self, payload: dict | None = None) -> dict:
        data = payload or {}
        target, error = self._preview_target(str(data.get("path") or ""))
        if target is None:
            return {"ok": False, "error": error}
        if target.suffix.lower() not in (".xlsx", ".xlsm"):
            return {"ok": False, "error": "不是 Excel 工作簿"}
        try:
            out = xlsx_doc.add_sheet(target, str(data.get("name") or ""))
        except Exception as e:
            return {"ok": False, "error": f"新建工作表失败：{e}"}
        if out.get("ok"):
            log.info("新增工作表：%s -> %s", target, out.get("name"))
        return out

    def office_save(self, payload: dict | None = None) -> dict:
        data = payload or {}
        target, error = self._preview_target(str(data.get("path") or ""))
        if target is None:
            return {"ok": False, "error": error}
        kind = str(data.get("kind") or kind_of(target))
        updates = data.get("updates") or []
        if not isinstance(updates, list) or not updates:
            return {"ok": False, "error": "没有要保存的修改"}
        try:
            if kind == "docx":
                out = docx_doc.update_paragraphs(target, updates)
            elif kind == "xlsx":
                out = xlsx_doc.update_cells(target, updates)
            elif kind == "pptx":
                out = pptx_doc.update_texts(target, updates)
            else:
                return {"ok": False, "error": f"不支持保存的类型：{kind}"}
        except Exception as e:
            return {"ok": False, "error": f"保存失败：{e}"}
        if out.get("ok"):
            log.info("办公文件保存：%s（%s，%s 处）", target, kind, out.get("updated", 0))
            try:
                out["bytes"] = target.stat().st_size
            except OSError:
                pass
        return out

    def _browser_root(self) -> Path:
        root = Path(tempfile.gettempdir()) / "NexusBrowser"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _cleanup_browser_profiles(self, keep: Path | None = None) -> None:
        """删除旧的无痕配置目录；正在使用的窗口跳过。"""
        try:
            root = self._browser_root()
        except OSError:
            return
        now = time.time()
        for item in root.iterdir():
            if keep is not None and item == keep:
                continue
            try:
                if item.is_dir() and now - item.stat().st_mtime > 6 * 3600:
                    shutil.rmtree(item, ignore_errors=True)
            except OSError:
                continue

    def browser_open(self, payload: dict) -> dict:
        """用独立临时配置的 Edge/Chrome 无痕窗口打开网址或本地文件。

        每次都是新的 user-data-dir，窗口之间不共享 Cookie、缓存与登录态；
        InPrivate/Incognito 再额外避免写盘。旧配置目录会在后续打开时清理。
        """
        target = browser_target(str((payload or {}).get("url") or ""))
        if not target:
            return {"ok": False, "error": "地址无效：请输入网址、localhost 或本地文件路径"}
        exe = browser_exe()
        if not exe:
            return {"ok": False, "error": "找不到 Edge 或 Chrome，无法打开浏览器窗口"}
        try:
            profile = Path(tempfile.mkdtemp(prefix="profile-", dir=self._browser_root()))
        except OSError as e:
            return {"ok": False, "error": f"创建临时配置失败：{e}"}
        self._cleanup_browser_profiles(keep=profile)
        args = [
            str(exe), f"--user-data-dir={profile}", "--inprivate", "--incognito",
            "--no-first-run", "--no-default-browser-check", "--disable-sync", target,
        ]
        try:
            subprocess.Popen(args)
        except OSError as e:
            return {"ok": False, "error": f"浏览器启动失败：{e}"}
        log.info("无痕浏览：%s（%s）", target, exe.name)
        return {
            "ok": True,
            "url": target,
            "browser": exe.name,
            "incognito": True,
            "output": f"已在无痕窗口打开：{target}",
        }

    # ---------- 内嵌浏览器 ----------
    def browser_embed_open(self, payload: dict | None = None) -> dict:
        data = payload or {}
        target = browser_target(str(data.get("url") or ""))
        if not target:
            return {"ok": False, "error": "地址无效：请输入网址、localhost 或本地文件路径"}
        return self._app.embedded.open(
            target, int(data.get("x") or 0), int(data.get("y") or 0),
            int(data.get("w") or 640), int(data.get("h") or 480),
        )

    def browser_embed_rect(self, payload: dict | None = None) -> dict:
        data = payload or {}
        return self._app.embedded.move(
            str(data.get("id") or ""), int(data.get("x") or 0), int(data.get("y") or 0),
            int(data.get("w") or 0), int(data.get("h") or 0),
        )

    def browser_embed_show(self, payload: dict | None = None) -> dict:
        data = payload or {}
        return self._app.embedded.show(str(data.get("id") or ""), bool(data.get("show")))

    def browser_embed_navigate(self, payload: dict | None = None) -> dict:
        data = payload or {}
        target = browser_target(str(data.get("url") or ""))
        if not target:
            return {"ok": False, "error": "地址无效：请输入网址、localhost 或本地文件路径"}
        return self._app.embedded.navigate(str(data.get("id") or ""), target)

    def browser_embed_act(self, payload: dict | None = None) -> dict:
        data = payload or {}
        return self._app.embedded.act(str(data.get("id") or ""), str(data.get("action") or ""))

    def browser_embed_info(self, payload: dict | None = None) -> dict:
        data = payload or {}
        return self._app.embedded.info(str(data.get("id") or ""))

    def browser_embed_close(self, payload: dict | None = None) -> dict:
        data = payload or {}
        return self._app.embedded.close(str(data.get("id") or ""))

    def browser_embed_close_all(self, payload: dict | None = None) -> dict:
        """页面重新加载时清掉上一轮遗留的原生子窗口，避免出现“幽灵网页”。"""
        self._app.embedded.close_all()
        return {"ok": True}

    # ---------- 终端 ----------
    def terminal_shells(self, payload: dict | None = None) -> dict:
        """返回本机检测到的终端类型（PowerShell / CMD / Git Bash / WSL 等）。"""
        return self._app.terminals.shells()

    def terminal_start(self, payload: dict | None = None) -> dict:
        """按需启动一个真的 CMD / PowerShell 伪终端，返回会话 id。"""
        data = payload or {}
        cwd = str(data.get("cwd") or "")
        if not cwd:
            cwd = str(self._app.config.output_dir)
            try:
                Path(cwd).mkdir(parents=True, exist_ok=True)
            except OSError:
                cwd = str(Path.home())
        return self._app.terminals.start(
            str(data.get("shell") or "powershell"), cwd,
            int(data.get("cols") or 100), int(data.get("rows") or 24),
        )

    def terminal_write(self, payload: dict | None = None) -> dict:
        data = payload or {}
        return self._app.terminals.write(str(data.get("id") or ""),
                                         str(data.get("data") or ""))

    def terminal_resize(self, payload: dict | None = None) -> dict:
        data = payload or {}
        return self._app.terminals.resize(str(data.get("id") or ""),
                                          int(data.get("cols") or 100),
                                          int(data.get("rows") or 24))

    def terminal_close(self, payload: dict | None = None) -> dict:
        data = payload or {}
        return self._app.terminals.close(str(data.get("id") or ""))

    def open_path(self, path: str) -> dict:
        target = str(path or "").strip()
        if not target:
            return {"ok": False, "error": "路径为空"}
        try:
            if not os.path.exists(target):
                return {"ok": False, "error": "文件不存在"}
            os.startfile(target)  # noqa: S606
            return {"ok": True}
        except OSError as e:
            return {"ok": False, "error": str(e)}

    def reveal_path(self, path: str) -> dict:
        target = Path(str(path or "")).expanduser()
        if not target.exists():
            return {"ok": False, "error": "文件不存在"}
        try:
            subprocess.Popen(["explorer", "/select,", str(target)])
            return {"ok": True}
        except OSError as e:
            return {"ok": False, "error": str(e)}

    # ---------- 历史 ----------
    def history_list(self, payload: dict | None = None) -> dict:
        payload = payload or {}
        kind = payload.get("kind") or "sessions"
        limit = int(payload.get("limit") or 40)
        if kind == "files":
            items = self._app.store.list_files(limit)
        elif kind == "tools":
            items = self._app.store.list_tool_runs(limit)
        else:
            items = self._app.store.list_sessions(limit)
        return {"ok": True, "items": items}

    def history_get(self, payload: dict) -> dict:
        sid = int((payload or {}).get("id") or 0)
        if not sid:
            return {"ok": False, "error": "缺少会话 id"}
        session = self._app.store.get_session(sid)
        if not session:
            return {"ok": False, "error": "会话不存在"}
        return {"ok": True, "session": session,
                "messages": self._app.store.messages(sid),
                "files": self._app.store.session_files(sid),
                "tool_runs": self._app.store.session_tool_runs(sid)}

    def history_delete(self, payload: dict) -> dict:
        sid = int((payload or {}).get("id") or 0)
        if not sid:
            return {"ok": False, "error": "缺少会话 id"}
        self._app.store.delete_session(sid)
        return {"ok": True}

    # ---------- 定时任务 ----------
    def schedule_list(self) -> dict:
        return {"ok": True, "items": self._app.store.list_schedules(50)}

    def schedule_delete(self, payload: dict) -> dict:
        sid = int((payload or {}).get("id") or 0)
        if not sid:
            return {"ok": False, "error": "缺少任务 id"}
        ok = self._app.store.delete_schedule(sid)
        return {"ok": ok, "error": "" if ok else "任务不存在"}

    def schedule_toggle(self, payload: dict) -> dict:
        sid = int((payload or {}).get("id") or 0)
        if not sid:
            return {"ok": False, "error": "缺少任务 id"}
        enabled = bool((payload or {}).get("enabled"))
        ok = self._app.store.set_schedule_enabled(sid, enabled)
        return {"ok": ok, "error": "" if ok else "任务不存在"}

    # ---------- 技能与记忆 ----------
    def skills(self, action: str = "list", payload: dict | None = None) -> dict:
        from .core.skills import Skills

        payload = payload or {}
        book = Skills(self._app.config)
        try:
            if action == "list":
                return {"ok": True, "items": book.list(), "dir": str(book.user_dir)}
            if action == "get":
                item = book.get(str(payload.get("id") or ""))
                return {"ok": bool(item), "skill": item}
            if action == "save":
                payload = dict(payload)
                if not str(payload.get("name") or "").strip():
                    from .core.naming import suggest_name

                    payload["name"] = suggest_name(
                        self._app.config, str(payload.get("body") or ""), "skill", 40)
                return book.save(payload)
            if action == "delete":
                return book.delete(str(payload.get("id") or ""))
            if action == "toggle":
                return book.set_enabled(str(payload.get("id") or ""), bool(payload.get("enabled")))
            if action == "open_dir":
                book.user_dir.mkdir(parents=True, exist_ok=True)
                os.startfile(str(book.user_dir))
                return {"ok": True, "dir": str(book.user_dir)}
        except OSError as exc:
            return {"ok": False, "error": f"操作失败：{exc}"}
        return {"ok": False, "error": "未知操作"}

    def prompts(self, action: str = "list", payload: dict | None = None) -> dict:
        from .core.prompt_library import PromptBook

        payload = payload or {}
        book = PromptBook(self._app.config)
        try:
            if action == "list":
                return {"ok": True, "items": book.list(), "dir": str(book.dir)}
            if action == "get":
                item = book.get(str(payload.get("id") or ""))
                return {"ok": bool(item), "prompt": item}
            if action == "save":
                payload = dict(payload)
                if not str(payload.get("name") or "").strip():
                    from .core.naming import suggest_name

                    payload["name"] = suggest_name(
                        self._app.config, str(payload.get("body") or ""), "prompt", 60)
                return book.save(payload)
            if action == "delete":
                return book.delete(str(payload.get("id") or ""))
            if action == "toggle":
                return book.set_enabled(str(payload.get("id") or ""), bool(payload.get("enabled")))
            if action == "open_dir":
                book.dir.mkdir(parents=True, exist_ok=True)
                os.startfile(str(book.dir))
                return {"ok": True, "dir": str(book.dir)}
        except OSError as exc:
            return {"ok": False, "error": f"操作失败：{exc}"}
        return {"ok": False, "error": "未知操作"}

    def memory(self, action: str = "list", payload: dict | None = None) -> dict:
        payload = payload or {}
        store = self._app.store
        try:
            if action == "list":
                return {"ok": True, "items": store.memories(200)}
            if action == "add":
                mid = store.add_memory(
                    str(payload.get("text") or ""),
                    str(payload.get("category") or "preference"),
                    getattr(self._app, "_run_session_id", None),
                )
                return {"ok": True, "id": mid, "items": store.memories(200)}
            if action == "update":
                ok = store.update_memory(int(payload.get("id") or 0),
                                         str(payload.get("text") or ""),
                                         payload.get("category"))
                if not ok:
                    return {"ok": False, "error": "记忆不存在"}
                return {"ok": True, "items": store.memories(200)}
            if action == "delete":
                ok = store.delete_memory(int(payload.get("id") or 0))
                if not ok:
                    return {"ok": False, "error": "记忆不存在"}
                return {"ok": True, "items": store.memories(200)}
            if action == "clear":
                return {"ok": True, "removed": store.clear_memories(), "items": []}
        except (TypeError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": False, "error": "未知操作"}

    # ---------- 截图 ----------
    def _pick_region(self) -> dict | None:
        out = self._app.config.dir / f".region_{os.getpid()}.json"
        try:
            out.unlink()
        except OSError:
            pass
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--pick-region", str(out)]
        else:
            cmd = [sys.executable, str(Path(__file__).resolve().with_name("main.py")),
                   "--pick-region", str(out)]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        try:
            subprocess.run(cmd, timeout=120, creationflags=flags, check=False)
        except (OSError, subprocess.TimeoutExpired) as e:
            log.warning("区域框选启动失败：%s", e)
            return None
        time.sleep(0.15)
        try:
            data = json.loads(out.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        finally:
            try:
                out.unlink()
            except OSError:
                pass
        if not isinstance(data, dict) or data.get("cancelled"):
            return None
        return data

    def capture_screen(self, payload: dict | None = None) -> dict:
        try:
            from PIL import ImageGrab
        except ImportError:
            return {"ok": False, "error": "缺少截图组件"}
        payload = payload if isinstance(payload, dict) else {}
        region = payload.get("region")
        img = None
        if payload.get("mode") == "region" and not region:
            region = self._pick_region()
            if not region:
                return {"ok": False, "cancelled": True, "error": "已取消截图"}
        try:
            img = ImageGrab.grab(all_screens=True)
        except OSError as e:
            return {"ok": False, "error": f"截图失败：{e}"}
        if region:
            from .core.region import normalize_region

            bounds = {"left": 0, "top": 0, "width": img.width, "height": img.height}
            norm = normalize_region(region, bounds)
            if not norm:
                return {"ok": False, "error": "框选区域太小或无效"}
            try:
                img = img.crop((
                    norm["left"] - bounds["left"], norm["top"] - bounds["top"],
                    norm["right"] - bounds["left"], norm["bottom"] - bounds["top"],
                ))
            except Exception as e:
                return {"ok": False, "error": f"裁剪失败：{e}"}
        if img.width > 1600:
            ratio = 1600 / img.width
            img = img.resize((1600, int(img.height * ratio)))
        buf = io.BytesIO()
        img.save(buf, "PNG", optimize=True)
        raw = buf.getvalue()
        if len(raw) > 4 * 1024 * 1024:
            return {"ok": False, "error": "截图太大，请缩小窗口后重试"}
        audit = {"size": img.size, "bytes": len(raw)}
        if region:
            audit["region"] = region
        self._app.safety.audit("capture_screen", audit)
        b64 = base64.b64encode(raw).decode("ascii")
        result = {
            "ok": True,
            "base64": b64,
            "data_url": "data:image/png;base64," + b64,
            "width": img.width,
            "height": img.height,
        }
        if region:
            result["region"] = region
        return result

    def quit_app(self) -> dict:
        threading.Timer(0.2, self._app.quit).start()
        return {"ok": True}


def launch(config: Config, store: Store, safety: Safety, registry: Registry,
           debug: bool = False) -> int:
    return NexusApp(config, store, safety, registry, debug=debug).launch()

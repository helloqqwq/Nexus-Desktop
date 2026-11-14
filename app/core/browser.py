"""内嵌浏览器：运行时创建 pywebview 窗口，再把它挂成主窗口的子窗口。

这样右侧面板里显示的是真正的 WebView2（不是 iframe），主流站点的
X-Frame-Options / CSP 不会拦截；子窗口跟着主窗口一起移动、最小化和销毁。
"""
from __future__ import annotations

import ctypes
import logging
import time
import uuid
from ctypes import wintypes

import webview

log = logging.getLogger("nexus.browser")

user32 = ctypes.windll.user32
GWL_STYLE = -16
WS_CHILD = 0x40000000
WS_POPUP = 0x80000000
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
SW_HIDE = 0
SW_SHOW = 5
HWND_TOP = 0

user32.GetWindowLongW.restype = ctypes.c_long
user32.SetWindowLongW.restype = ctypes.c_long
user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
user32.MoveWindow.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, ctypes.c_int, wintypes.BOOL]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetParent.argtypes = [wintypes.HWND]
user32.GetParent.restype = wintypes.HWND
user32.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]

_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def _find_window(title: str) -> int:
    found: list[int] = []

    def _cb(hwnd, _lparam):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        if buf.value == title:
            found.append(int(hwnd))
        return True

    user32.EnumWindows(_WNDENUMPROC(_cb), 0)
    return found[0] if found else 0


def _wait_window(title: str, timeout: float = 8.0) -> int:
    deadline = time.time() + timeout
    while time.time() < deadline:
        hwnd = _find_window(title)
        if hwnd:
            return hwnd
        time.sleep(0.05)
    return 0


class BrowserView:
    def __init__(self, uid: str, token: str, window, hwnd: int):
        self.id = uid
        self.token = token
        self.window = window
        self.hwnd = hwnd
        self.visible = True

    def move(self, x: int, y: int, w: int, h: int) -> None:
        if not self.hwnd:
            return
        user32.MoveWindow(self.hwnd, int(x), int(y), max(80, int(w)), max(60, int(h)), True)

    def show(self, visible: bool) -> None:
        if not self.hwnd:
            return
        self.visible = bool(visible)
        user32.ShowWindow(self.hwnd, SW_SHOW if visible else SW_HIDE)

    def navigate(self, url: str) -> None:
        try:
            self.window.load_url(url)
        except Exception:
            log.debug("内嵌浏览器跳转失败", exc_info=True)

    def act(self, action: str) -> None:
        script = {
            "reload": "location.reload()",
            "back": "history.back()",
            "forward": "history.forward()",
        }.get(action)
        if not script:
            return
        try:
            self.window.evaluate_js(script)
        except Exception:
            log.debug("内嵌浏览器动作失败：%s", action, exc_info=True)

    def info(self) -> dict:
        url = ""
        title = ""
        for attempt in range(2):
            try:
                url = str(self.window.evaluate_js("document.URL") or "")
            except Exception:
                url = ""
            if url:
                break
            time.sleep(0.12)
        try:
            title = str(self.window.evaluate_js("document.title") or "")
        except Exception:
            title = ""
        return {"url": url, "title": title}

    def close(self) -> None:
        try:
            if self.hwnd:
                user32.ShowWindow(self.hwnd, SW_HIDE)
        except OSError:
            pass
        try:
            self.window.destroy()
        except Exception:
            log.debug("销毁内嵌浏览器失败", exc_info=True)


class BrowserHost:
    """管理所有内嵌浏览器子窗口。"""

    def __init__(self, main_hwnd):
        self._main_hwnd = main_hwnd
        self._views: dict[str, BrowserView] = {}

    def open(self, url: str, x: int, y: int, w: int, h: int) -> dict:
        parent = int(self._main_hwnd() or 0)
        if not parent:
            return {"ok": False, "error": "找不到主窗口，暂时无法内嵌浏览器"}
        uid = "br" + uuid.uuid4().hex[:8]
        token = "NexusBrowser-" + uid
        try:
            win = webview.create_window(
                token, url or "about:blank",
                width=max(120, int(w)), height=max(80, int(h)),
                frameless=True, hidden=True, focus=False,
                min_size=(120, 80), background_color="#0f1114",
            )
        except Exception as e:
            log.exception("创建内嵌浏览器窗口失败")
            return {"ok": False, "error": f"创建浏览器窗口失败：{e}"}
        hwnd = _wait_window(token)
        if not hwnd:
            try:
                win.destroy()
            except Exception:
                pass
            return {"ok": False, "error": "浏览器窗口没有成功创建"}
        style = user32.GetWindowLongW(hwnd, GWL_STYLE)
        user32.SetWindowLongW(hwnd, GWL_STYLE,
                              (style | WS_CHILD) & ~WS_CAPTION & ~WS_THICKFRAME & ~WS_POPUP)
        user32.SetParent(hwnd, parent)
        view = BrowserView(uid, token, win, hwnd)
        view.move(x, y, w, h)
        view.show(True)
        self._views[uid] = view
        return {"ok": True, "id": uid, "hwnd": hwnd}

    def get(self, uid: str) -> BrowserView | None:
        return self._views.get(str(uid or ""))

    def move(self, uid: str, x: int, y: int, w: int, h: int) -> dict:
        view = self.get(uid)
        if not view:
            return {"ok": False, "error": "浏览器标签已关闭"}
        view.move(x, y, w, h)
        return {"ok": True}

    def show(self, uid: str, visible: bool) -> dict:
        view = self.get(uid)
        if not view:
            return {"ok": False, "error": "浏览器标签已关闭"}
        view.show(visible)
        return {"ok": True}

    def navigate(self, uid: str, url: str) -> dict:
        view = self.get(uid)
        if not view:
            return {"ok": False, "error": "浏览器标签已关闭"}
        view.navigate(url)
        return {"ok": True}

    def act(self, uid: str, action: str) -> dict:
        view = self.get(uid)
        if not view:
            return {"ok": False, "error": "浏览器标签已关闭"}
        view.act(str(action or ""))
        return {"ok": True}

    def info(self, uid: str) -> dict:
        view = self.get(uid)
        if not view:
            return {"ok": False, "error": "浏览器标签已关闭"}
        data = view.info()
        return {"ok": True, **data}

    def close(self, uid: str) -> dict:
        view = self._views.pop(str(uid or ""), None)
        if view:
            view.close()
        return {"ok": True}

    def hide_all(self) -> None:
        for view in list(self._views.values()):
            view.show(False)

    def close_all(self) -> None:
        for uid in list(self._views.keys()):
            self.close(uid)

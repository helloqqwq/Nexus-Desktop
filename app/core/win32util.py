"""Win32 窗口位置工具。

不要给 ``user32.SetWindowPos`` 设置全局 argtypes：pywebview 自己的拖动逻辑会
传入 ``None`` 作为宽高，全局 argtypes 会让它抛 ``TypeError``。这里显式构造
64 位 HWND 与 c_int 参数，既避免句柄截断，也不污染其他库的调用。
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes


def set_window_pos(hwnd: int, insert_after: int, x: int, y: int,
                   cx: int, cy: int, flags: int) -> None:
    if not hwnd:
        return
    ctypes.windll.user32.SetWindowPos(
        wintypes.HWND(int(hwnd)),
        wintypes.HWND(int(insert_after)),
        ctypes.c_int(int(x)),
        ctypes.c_int(int(y)),
        ctypes.c_int(int(cx)),
        ctypes.c_int(int(cy)),
        wintypes.UINT(int(flags)),
    )

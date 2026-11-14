"""轻量资源监控：后端进程、整棵应用进程树、系统 CPU 与内存。

不依赖 psutil：
- Windows 通过 kernel32 / psapi 读取进程树、CPU 时间和工作集；
- 其他平台退化为当前进程的 process_time + /proc 内存，保证监控本身不会拖垮应用。

CPU 百分比按逻辑核心数归一化；系统 CPU 除外（直接是整机占用率）。
"""
from __future__ import annotations

import ctypes
import os
import threading
import time
from ctypes import wintypes
from pathlib import Path

_IS_WIN = os.name == "nt"
_CORES = max(1, os.cpu_count() or 1)
_MB = 1024 * 1024

if _IS_WIN:
    class _FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", wintypes.DWORD),
                    ("dwHighDateTime", wintypes.DWORD)]

    class _PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    class _PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
            ("PrivateUsage", ctypes.c_size_t),
        ]

    class _MEMORYSTATUSEX(ctypes.Structure):
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

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _psapi = ctypes.WinDLL("psapi", use_last_error=True)

    _kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    _kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    _kernel32.Process32FirstW.argtypes = [ctypes.c_void_p,
                                          ctypes.POINTER(_PROCESSENTRY32W)]
    _kernel32.Process32FirstW.restype = wintypes.BOOL
    _kernel32.Process32NextW.argtypes = [ctypes.c_void_p,
                                         ctypes.POINTER(_PROCESSENTRY32W)]
    _kernel32.Process32NextW.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.OpenProcess.restype = ctypes.c_void_p
    _kernel32.GetProcessTimes.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(_FILETIME), ctypes.POINTER(_FILETIME),
        ctypes.POINTER(_FILETIME), ctypes.POINTER(_FILETIME),
    ]
    _kernel32.GetProcessTimes.restype = wintypes.BOOL
    _kernel32.GetSystemTimes.argtypes = [
        ctypes.POINTER(_FILETIME), ctypes.POINTER(_FILETIME),
        ctypes.POINTER(_FILETIME),
    ]
    _kernel32.GetSystemTimes.restype = wintypes.BOOL
    _kernel32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(_MEMORYSTATUSEX)]
    _kernel32.GlobalMemoryStatusEx.restype = wintypes.BOOL
    _psapi.GetProcessMemoryInfo.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(_PROCESS_MEMORY_COUNTERS_EX),
        wintypes.DWORD,
    ]
    _psapi.GetProcessMemoryInfo.restype = wintypes.BOOL

    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _TH32CS_SNAPPROCESS = 0x00000002
    _INVALID_HANDLE = ctypes.c_void_p(-1).value


def _filetime_seconds(value: "_FILETIME") -> float:
    ticks = (int(value.dwHighDateTime) << 32) | int(value.dwLowDateTime)
    return ticks / 10_000_000.0


if _IS_WIN:
    def _process_table() -> dict[int, tuple[int, int, str]]:
        """返回 pid -> (父 pid, 线程数, 进程名)。"""
        snapshot = _kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
        if not snapshot or snapshot == _INVALID_HANDLE:
            return {}
        table: dict[int, tuple[int, int, str]] = {}
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        try:
            ok = _kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
            while ok:
                table[int(entry.th32ProcessID)] = (
                    int(entry.th32ParentProcessID),
                    int(entry.cntThreads),
                    str(entry.szExeFile),
                )
                ok = _kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            _kernel32.CloseHandle(snapshot)
        return table

    def _tree_pids(root: int, table: dict[int, tuple[int, int, str]]) -> list[int]:
        children: dict[int, list[int]] = {}
        for pid, (ppid, _threads, _name) in table.items():
            children.setdefault(ppid, []).append(pid)
        out: list[int] = []
        seen: set[int] = set()
        stack = [root]
        while stack:
            pid = stack.pop()
            if pid in seen:
                continue
            seen.add(pid)
            out.append(pid)
            stack.extend(children.get(pid, ()))
        return out

    def _process_cpu(pid: int) -> float | None:
        handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return None
        try:
            created = _FILETIME()
            exited = _FILETIME()
            kernel = _FILETIME()
            user = _FILETIME()
            if not _kernel32.GetProcessTimes(
                    handle, ctypes.byref(created), ctypes.byref(exited),
                    ctypes.byref(kernel), ctypes.byref(user)):
                return None
            return _filetime_seconds(kernel) + _filetime_seconds(user)
        finally:
            _kernel32.CloseHandle(handle)

    def _process_mem(pid: int) -> tuple[float, float]:
        handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return 0.0, 0.0
        try:
            counters = _PROCESS_MEMORY_COUNTERS_EX()
            counters.cb = ctypes.sizeof(counters)
            if not _psapi.GetProcessMemoryInfo(
                    handle, ctypes.byref(counters), counters.cb):
                return 0.0, 0.0
            return (counters.WorkingSetSize / _MB,
                    counters.PrivateUsage / _MB)
        finally:
            _kernel32.CloseHandle(handle)

    def _system_cpu() -> tuple[float, float]:
        idle = _FILETIME()
        kernel = _FILETIME()
        user = _FILETIME()
        if not _kernel32.GetSystemTimes(
                ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            return 0.0, 0.0
        idle_s = _filetime_seconds(idle)
        total_s = _filetime_seconds(kernel) + _filetime_seconds(user)
        return max(0.0, total_s - idle_s), total_s

    def _system_mem() -> tuple[float, float, int]:
        status = _MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(status)
        if not _kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return 0.0, 0.0, 0
        total = status.ullTotalPhys / _MB
        avail = status.ullAvailPhys / _MB
        return total, max(0.0, total - avail), int(status.dwMemoryLoad)


def _linux_rss_mb() -> float:
    try:
        for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return float(line.split()[1]) / 1024.0
    except (OSError, ValueError, IndexError):
        pass
    return 0.0


def _linux_system_cpu() -> tuple[float, float]:
    try:
        parts = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0].split()
        values = [int(v) for v in parts[1:]]
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        total = sum(values)
        return float(total - idle), float(total)
    except (OSError, ValueError, IndexError):
        return 0.0, 0.0


def _linux_system_mem() -> tuple[float, float, int]:
    try:
        info: dict[str, float] = {}
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, _, rest = line.partition(":")
            info[key] = float(rest.strip().split()[0]) / 1024.0
        total = info.get("MemTotal", 0.0)
        available = info.get("MemAvailable", info.get("MemFree", 0.0))
        used = max(0.0, total - available)
        pct = int(round(used / total * 100)) if total else 0
        return total, used, pct
    except (OSError, ValueError, IndexError):
        return 0.0, 0.0, 0


class ResourceMonitor:
    """采样当前后端、整棵应用进程树和系统资源。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last: dict | None = None
        self._run: dict | None = None
        self._last_run: dict | None = None
        self._started = time.perf_counter()

    # ---------- 采样 ----------
    def _read(self) -> dict:
        now = time.perf_counter()
        pid = os.getpid()
        if _IS_WIN:
            table = _process_table()
            tree = _tree_pids(pid, table) or [pid]
            cpu_map = {}
            for item in tree:
                value = _process_cpu(item)
                if value is not None:
                    cpu_map[item] = value
            mem_map = {item: _process_mem(item) for item in tree}
            threads = table.get(pid, (0, 0, ""))[1]
            system_cpu = _system_cpu()
            system_mem = _system_mem()
        else:
            tree = [pid]
            cpu_map = {pid: time.process_time()}
            mem_map = {pid: (_linux_rss_mb(), 0.0)}
            threads = threading.active_count()
            system_cpu = _linux_system_cpu()
            system_mem = _linux_system_mem()

        backend_mem = mem_map.get(pid, (0.0, 0.0))
        app_mem = sum(item[0] for item in mem_map.values())
        app_private = sum(item[1] for item in mem_map.values())
        return {
            "ts": now,
            "tree": tree,
            "cpu": cpu_map,
            "mem": mem_map,
            "backend_mem": backend_mem,
            "app_mem": app_mem,
            "app_private": app_private,
            "processes": len(tree),
            "threads": threads,
            "system_cpu": system_cpu,
            "system_mem": system_mem,
        }

    @staticmethod
    def _cpu_percent(delta: float, elapsed: float) -> float:
        if elapsed <= 0:
            return 0.0
        return round(max(0.0, delta) / elapsed / _CORES * 100.0, 2)

    def snapshot(self) -> dict:
        raw = self._read()
        pid = os.getpid()
        backend_cpu = 0.0
        app_cpu = 0.0
        system_cpu = 0.0
        with self._lock:
            previous = self._last
            if previous:
                elapsed = raw["ts"] - previous["ts"]
                if elapsed > 0:
                    backend_cpu = self._cpu_percent(
                        raw["cpu"].get(pid, 0.0) - previous["cpu"].get(pid, 0.0),
                        elapsed)
                    app_delta = 0.0
                    for item, value in raw["cpu"].items():
                        app_delta += max(0.0, value - previous["cpu"].get(item, 0.0))
                    app_cpu = self._cpu_percent(app_delta, elapsed)
                    busy_delta = raw["system_cpu"][0] - previous["system_cpu"][0]
                    total_delta = raw["system_cpu"][1] - previous["system_cpu"][1]
                    if total_delta > 0:
                        system_cpu = round(max(0.0, busy_delta) / total_delta * 100.0, 2)
            self._last = raw
            last_run = dict(self._last_run) if self._last_run else None

        total_mem, used_mem, mem_pct = raw["system_mem"]
        return {
            "ok": True,
            "platform": "windows" if _IS_WIN else os.name,
            "full": _IS_WIN,
            "pid": pid,
            "uptime_s": round(raw["ts"] - self._started, 1),
            "backend": {
                "cpu_percent": backend_cpu,
                "mem_mb": round(raw["backend_mem"][0], 1),
                "private_mb": round(raw["backend_mem"][1], 1),
                "threads": raw["threads"],
            },
            "app": {
                "cpu_percent": app_cpu,
                "mem_mb": round(raw["app_mem"], 1),
                "private_mb": round(raw["app_private"], 1),
                "processes": raw["processes"],
            },
            "system": {
                "cpu_percent": system_cpu,
                "mem_total_mb": round(total_mem, 1),
                "mem_used_mb": round(used_mem, 1),
                "mem_percent": mem_pct,
            },
            "last_run": last_run,
        }

    # ---------- 单次对话统计 ----------
    def begin_run(self) -> None:
        raw = self._read()
        with self._lock:
            self._run = {"t0": time.perf_counter(), "cpu0": dict(raw["cpu"])}

    def end_run(self) -> None:
        raw = self._read()
        now = time.perf_counter()
        with self._lock:
            run = self._run
            self._run = None
            if not run:
                return
            elapsed = max(0.001, now - run["t0"])
            delta = 0.0
            for item, value in raw["cpu"].items():
                previous = run["cpu0"].get(item)
                delta += value if previous is None else max(0.0, value - previous)
            self._last_run = {
                "avg_cpu_percent": self._cpu_percent(delta, elapsed),
                "duration_s": round(elapsed, 2),
                "mem_mb": round(raw["app_mem"], 1),
            }

"""伪终端：用 ConPTY（pywinpty）跑真正的 shell，并把输出推给界面。"""
from __future__ import annotations

import logging
import os
import shutil
import threading
import uuid
import winreg

log = logging.getLogger("nexus.term")

SYSTEM_ROOT = os.environ.get("SystemRoot") or r"C:\Windows"
FLUSH_MS = 30          # 输出合批间隔，避免逐字符 evaluate_js
MAX_PENDING = 200_000  # 单次合批上限，防止极端输出刷爆界面

_SHELLS: list[dict] | None = None


def _is_file(path: str) -> bool:
    return bool(path) and os.path.isfile(path)


def _find_git_bash() -> str:
    """Git for Windows 自带 bash.exe；优先常见安装位置，再退回 PATH。"""
    candidates: list[str] = []
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"),
                 os.environ.get("LOCALAPPDATA")):
        if not base:
            continue
        candidates.append(os.path.join(base, "Git", "bin", "bash.exe"))
        candidates.append(os.path.join(base, "Programs", "Git", "bin", "bash.exe"))
    candidates.append(shutil.which("bash") or "")
    for path in candidates:
        if _is_file(path):
            return path
    return ""


def shell_list() -> list[dict]:
    """按本机实际安装情况探测可用终端类型，结果缓存到进程结束。"""
    global _SHELLS
    if _SHELLS is not None:
        return _SHELLS
    items: list[dict] = []

    ps5 = os.path.join(SYSTEM_ROOT, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    if _is_file(ps5):
        items.append({"id": "powershell", "label": "PowerShell", "hint": "5.1", "badge": "PS",
                      "argv": [ps5, "-NoLogo", "-NoProfile"]})

    pwsh = shutil.which("pwsh") or ""
    if _is_file(pwsh):
        items.append({"id": "pwsh", "label": "PowerShell 7", "hint": "pwsh", "badge": "PS7",
                      "argv": [pwsh, "-NoLogo", "-NoProfile"]})

    cmd = os.path.join(SYSTEM_ROOT, "System32", "cmd.exe")
    if _is_file(cmd):
        items.append({"id": "cmd", "label": "命令提示符", "hint": "cmd.exe", "badge": "CMD",
                      "argv": [cmd]})

    bash = _find_git_bash()
    if bash:
        items.append({"id": "gitbash", "label": "Git Bash", "hint": "Git for Windows", "badge": "GIT",
                      "argv": [bash, "--login", "-i"]})

    wsl = os.path.join(SYSTEM_ROOT, "System32", "wsl.exe")
    if _is_file(wsl) and _wsl_has_distro():
        items.append({"id": "wsl", "label": "WSL", "hint": "Linux", "badge": "WSL",
                      "argv": [wsl]})

    _SHELLS = items
    return items


def shell_info(sid: str) -> dict | None:
    for item in shell_list():
        if item["id"] == sid:
            return item
    return None


def _wsl_has_distro() -> bool:
    """wsl.exe 存在不代表能用：没有安装分发时启动只会打印错误。

    这里读注册表而不是执行 `wsl -l -q`：在 GUI 进程里启动 wsl.exe 可能长时间
    阻塞，而 pywebview 的接口调用是单线程的，会把整个界面一起卡住。
    """
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Lxss") as key:
            winreg.EnumKey(key, 0)
            return True
    except (OSError, ImportError):
        return False


def default_shell() -> str:
    items = shell_list()
    return items[0]["id"] if items else "cmd"


class TerminalSession:
    """一个伪终端会话：启动、写入、缩放、读取线程。"""

    def __init__(self, sid: str, shell: str, argv: list[str], cwd: str,
                 cols: int, rows: int, on_data, on_exit):
        self.id = sid
        self.shell = shell
        self.argv = argv
        self.cwd = cwd
        self.cols = max(20, min(int(cols or 100), 400))
        self.rows = max(5, min(int(rows or 24), 200))
        self.pid = 0
        self._on_data = on_data
        self._on_exit = on_exit
        self._proc = None
        self._thread: threading.Thread | None = None
        self._closed = threading.Event()
        self._write_lock = threading.Lock()

    def start(self) -> None:
        from winpty import PtyProcess

        self._proc = PtyProcess.spawn(
            self.argv,
            dimensions=(self.rows, self.cols),
            cwd=self.cwd or None,
        )
        self.pid = int(getattr(self._proc, "pid", 0) or 0)
        self._thread = threading.Thread(target=self._reader, name=f"term-{self.id}",
                                        daemon=True)
        self._thread.start()

    def _reader(self) -> None:
        while not self._closed.is_set():
            try:
                chunk = self._proc.read(4096)
            except (EOFError, OSError, ValueError):
                break
            if not chunk:
                break
            try:
                self._on_data(self.id, chunk)
            except Exception:
                log.debug("终端输出推送失败", exc_info=True)
        self._closed.set()
        try:
            self._on_exit(self.id)
        except Exception:
            log.debug("终端退出回调失败", exc_info=True)

    def write(self, data: str) -> bool:
        if self._closed.is_set() or self._proc is None or not data:
            return False
        try:
            with self._write_lock:
                self._proc.write(data)
            return True
        except (OSError, ValueError, EOFError):
            return False

    def resize(self, cols: int, rows: int) -> bool:
        if self._closed.is_set() or self._proc is None:
            return False
        self.cols = max(20, min(int(cols or 100), 400))
        self.rows = max(5, min(int(rows or 24), 200))
        try:
            self._proc.setwinsize(self.rows, self.cols)
            return True
        except (OSError, ValueError):
            return False

    def close(self) -> None:
        self._closed.set()
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            proc.terminate(force=True)
        except (OSError, ValueError):
            log.debug("结束终端进程失败", exc_info=True)

    @property
    def alive(self) -> bool:
        return not self._closed.is_set()


class TerminalHub:
    """管理多个终端会话，按 30ms 合批把输出推给前端。"""

    def __init__(self, push):
        self._push = push
        self._sessions: dict[str, TerminalSession] = {}
        self._pending: dict[str, list[str]] = {}
        self._lock = threading.Lock()
        self._flush_lock = threading.Lock()
        self._timer: threading.Timer | None = None

    # ---------- 对外 ----------
    def shells(self) -> dict:
        items = [{"id": s["id"], "label": s["label"], "hint": s["hint"], "badge": s["badge"]}
                 for s in shell_list()]
        return {"ok": True, "items": items, "default": default_shell()}

    def start(self, shell: str, cwd: str, cols: int, rows: int) -> dict:
        shell = str(shell or default_shell()).lower()
        info = shell_info(shell)
        if info is None:
            info = shell_info(default_shell())
        if info is None:
            return {"ok": False, "error": "本机没有可用的终端类型"}
        shell = info["id"]
        sid = "t" + uuid.uuid4().hex[:10]
        session = TerminalSession(sid, shell, info["argv"], cwd, cols, rows,
                                  self._on_data, self._on_exit)
        try:
            session.start()
        except Exception as e:
            log.exception("启动终端失败")
            return {"ok": False, "error": f"启动终端失败：{e}"}
        with self._lock:
            self._sessions[sid] = session
        return {"ok": True, "id": sid, "pid": session.pid, "shell": shell,
                "cwd": cwd}

    def write(self, sid: str, data: str) -> dict:
        session = self._get(sid)
        if session is None:
            return {"ok": False, "error": "终端已关闭"}
        return {"ok": session.write(str(data or ""))}

    def resize(self, sid: str, cols: int, rows: int) -> dict:
        session = self._get(sid)
        if session is None:
            return {"ok": False, "error": "终端已关闭"}
        return {"ok": session.resize(cols, rows)}

    def close(self, sid: str) -> dict:
        with self._lock:
            session = self._sessions.pop(sid, None)
        if session is None:
            return {"ok": True}
        session.close()
        with self._lock:
            self._pending.pop(sid, None)
        return {"ok": True}

    def close_all(self) -> None:
        with self._lock:
            items = list(self._sessions.values())
            self._sessions.clear()
            self._pending.clear()
        for session in items:
            session.close()

    def count(self) -> int:
        with self._lock:
            return len(self._sessions)

    # ---------- 内部 ----------
    def _get(self, sid: str) -> TerminalSession | None:
        with self._lock:
            return self._sessions.get(str(sid or ""))

    def _on_data(self, sid: str, text: str) -> None:
        with self._lock:
            if sid not in self._sessions:
                return
            buf = self._pending.setdefault(sid, [])
            buf.append(text)
            size = sum(len(x) for x in buf)
            if size > MAX_PENDING:
                del buf[: max(0, len(buf) - 50)]
            need_timer = self._timer is None
            if need_timer:
                self._timer = threading.Timer(FLUSH_MS / 1000.0, self._flush)
                self._timer.daemon = True
                self._timer.start()

    def _flush(self) -> None:
        with self._flush_lock:
            with self._lock:
                self._timer = None
                pending = self._pending
                self._pending = {}
            for sid, parts in pending.items():
                data = "".join(parts)
                if not data:
                    continue
                try:
                    self._push({"type": "term_data", "id": sid, "data": data})
                except Exception:
                    log.debug("推送终端输出失败", exc_info=True)

    def _on_exit(self, sid: str) -> None:
        with self._lock:
            self._sessions.pop(sid, None)
            self._pending.pop(sid, None)
        try:
            self._push({"type": "term_exit", "id": sid})
        except Exception:
            log.debug("推送终端退出失败", exc_info=True)

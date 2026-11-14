"""文件读写工具（全部经过路径沙箱）。"""
from __future__ import annotations

import ctypes
import difflib
import fnmatch
import os
import re
import time
from ctypes import wintypes
from pathlib import Path

from ..config import Config
from ..safety import Safety
from .registry import Registry, Tool

MAX_READ_LINES = 800
MAX_READ_CHARS = 3000
MAX_WRITE_BYTES = 2 * 1024 * 1024
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "appdata",
             "$recycle.bin", "windows", "system32", ".idea", ".vscode"}

FO_DELETE = 3
FOF_ALLOWUNDO = 0x0040
FOF_NOCONFIRMATION = 0x0010
FOF_SILENT = 0x0004
FOF_NOERRORUI = 0x0400
FOF_WANTNUKEWARNING = 0x4000


class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", wintypes.WORD),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


def _recycle(paths: list[Path]) -> tuple[bool, str]:
    """调用 Windows Shell 把文件移入回收站（不永久删除）。"""
    if os.name != "nt":
        return False, "回收站功能仅支持 Windows"
    # pFrom 需要双 \0 结尾
    payload = "\0".join(str(p) for p in paths) + "\0\0"
    op = _SHFILEOPSTRUCTW()
    op.hwnd = None
    op.wFunc = FO_DELETE
    op.pFrom = payload
    op.pTo = None
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI | FOF_WANTNUKEWARNING
    shell32 = ctypes.windll.shell32
    shell32.SHFileOperationW.argtypes = [ctypes.POINTER(_SHFILEOPSTRUCTW)]
    shell32.SHFileOperationW.restype = ctypes.c_int
    code = shell32.SHFileOperationW(ctypes.byref(op))
    if code != 0:
        return False, f"回收站操作失败（错误码 {code}）"
    if op.fAnyOperationsAborted:
        return False, "操作被系统取消"
    return True, ""


def _decode_raw(raw: bytes) -> str:
    # UTF-16 带 BOM 的文本（记事本“Unicode”）含大量 0x00，必须先按 BOM 解码，
    # 否则会被误判成二进制。
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", "replace")
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def _text_of(path: Path, limit_bytes: int = 1024 * 1024) -> str:
    with path.open("rb") as f:
        raw = f.read(limit_bytes)
    return _decode_raw(raw)


def _is_binary(raw: bytes) -> bool:
    if raw.startswith((b"\xff\xfe", b"\xfe\xff", b"\xef\xbb\xbf")):
        return False
    return b"\x00" in raw[:4096]


def _document_of(path: Path, limit_bytes: int = 1024 * 1024) -> tuple[str, str]:
    """读出文本并保留原编码；修改后用同一编码写回，避免换行/ BOM 被改写。"""
    with path.open("rb") as f:
        raw = f.read(limit_bytes)
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", "replace"), "utf-8-sig"
    if raw.startswith(b"\xff\xfe"):
        return raw.decode("utf-16", "replace"), "utf-16-le"
    if raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16", "replace"), "utf-16-be"
    for enc in ("utf-8", "gbk", "mbcs"):
        try:
            return raw.decode(enc), enc
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "replace"), "utf-8"


def _line_stats(old: str, new: str) -> tuple[int, int]:
    """按行统计这次改动新增/删除了多少行；超大文件退化为行数差，避免卡顿。"""
    old_lines = old.splitlines()
    new_lines = new.splitlines()
    if old == new:
        return 0, 0
    if len(old_lines) > 4000 or len(new_lines) > 4000:
        delta = len(new_lines) - len(old_lines)
        return max(0, delta), max(0, -delta)
    added = removed = 0
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "delete"):
            removed += i2 - i1
        if tag in ("replace", "insert"):
            added += j2 - j1
    return added, removed


def _write_failure(path: Path, err: OSError) -> dict:
    """把 Python 原始异常换成能看懂的中文说明。"""
    if isinstance(err, PermissionError) or getattr(err, "errno", None) == 13:
        try:
            if path.exists() and not os.access(path, os.W_OK):
                return {
                    "ok": False,
                    "denied": True,
                    "error": f"没有写入权限：{path}",
                    "hint": "文件可能是只读属性，或正被其他程序占用；取消只读后重试。",
                }
        except OSError:
            pass
        return {
            "ok": False,
            "denied": True,
            "error": f"目录没有写入权限：{path.parent}",
            "hint": "换一个目录，或在系统设置里给当前用户授予写入权限。",
        }
    return {"ok": False, "error": f"写入失败：{err}"}


def _line_ending(text: str) -> str:
    if "\r\n" in text:
        return "CRLF"
    if "\n" in text or "\r" in text:
        return "LF"
    return "NONE"


def _cap_note(requested: int, effective: int) -> str:
    if requested > effective:
        return (f"单次最多返回 {effective} 条（max_results={requested} 已按上限截断），"
                "结果可能不完整；请缩小目录范围。")
    return f"已达到 max_results={effective}，结果可能不完整；请缩小目录范围或调大 max_results。"


def register(reg: Registry, config: Config, safety: Safety) -> None:
    def fs_read(args: dict) -> dict:
        path = safety.resolve(args.get("path", ""), for_write=False)
        if not path.exists():
            return {"ok": False, "error": f"文件不存在：{path}"}
        if path.is_dir():
            return {"ok": False, "error": f"这是文件夹，请用 fs_list：{path}"}
        with path.open("rb") as f:
            raw = f.read(1024 * 1024)
        if _is_binary(raw):
            return {
                "ok": False,
                "binary": True,
                "path": str(path),
                "bytes": len(raw),
                "error": "这是二进制文件，不能按文本读取",
                "hint": "图片/程序/压缩包等请直接打开；需要十六进制内容可改用 shell_exec 查看。",
            }
        text = _decode_raw(raw)
        lines = text.splitlines()
        offset = max(0, int(args.get("offset") or 0))
        limit = max(1, min(int(args.get("limit") or 400), MAX_READ_LINES))
        char_offset = max(0, int(args.get("char_offset") or 0))
        if offset >= len(lines) and lines:
            return {
                "ok": False,
                "path": str(path),
                "total_lines": len(lines),
                "offset": offset,
                "error": f"offset 超出范围：文件只有 {len(lines)} 行（offset 从 0 开始）",
                "hint": "传 offset=0 重新读取，或使用小于 total_lines 的值。",
            }
        if char_offset:
            line = lines[offset] if offset < len(lines) else ""
            if char_offset >= len(line):
                return {
                    "ok": False,
                    "path": str(path),
                    "offset": offset,
                    "char_offset": char_offset,
                    "line_chars": len(line),
                    "error": f"char_offset 超出该行长度：第 {offset + 1} 行只有 {len(line)} 个字符",
                    "hint": "char_offset 从 0 开始；用 offset 定位行、char_offset=0 重新读取该行。",
                }
            piece = line[char_offset:char_offset + MAX_READ_CHARS]
            next_char = char_offset + len(piece)
            more = next_char < len(line)
            result = {
                "ok": True,
                "path": str(path),
                "content": piece,
                "total_lines": len(lines),
                "offset": offset,
                "char_offset": char_offset,
                "returned_chars": len(piece),
                "line_chars": len(line),
                "line_ending": _line_ending(text),
                "truncated": more,
            }
            if more:
                result["warning"] = (
                    f"第 {offset + 1} 行共 {len(line)} 字符，本次返回第 "
                    f"{char_offset + 1}-{next_char} 字符；续读请传 "
                    f"offset={offset}、char_offset={next_char}。"
                )
                # 该行还没读完，offset 仍停在同一行，不能作为推进依据。
                result["next_offset"] = None
                result["next_char_offset"] = next_char
            return result
        chunk: list[str] = []
        used = 0
        line_truncated = False
        for raw_line in lines[offset:offset + limit]:
            if chunk and used + len(raw_line) + 1 > MAX_READ_CHARS:
                break
            if not chunk and len(raw_line) > MAX_READ_CHARS:
                raw_line = raw_line[:MAX_READ_CHARS]
                line_truncated = True
            chunk.append(raw_line)
            used += len(raw_line) + 1
        truncated = offset + len(chunk) < len(lines)
        result = {
            "ok": True,
            "path": str(path),
            "content": "\n".join(chunk),
            "total_lines": len(lines),
            "offset": offset,
            "returned_lines": len(chunk),
            "line_ending": _line_ending(text),
            "truncated": truncated or line_truncated,
        }
        if line_truncated:
            result["line_truncated"] = True
        warnings = []
        if line_truncated:
            warnings.append(
                f"第 {offset + 1} 行超过 {MAX_READ_CHARS} 字符，已截断该行；续读请传 "
                f"offset={offset}、char_offset={MAX_READ_CHARS}，读完该行后再用 "
                f"offset={offset + 1}（共 {len(lines)} 行）。"
            )
            # 行内还有剩余内容，不能用 next_offset 推进，否则会重复读首段。
            result["next_offset"] = None
            result["next_char_offset"] = MAX_READ_CHARS
        elif truncated:
            warnings.append(
                f"只返回第 {offset + 1}-{offset + len(chunk)} 行，共 {len(lines)} 行；"
                f"继续读取请传 offset={offset + len(chunk)}。"
            )
            result["next_offset"] = offset + len(chunk)
        if warnings:
            result["warning"] = " ".join(warnings)
        return result

    def fs_write(args: dict) -> dict:
        path = safety.resolve(args.get("path", ""), for_write=True)
        content = args.get("content")
        if content is None:
            return {"ok": False, "error": "缺少 content"}
        raw = str(content).encode("utf-8")
        if len(raw) > MAX_WRITE_BYTES:
            return {"ok": False, "error": "内容超过 2MB，已拒绝写入"}
        existed = path.exists()
        if existed and not path.is_file():
            return {"ok": False, "error": f"目标不是普通文件：{path}"}
        old_text = ""
        if existed:
            try:
                raw_old = path.read_bytes()
                if not _is_binary(raw_old):
                    old_text = _decode_raw(raw_old)
            except OSError:
                old_text = ""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        except OSError as e:
            return _write_failure(path, e)
        added, removed = _line_stats(old_text, str(content))
        safety.audit("fs_write", {"path": str(path), "bytes": len(raw), "overwrite": existed})
        return {
            "ok": True,
            "path": str(path),
            "name": path.name,
            "bytes": len(raw),
            "overwritten": existed,
            "lines_added": added,
            "lines_removed": removed,
        }

    def fs_edit(args: dict) -> dict:
        path = safety.resolve(args.get("path", ""), for_write=True)
        if not path.is_file():
            return {"ok": False, "error": f"文件不存在：{path}"}
        old = str(args.get("old") or "")
        new = str(args.get("new") or "")
        if not old:
            return {"ok": False, "error": "缺少 old"}
        text, encoding = _document_of(path, limit_bytes=MAX_WRITE_BYTES)
        count = text.count(old)
        if count == 0:
            return {"ok": False, "error": "没有找到要替换的内容（请先 fs_read 确认原文）",
                    "hint": "注意原文里的空格、换行和标点必须与文件完全一致。"}
        if count > 1:
            return {"ok": False, "error": f"原文出现 {count} 次，无法确定替换位置，请提供更长的唯一片段",
                    "hint": "在 old 里多带上前后几行，确保整段只出现一次。"}
        updated = text.replace(old, new, 1)
        try:
            if encoding == "utf-16-le":
                raw = b"\xff\xfe" + updated.encode("utf-16-le")
            elif encoding == "utf-16-be":
                raw = b"\xfe\xff" + updated.encode("utf-16-be")
            else:
                raw = updated.encode(encoding)
        except UnicodeEncodeError:
            encoding = "utf-8"
            raw = updated.encode("utf-8")
        if len(raw) > MAX_WRITE_BYTES:
            return {"ok": False, "error": "修改后文件超过 2MB，已拒绝写入"}
        try:
            path.write_bytes(raw)
        except OSError as e:
            return _write_failure(path, e)
        added, removed = _line_stats(text, updated)
        safety.audit("fs_edit", {"path": str(path), "size": len(new), "encoding": encoding})
        return {
            "ok": True,
            "path": str(path),
            "name": path.name,
            "occurrences": 1,
            "bytes": len(raw),
            "encoding": encoding,
            "lines_added": added,
            "lines_removed": removed,
        }

    def fs_list(args: dict) -> dict:
        target = safety.resolve(args.get("dir") or str(config.output_dir), for_write=False)
        if not target.exists():
            return {"ok": False, "error": f"目录不存在：{target}"}
        if target.is_file():
            return {"ok": False, "error": f"这是文件，请用 fs_read：{target}"}
        pattern = args.get("pattern") or "*"
        items = []
        try:
            for entry in target.iterdir():
                if not fnmatch.fnmatch(entry.name, pattern):
                    continue
                try:
                    stat = entry.stat()
                except OSError:
                    continue
                items.append({
                    "name": entry.name,
                    "path": str(entry),
                    "is_dir": entry.is_dir(),
                    "size": 0 if entry.is_dir() else stat.st_size,
                    "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(stat.st_mtime)),
                })
        except OSError as e:
            return {"ok": False, "error": f"读取目录失败：{e}"}
        items.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
        items = items[:200]
        lines = [
            f"{'[文件夹]' if i['is_dir'] else '[文件]'} {i['name']}  {i['modified']}"
            for i in items
        ]
        return {"ok": True, "dir": str(target), "items": items, "output": "\n".join(lines) or "（空目录）"}

    def fs_search(args: dict) -> dict:
        base = safety.resolve(args.get("dir") or str(config.output_dir), for_write=False)
        if not base.is_dir():
            return {"ok": False, "error": f"目录不存在：{base}"}
        needle = str(args.get("pattern") or "").strip()
        if not needle:
            return {"ok": False, "error": "缺少 pattern"}
        glob_pat = args.get("glob") or "*"
        requested = int(args.get("max_results") or 30)
        max_results = max(1, min(requested, 200))
        context = max(0, min(int(args.get("context") or 0), 5))
        regex = bool(args.get("regex"))
        matcher = None
        if regex:
            try:
                matcher = re.compile(needle, re.IGNORECASE)
            except re.error as e:
                return {"ok": False, "error": f"正则表达式不正确：{e}"}
        matches = []
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d.lower() not in SKIP_DIRS and not d.startswith("$")]
            for name in files:
                if not fnmatch.fnmatch(name, glob_pat):
                    continue
                fp = Path(root) / name
                try:
                    if fp.stat().st_size > MAX_WRITE_BYTES:
                        continue
                    text = _text_of(fp, limit_bytes=MAX_WRITE_BYTES)
                except OSError:
                    continue
                if "\x00" in text[:1000]:
                    continue
                lines = text.splitlines()
                for idx, line in enumerate(lines):
                    hit = bool(matcher.search(line)) if matcher else (needle.lower() in line.lower())
                    if not hit:
                        continue
                    start = max(0, idx - context)
                    end = min(len(lines), idx + context + 1)
                    excerpt = "\n".join(x.strip()[:200] for x in lines[start:end])
                    matches.append({
                        "path": str(fp),
                        "line": idx + 1,
                        "text": line.strip()[:200],
                        "context": excerpt,
                    })
                    if len(matches) >= max_results:
                        break
                if len(matches) >= max_results:
                    break
            if len(matches) >= max_results:
                break
        text = "\n".join(
            f"{m['path']}:{m['line']}  {m['text']}" if not context
            else f"{m['path']}:{m['line']}\n{m['context']}"
            for m in matches
        )
        if not matches:
            return {
                "ok": True,
                "found": False,
                "empty": True,
                "matches": [],
                "count": 0,
                "output": "没有找到匹配内容",
                "hint": "检索已执行，只是没有命中；确认目录、pattern 与 glob 是否正确，需要正则时设置 regex=true。",
            }
        result = {"ok": True, "found": True, "matches": matches, "count": len(matches),
                  "output": text[:6000]}
        if len(matches) >= max_results:
            result["truncated"] = True
            result["warning"] = _cap_note(requested, max_results)
        return result

    def fs_glob(args: dict) -> dict:
        base = safety.resolve(args.get("dir") or str(config.output_dir), for_write=False)
        if not base.is_dir():
            return {"ok": False, "error": f"目录不存在：{base}"}
        pattern = str(args.get("pattern") or "*").strip()
        if not pattern:
            return {"ok": False, "error": "缺少 pattern"}
        if Path(pattern).is_absolute():
            return {"ok": False, "error": "pattern 必须是相对路径，如 **/*.md"}
        requested = int(args.get("max_results") or 100)
        max_results = max(1, min(requested, 200))
        items = []
        try:
            for fp in base.glob(pattern):
                if not fp.is_file():
                    continue
                try:
                    rel_parts = {p.lower() for p in fp.relative_to(base).parts}
                except ValueError:
                    continue
                if rel_parts & SKIP_DIRS:
                    continue
                try:
                    stat = fp.stat()
                except OSError:
                    continue
                items.append({
                    "path": str(fp),
                    "name": fp.name,
                    "size": stat.st_size,
                    "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(stat.st_mtime)),
                })
                if len(items) >= max_results:
                    break
        except (OSError, ValueError) as e:
            return {"ok": False, "error": f"通配符无效：{e}"}
        items.sort(key=lambda x: x["modified"], reverse=True)
        lines = [f"{i['path']}  {i['size']} B  {i['modified']}" for i in items]
        if not items:
            return {
                "ok": True,
                "found": False,
                "empty": True,
                "items": [],
                "count": 0,
                "output": "没有找到匹配文件",
                "hint": "检索已执行，只是没有命中；确认 pattern 写法，如 **/*.md，目录范围可通过 dir 指定。",
            }
        result = {"ok": True, "found": True, "items": items, "count": len(items),
                  "output": "\n".join(lines)}
        if len(items) >= max_results:
            result["truncated"] = True
            result["warning"] = _cap_note(requested, max_results)
        return result

    def fs_delete(args: dict) -> dict:
        raw_paths = args.get("paths")
        if isinstance(raw_paths, str):
            raw_paths = [raw_paths]
        if not isinstance(raw_paths, list) or not raw_paths:
            return {"ok": False, "error": "缺少 paths"}
        if len(raw_paths) > 20:
            return {"ok": False, "error": "一次最多删除 20 个文件"}
        targets: list[Path] = []
        for raw in raw_paths:
            path = safety.resolve(str(raw), for_write=True, action="delete")
            if not path.exists():
                return {"ok": False, "error": f"文件不存在：{path}"}
            if not path.is_file():
                return {"ok": False, "error": f"只允许删除文件，不删除文件夹：{path}"}
            targets.append(path)
        ok, err = _recycle(targets)
        if not ok:
            return {"ok": False, "error": err}
        safety.audit("fs_delete", {"paths": [str(p) for p in targets],
                                   "count": len(targets), "recycle": True})
        return {
            "ok": True,
            "paths": [str(p) for p in targets],
            "count": len(targets),
            "output": f"已把 {len(targets)} 个文件移到回收站",
        }

    reg.add(Tool(
        name="fs_read",
        description=(
            "读取本地文本文件内容。单次最多约 3000 字符（默认 400 行）；"
            "超出时返回 truncated 与 next_offset，用 offset 继续读；"
            "单行过长时用 offset + char_offset 续读同一行。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "绝对路径"},
                "offset": {"type": "integer", "description": "起始行，默认 0"},
                "limit": {"type": "integer", "description": "读取行数，默认 400"},
                "char_offset": {
                    "type": "integer",
                    "description": "行内字符起点，默认 0；用于读取超长单行的后段",
                },
            },
            "required": ["path"],
        },
        handler=fs_read,
        tag="fs",
    ))
    reg.add(Tool(
        name="fs_write",
        description="把文本按原样写入本地文件（UTF-8，不会自动添加换行；会自动创建目录）。生成 html/md/txt/csv 时使用。",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "绝对路径"},
                "content": {"type": "string", "description": "完整文件内容"},
            },
            "required": ["path", "content"],
        },
        handler=fs_write,
        tag="fs",
    ))
    reg.add(Tool(
        name="fs_edit",
        description=(
            "精确替换文件中的一段文本，原文必须在文件中唯一出现。"
            "保留原文件编码与换行；修改前先用 fs_read 确认原文。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old": {"type": "string", "description": "被替换的原文（需唯一）"},
                "new": {"type": "string", "description": "替换后的内容"},
            },
            "required": ["path", "old", "new"],
        },
        handler=fs_edit,
        tag="fs",
    ))
    reg.add(Tool(
        name="fs_list",
        description="列出文件夹内容，可按通配符过滤。",
        parameters={
            "type": "object",
            "properties": {
                "dir": {"type": "string", "description": "文件夹路径，默认输出目录"},
                "pattern": {"type": "string", "description": "通配符，如 *.md"},
            },
        },
        handler=fs_list,
        tag="fs",
    ))
    reg.add(Tool(
        name="fs_search",
        description=(
            "在文件夹内搜索文本内容，返回文件路径、行号与匹配行。"
            "regex=true 时按正则匹配；context 可带前后各几行；max_results 最多 200。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "要搜索的文字或正则"},
                "dir": {"type": "string", "description": "搜索根目录"},
                "glob": {"type": "string", "description": "文件名过滤，如 *.txt 或 **/*.py"},
                "regex": {"type": "boolean", "description": "是否按正则表达式匹配"},
                "context": {"type": "integer", "description": "前后各带几行，0-5"},
                "max_results": {"type": "integer", "description": "最多返回条数，默认 30"},
            },
            "required": ["pattern"],
        },
        handler=fs_search,
        tag="fs",
    ))
    reg.add(Tool(
        name="fs_glob",
        description=(
            "按通配符递归查找文件，支持 **（如 **/*.md），返回路径、大小、修改时间。"
            "只读，最多 200 条，自动跳过 .git/node_modules/AppData/Windows 等目录。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "相对通配符，如 **/*.md"},
                "dir": {"type": "string", "description": "搜索根目录，默认输出目录"},
                "max_results": {"type": "integer", "description": "最多返回条数，默认 100"},
            },
            "required": ["pattern"],
        },
        handler=fs_glob,
        tag="fs",
    ))
    reg.add(Tool(
        name="fs_delete",
        description=(
            "把文件移到回收站（需要用户确认）。只允许删除文件，不删除文件夹；"
            "一次最多 20 个；不能删除沙箱外的文件。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要删除的文件路径列表",
                }
            },
            "required": ["paths"],
        },
        handler=fs_delete,
        needs_confirm=True,
        tag="fs",
    ))

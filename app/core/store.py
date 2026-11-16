"""SQLite 本地历史：会话、消息、工具执行、生成文件、审计。

敏感字段（标题、正文、工具参数、文件路径、审计详情、定时任务）在写入前
用 AES-256-GCM 加密，读取时透明解密；首次启动会把旧的明文记录原地加密，
并通过 VACUUM 重写数据库文件，避免明文残留在空闲页。
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from .secret import SecretBox


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL DEFAULT '新对话',
    mode TEXT NOT NULL DEFAULT 'supervised',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    meta TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
CREATE TABLE IF NOT EXISTS tool_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER,
    tool TEXT NOT NULL,
    args TEXT,
    ok INTEGER NOT NULL DEFAULT 0,
    summary TEXT,
    ms INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER,
    path TEXT NOT NULL,
    name TEXT NOT NULL,
    size INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT,
    ok INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit(ts);
CREATE TABLE IF NOT EXISTS schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    prompt TEXT NOT NULL,
    interval_minutes INTEGER NOT NULL,
    next_run TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_run TEXT,
    last_result TEXT,
    created_at TEXT NOT NULL,
    once INTEGER NOT NULL DEFAULT 0,
    session_id INTEGER
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'preference',
    source_session INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memories_updated ON memories(updated_at DESC, id DESC);
"""

# 需要加密的字段：表名 -> 列
_SENSITIVE_COLUMNS = {
    "sessions": ("title", "summary"),
    "messages": ("content", "meta"),
    "tool_runs": ("args", "summary"),
    "files": ("path", "name"),
    "audit": ("detail",),
    "schedules": ("title", "prompt", "last_result"),
    "memories": ("text",),
}
_CRYPTO_VERSION = "1"


class Store:
    def __init__(self, db_path: Path, box: SecretBox):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._box = box
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA secure_delete=ON")
            self._conn.executescript(SCHEMA)
            self._conn.commit()
            self._ensure_columns()
            self._migrate_plaintext()

    def _ensure_columns(self) -> None:
        """为旧数据库补上后加的字段。"""
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(sessions)")}
        if "summary" not in cols:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN summary TEXT DEFAULT ''")
        if "summary_upto" not in cols:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN summary_upto INTEGER DEFAULT 0")
        schedule_cols = {row[1] for row in self._conn.execute("PRAGMA table_info(schedules)")}
        if "once" not in schedule_cols:
            self._conn.execute("ALTER TABLE schedules ADD COLUMN once INTEGER NOT NULL DEFAULT 0")
        if "session_id" not in schedule_cols:
            self._conn.execute("ALTER TABLE schedules ADD COLUMN session_id INTEGER")
        # 旧版本的回滚日志表已废弃，启动时清理。
        self._conn.execute("DROP TABLE IF EXISTS file_journal")
        self._conn.commit()

    def _migrate_plaintext(self) -> None:
        """把旧版本遗留的明文记录加密，并在完成后重写数据库文件。"""
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key='crypto_version'"
        ).fetchone()
        if row and str(row["value"]) == _CRYPTO_VERSION:
            return
        changed = 0
        with self._conn:
            for table, columns in _SENSITIVE_COLUMNS.items():
                rows = self._conn.execute(
                    f"SELECT id,{','.join(columns)} FROM {table}"
                ).fetchall()
                for item in rows:
                    sets, values = [], []
                    for col in columns:
                        value = item[col]
                        if value and not self._box.is_encrypted(value):
                            sets.append(f"{col}=?")
                            values.append(self._box.encrypt_text(value))
                    if sets:
                        values.append(item["id"])
                        self._conn.execute(
                            f"UPDATE {table} SET {','.join(sets)} WHERE id=?", values
                        )
                        changed += 1
            self._conn.execute(
                "INSERT OR REPLACE INTO meta(key,value) VALUES('crypto_version',?)",
                (_CRYPTO_VERSION,),
            )
        if changed:
            try:
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                self._conn.execute("VACUUM")
            except sqlite3.Error:
                pass

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---------- sessions ----------
    def create_session(self, title: str = "新对话", mode: str = "supervised") -> int:
        now = _now()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO sessions(title, mode, created_at, updated_at) VALUES(?,?,?,?)",
                (self._box.encrypt_text(title or "新对话"), mode, now, now),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def touch_session(self, session_id: int, title: str | None = None) -> None:
        with self._lock:
            if title:
                self._conn.execute(
                    "UPDATE sessions SET updated_at=?, title=? WHERE id=?",
                    (_now(), self._box.encrypt_text(title), session_id),
                )
            else:
                self._conn.execute("UPDATE sessions SET updated_at=? WHERE id=?", (_now(), session_id))
            self._conn.commit()

    def get_session(self, session_id: int) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["title"] = self._box.decrypt_text(item.get("title"))
        return item

    def get_session_summary(self, session_id: int) -> tuple[str, int]:
        """读取已持久化的上下文摘要与摘要覆盖到的消息 id。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT summary, summary_upto FROM sessions WHERE id=?", (session_id,)
            ).fetchone()
        if not row:
            return "", 0
        return self._box.decrypt_text(row["summary"]) or "", int(row["summary_upto"] or 0)

    def set_session_summary(self, session_id: int, summary: str, upto: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET summary=?, summary_upto=? WHERE id=?",
                (self._box.encrypt_text(summary or ""), int(upto or 0), session_id),
            )
            self._conn.commit()

    def clear_all_sessions(self) -> int:
        """清空全部对话、工具记录与文件记录，返回删除的会话数。"""
        with self._lock:
            count = int(self._conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])
            with self._conn:
                for table in ("messages", "tool_runs", "files", "sessions"):
                    self._conn.execute(f"DELETE FROM {table}")
            return count

    def list_sessions(self, limit: int = 30) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT s.*, (SELECT COUNT(*) FROM messages m WHERE m.session_id=s.id) AS msg_count "
                "FROM sessions s ORDER BY s.updated_at DESC, s.id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["title"] = self._box.decrypt_text(item.get("title"))
            out.append(item)
        return out

    # ---------- messages ----------
    def add_message(self, session_id: int, role: str, content: str, meta: dict | None = None) -> int:
        meta_text = json.dumps(meta, ensure_ascii=False) if meta else None
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO messages(session_id, role, content, meta, created_at) VALUES(?,?,?,?,?)",
                (session_id, role, self._box.encrypt_text(content or ""),
                 self._box.encrypt_text(meta_text), _now()),
            )
            self._conn.commit()
            session_id_val = int(cur.lastrowid)
        return session_id_val

    def messages(self, session_id: int, limit: int = 200) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM messages WHERE session_id=? ORDER BY id ASC LIMIT ?",
                (session_id, int(limit)),
            ).fetchall()
        return self._decrypt_messages(rows)

    def tail_messages(self, session_id: int, limit: int = 400) -> list[dict]:
        """返回最近 N 条消息，仍按时间正序排列。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?",
                (session_id, int(limit)),
            ).fetchall()
        return self._decrypt_messages(reversed(rows))

    def messages_after(self, session_id: int, after_id: int = 0,
                       limit: int = 50000) -> list[dict]:
        """返回指定 id 之后的全部消息，按时间正序；用于全量上下文压缩。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM messages WHERE session_id=? AND id>? ORDER BY id ASC LIMIT ?",
                (session_id, int(after_id or 0), int(limit)),
            ).fetchall()
        return self._decrypt_messages(rows)

    def last_usage(self, session_id: int, scan: int = 30) -> dict | None:
        """最近一次带真实用量的助手消息，用作上下文计量的锚点。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM messages WHERE session_id=? AND role='assistant' "
                "ORDER BY id DESC LIMIT ?",
                (int(session_id), int(scan)),
            ).fetchall()
        for row in self._decrypt_messages(rows):
            meta = row.get("meta") or {}
            usage = meta.get("usage")
            if isinstance(usage, dict) and usage.get("input") is not None:
                return {
                    "usage": usage,
                    "envelope": str(meta.get("envelope") or ""),
                    "surface": int(meta.get("surface") or 0),
                    "estimate": int(meta.get("estimate") or 0),
                }
        return None

    def _decrypt_messages(self, rows) -> list[dict]:
        out = []
        for r in rows:
            item = dict(r)
            item["content"] = self._box.decrypt_text(item.get("content")) or ""
            meta_text = self._box.decrypt_text(item.get("meta"))
            try:
                item["meta"] = json.loads(meta_text) if meta_text else None
            except json.JSONDecodeError:
                item["meta"] = None
            out.append(item)
        return out

    def delete_session(self, session_id: int) -> None:
        with self._lock:
            for table in ("messages", "tool_runs", "files", "sessions"):
                self._conn.execute(f"DELETE FROM {table} WHERE {'id' if table == 'sessions' else 'session_id'}=?",
                                   (session_id,))
            self._conn.commit()

    # ---------- tool runs ----------
    def add_tool_run(self, session_id: int | None, tool: str, args: dict | None,
                     ok: bool, summary: str, ms: int) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO tool_runs(session_id, tool, args, ok, summary, ms, created_at) VALUES(?,?,?,?,?,?,?)",
                (session_id, tool,
                 self._box.encrypt_text(json.dumps(args or {}, ensure_ascii=False)[:4000]),
                 1 if ok else 0, self._box.encrypt_text((summary or "")[:2000]),
                 int(ms), _now()),
            )
            self._conn.commit()

    def list_tool_runs(self, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM tool_runs ORDER BY id DESC LIMIT ?", (int(limit),)
            ).fetchall()
        return [self._decrypt_run(r) for r in rows]

    def _decrypt_run(self, row) -> dict:
        item = dict(row)
        item["args"] = self._box.decrypt_text(item.get("args"))
        item["summary"] = self._box.decrypt_text(item.get("summary"))
        return item

    # ---------- files ----------
    def add_file(self, session_id: int | None, path: str, name: str, size: int) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO files(session_id, path, name, size, created_at) VALUES(?,?,?,?,?)",
                (session_id, self._box.encrypt_text(path),
                 self._box.encrypt_text(name), int(size), _now()),
            )
            self._conn.commit()

    def _decrypt_file(self, row) -> dict:
        item = dict(row)
        item["path"] = self._box.decrypt_text(item.get("path"))
        item["name"] = self._box.decrypt_text(item.get("name"))
        return item

    def list_files(self, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM files ORDER BY id DESC LIMIT ?", (int(limit),)
            ).fetchall()
        return [self._decrypt_file(r) for r in rows]

    def session_files(self, session_id: int, limit: int = 60) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM files WHERE session_id=? ORDER BY id ASC LIMIT ?",
                (int(session_id), int(limit)),
            ).fetchall()
        return [self._decrypt_file(r) for r in rows]

    def session_tool_runs(self, session_id: int, limit: int = 80) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM tool_runs WHERE session_id=? ORDER BY id ASC LIMIT ?",
                (int(session_id), int(limit)),
            ).fetchall()
        return [self._decrypt_run(r) for r in rows]

    # ---------- audit ----------
    def audit(self, action: str, detail: dict | str | None = None, ok: bool = True) -> None:
        if isinstance(detail, (dict, list)):
            detail = json.dumps(detail, ensure_ascii=False)
        with self._lock:
            self._conn.execute(
                "INSERT INTO audit(ts, action, detail, ok) VALUES(?,?,?,?)",
                (_now(), action, self._box.encrypt_text((detail or "")[:4000]),
                 1 if ok else 0),
            )
            self._conn.commit()

    def list_audit(self, limit: int = 100) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM audit ORDER BY id DESC LIMIT ?", (int(limit),)
            ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["detail"] = self._box.decrypt_text(item.get("detail"))
            out.append(item)
        return out

    # ---------- schedules ----------
    def add_schedule(self, title: str, prompt: str, interval_minutes: int,
                     next_run: str, once: int = 0, session_id: int | None = None) -> int:
        now = _now()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO schedules(title, prompt, interval_minutes, next_run, created_at, once, session_id) "
                "VALUES(?,?,?,?,?,?,?)",
                (self._box.encrypt_text(title[:80] or "定时任务"),
                 self._box.encrypt_text(prompt[:4000]), int(interval_minutes),
                 next_run, now, 1 if once else 0,
                 int(session_id) if session_id else None),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def _decrypt_schedule(self, row) -> dict:
        item = dict(row)
        for key in ("title", "prompt", "last_result"):
            item[key] = self._box.decrypt_text(item.get(key))
        return item

    def list_schedules(self, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM schedules ORDER BY id DESC LIMIT ?", (int(limit),)
            ).fetchall()
        return [self._decrypt_schedule(r) for r in rows]

    def due_schedules(self, now: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM schedules WHERE enabled=1 AND next_run <= ? "
                "ORDER BY next_run LIMIT 5",
                (now,),
            ).fetchall()
        return [self._decrypt_schedule(r) for r in rows]

    def mark_schedule_run(self, schedule_id: int, next_run: str, result: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE schedules SET last_run=?, last_result=?, next_run=? WHERE id=?",
                (_now(), self._box.encrypt_text((result or "")[:1000]),
                 next_run, int(schedule_id)),
            )
            self._conn.commit()

    def set_schedule_enabled(self, schedule_id: int, enabled: bool) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE schedules SET enabled=? WHERE id=?",
                (1 if enabled else 0, int(schedule_id)),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def delete_schedule(self, schedule_id: int) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM schedules WHERE id=?", (int(schedule_id),))
            self._conn.commit()
            return cur.rowcount > 0

    # ---------- memories ----------
    def add_memory(self, text: str, category: str = "preference",
                   session_id: int | None = None) -> int:
        value = " ".join(str(text or "").split())[:500]
        if not value:
            raise ValueError("记忆内容为空")
        category = str(category or "preference").strip().lower()[:20] or "preference"
        now = _now()
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, text FROM memories ORDER BY updated_at DESC, id DESC LIMIT 200"
            ).fetchall()
            for row in rows:
                if self._box.decrypt_text(row["text"]) == value:
                    self._conn.execute(
                        "UPDATE memories SET category=?, updated_at=? WHERE id=?",
                        (category, now, int(row["id"])),
                    )
                    self._conn.commit()
                    return int(row["id"])
            cur = self._conn.execute(
                "INSERT INTO memories(text, category, source_session, created_at, updated_at) "
                "VALUES(?,?,?,?,?)",
                (self._box.encrypt_text(value), category, session_id, now, now),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def memories(self, limit: int = 40) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM memories ORDER BY updated_at DESC, id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["text"] = self._box.decrypt_text(item.get("text"))
            out.append(item)
        return out

    def update_memory(self, memory_id: int, text: str, category: str | None = None) -> bool:
        value = " ".join(str(text or "").split())[:500]
        if not value:
            return False
        with self._lock:
            if category:
                cur = self._conn.execute(
                    "UPDATE memories SET text=?, category=?, updated_at=? WHERE id=?",
                    (self._box.encrypt_text(value), str(category)[:20], _now(), int(memory_id)),
                )
            else:
                cur = self._conn.execute(
                    "UPDATE memories SET text=?, updated_at=? WHERE id=?",
                    (self._box.encrypt_text(value), _now(), int(memory_id)),
                )
            self._conn.commit()
            return cur.rowcount > 0

    def delete_memory(self, memory_id: int) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM memories WHERE id=?", (int(memory_id),))
            self._conn.commit()
            return cur.rowcount > 0

    def clear_memories(self) -> int:
        with self._lock:
            count = int(self._conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0])
            self._conn.execute("DELETE FROM memories")
            self._conn.commit()
            return count

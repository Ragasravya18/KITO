from __future__ import annotations

import json
import secrets
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any


class Store:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA busy_timeout = 10000")
        return db

    def initialize(self) -> None:
        with self.connect() as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    sid TEXT PRIMARY KEY,
                    owner_key TEXT NOT NULL,
                    role TEXT NOT NULL,
                    token TEXT,
                    user_json TEXT,
                    expires_at REAL NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS sessions_owner ON sessions(owner_key);
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    owner_key TEXT NOT NULL,
                    title TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS conversations_owner_updated ON conversations(owner_key, updated_at DESC);
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    owner_key TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS messages_conversation ON messages(conversation_id, id);
                CREATE TABLE IF NOT EXISTS pending_actions (
                    id TEXT PRIMARY KEY,
                    owner_key TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    operation_id TEXT NOT NULL,
                    arguments_json TEXT NOT NULL,
                    preview_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    result_json TEXT,
                    idempotency_key TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS pending_owner ON pending_actions(owner_key, status);
                CREATE TABLE IF NOT EXISTS personal_schedule (
                    id TEXT PRIMARY KEY,
                    owner_key TEXT NOT NULL,
                    title TEXT NOT NULL,
                    event_date TEXT NOT NULL,
                    start_time TEXT NOT NULL,
                    end_time TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS personal_schedule_owner_date ON personal_schedule(owner_key, event_date, start_time);
                """
            )

    def ensure_visitor(self, sid: str | None) -> tuple[dict[str, Any], bool]:
        now = time.time()
        if sid:
            with self.connect() as db:
                row = db.execute("SELECT * FROM sessions WHERE sid=? AND expires_at>?", (sid, now)).fetchone()
                if row:
                    return self._session(row), False
        sid = secrets.token_urlsafe(32)
        owner = f"visitor:{uuid.uuid4()}"
        session = {"sid": sid, "owner_key": owner, "role": "visitor", "token": None, "user": None}
        with self.connect() as db:
            db.execute(
                "INSERT INTO sessions(sid, owner_key, role, token, user_json, expires_at, created_at) VALUES(?,?,?,?,?,?,?)",
                (sid, owner, "visitor", None, None, now + 60 * 60 * 24 * 30, now),
            )
        return session, True

    def create_user_session(self, user: dict[str, Any], token: str, expires_in: int) -> dict[str, Any]:
        now = time.time()
        sid = secrets.token_urlsafe(32)
        owner = f"kit-user:{user.get('id', user.get('login_id', 'unknown'))}"
        with self.connect() as db:
            db.execute("DELETE FROM sessions WHERE owner_key=? AND role!='visitor'", (owner,))
            db.execute(
                "INSERT INTO sessions(sid, owner_key, role, token, user_json, expires_at, created_at) VALUES(?,?,?,?,?,?,?)",
                (sid, owner, user.get("role", "student"), token, json.dumps(user), now + min(expires_in, 28800), now),
            )
        return {"sid": sid, "owner_key": owner, "role": user.get("role", "student"), "token": token, "user": user}

    def get_session(self, sid: str | None) -> dict[str, Any] | None:
        if not sid:
            return None
        with self.connect() as db:
            row = db.execute("SELECT * FROM sessions WHERE sid=? AND expires_at>?", (sid, time.time())).fetchone()
            return self._session(row) if row else None

    @staticmethod
    def _session(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "sid": row["sid"], "owner_key": row["owner_key"], "role": row["role"],
            "token": row["token"], "user": json.loads(row["user_json"]) if row["user_json"] else None,
        }

    def delete_session(self, sid: str | None) -> None:
        if sid:
            with self.connect() as db:
                db.execute("DELETE FROM sessions WHERE sid=?", (sid,))

    def create_conversation(self, owner: str, first_text: str = "New conversation") -> str:
        now = time.time()
        title = " ".join(first_text.split())[:72] or "New conversation"
        conversation_id = str(uuid.uuid4())
        with self.connect() as db:
            db.execute(
                "INSERT INTO conversations(id, owner_key, title, created_at, updated_at) VALUES(?,?,?,?,?)",
                (conversation_id, owner, title, now, now),
            )
        return conversation_id

    def owns_conversation(self, owner: str, conversation_id: str) -> bool:
        with self.connect() as db:
            return db.execute("SELECT 1 FROM conversations WHERE id=? AND owner_key=?", (conversation_id, owner)).fetchone() is not None

    def save_message(self, owner: str, conversation_id: str, role: str, content: str, metadata: dict | None = None) -> None:
        now = time.time()
        with self.connect() as db:
            db.execute(
                "INSERT INTO messages(conversation_id,owner_key,role,content,metadata_json,created_at) VALUES(?,?,?,?,?,?)",
                (conversation_id, owner, role, content, json.dumps(metadata or {}, ensure_ascii=False), now),
            )
            db.execute("UPDATE conversations SET updated_at=? WHERE id=? AND owner_key=?", (now, conversation_id, owner))

    def get_messages(self, owner: str, conversation_id: str, limit: int = 30) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT role,content,metadata_json,created_at FROM messages WHERE owner_key=? AND conversation_id=? ORDER BY id DESC LIMIT ?",
                (owner, conversation_id, limit),
            ).fetchall()
            messages = []
            for row in reversed(rows):
                metadata = json.loads(row["metadata_json"])
                pending = metadata.get("pending")
                if pending and pending.get("id"):
                    state = db.execute("SELECT status FROM pending_actions WHERE id=? AND owner_key=?", (pending["id"], owner)).fetchone()
                    if state:
                        pending["status"] = state["status"]
                messages.append({"role": row["role"], "content": row["content"], "metadata": metadata, "created_at": row["created_at"]})
        return messages

    def list_conversations(self, owner: str, limit: int = 30) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT id,title,created_at,updated_at FROM conversations WHERE owner_key=? ORDER BY updated_at DESC LIMIT ?",
                (owner, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def create_pending(self, owner: str, conversation_id: str, operation_id: str, arguments: dict, preview: dict) -> str:
        now = time.time()
        pending_id = str(uuid.uuid4())
        with self.connect() as db:
            db.execute(
                "INSERT INTO pending_actions(id,owner_key,conversation_id,operation_id,arguments_json,preview_json,status,result_json,idempotency_key,created_at,updated_at) VALUES(?,?,?,?,?,?,'pending',NULL,?,?,?)",
                (pending_id, owner, conversation_id, operation_id, json.dumps(arguments, ensure_ascii=False), json.dumps(preview, ensure_ascii=False), secrets.token_urlsafe(24), now, now),
            )
        return pending_id

    def get_pending(self, owner: str, pending_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM pending_actions WHERE id=? AND owner_key=?", (pending_id, owner)).fetchone()
        if not row:
            return None
        return {"id": row["id"], "conversation_id": row["conversation_id"], "operation_id": row["operation_id"], "arguments": json.loads(row["arguments_json"]), "preview": json.loads(row["preview_json"]), "status": row["status"], "result": json.loads(row["result_json"]) if row["result_json"] else None, "idempotency_key": row["idempotency_key"]}

    def update_pending(self, owner: str, pending_id: str, arguments: dict, preview: dict) -> bool:
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE pending_actions SET arguments_json=?,preview_json=?,updated_at=? WHERE id=? AND owner_key=? AND status='pending'",
                (json.dumps(arguments, ensure_ascii=False), json.dumps(preview, ensure_ascii=False), time.time(), pending_id, owner),
            )
        return cursor.rowcount > 0

    def finish_pending(self, owner: str, pending_id: str, result: dict) -> None:
        with self.connect() as db:
            db.execute("UPDATE pending_actions SET status='sent',result_json=?,updated_at=? WHERE id=? AND owner_key=? AND status='pending'", (json.dumps(result, ensure_ascii=False), time.time(), pending_id, owner))

    def cancel_pending(self, owner: str, pending_id: str) -> bool:
        with self.connect() as db:
            cursor = db.execute("UPDATE pending_actions SET status='cancelled',updated_at=? WHERE id=? AND owner_key=? AND status='pending'", (time.time(), pending_id, owner))
        return cursor.rowcount > 0

    def create_schedule_item(self, owner: str, item: dict[str, str]) -> dict[str, Any]:
        item_id = str(uuid.uuid4())
        created_at = time.time()
        record = {"id": item_id, "owner_key": owner, "title": item["title"], "event_date": item["date"], "start_time": item["start_time"], "end_time": item["end_time"], "notes": item.get("notes", ""), "created_at": created_at}
        with self.connect() as db:
            db.execute("INSERT INTO personal_schedule(id,owner_key,title,event_date,start_time,end_time,notes,created_at) VALUES(?,?,?,?,?,?,?,?)", (record["id"], record["owner_key"], record["title"], record["event_date"], record["start_time"], record["end_time"], record["notes"], created_at))
        return {k: v for k, v in record.items() if k != "owner_key"}

    def list_schedule(self, owner: str, event_date: str | None = None) -> list[dict[str, Any]]:
        with self.connect() as db:
            if event_date:
                rows = db.execute("SELECT id,title,event_date,start_time,end_time,notes,created_at FROM personal_schedule WHERE owner_key=? AND event_date=? ORDER BY start_time", (owner, event_date)).fetchall()
            else:
                rows = db.execute("SELECT id,title,event_date,start_time,end_time,notes,created_at FROM personal_schedule WHERE owner_key=? ORDER BY event_date,start_time LIMIT 100", (owner,)).fetchall()
        return [dict(row) for row in rows]

    def delete_schedule_item(self, owner: str, item_id: str) -> bool:
        with self.connect() as db:
            cursor = db.execute("DELETE FROM personal_schedule WHERE id=? AND owner_key=?", (item_id, owner))
        return cursor.rowcount > 0

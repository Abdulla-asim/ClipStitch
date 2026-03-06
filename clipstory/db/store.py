"""
SQLite storage layer for ClipStory.
All DB access goes through this module.
"""

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent / "clipstory.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"

_local = threading.local()


def _conn() -> sqlite3.Connection:
    """Return a thread-local SQLite connection."""
    if not hasattr(_local, "conn") or _local.conn is None:
        con = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA foreign_keys=ON;")
        _local.conn = con
    return _local.conn


def init_db() -> None:
    """Create tables from schema.sql if they don't exist."""
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    con = _conn()
    con.executescript(schema)
    con.commit()


# ─── Sessions ────────────────────────────────────────────────────────────────

def create_session(started_at: datetime) -> int:
    """Insert a new session and return its id."""
    con = _conn()
    cur = con.execute(
        "INSERT INTO sessions (started_at) VALUES (?)",
        (started_at.isoformat(),),
    )
    con.commit()
    return cur.lastrowid


def close_session(session_id: int, ended_at: datetime) -> None:
    con = _conn()
    con.execute(
        "UPDATE sessions SET ended_at=? WHERE id=?",
        (ended_at.isoformat(), session_id),
    )
    con.commit()


def set_session_label(session_id: int, label: str) -> None:
    con = _conn()
    con.execute("UPDATE sessions SET label=? WHERE id=?", (label, session_id))
    con.commit()


def get_latest_session() -> dict | None:
    """Return the most recent session row as a dict, or None."""
    con = _conn()
    row = con.execute(
        "SELECT * FROM sessions ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def list_sessions() -> list[dict]:
    con = _conn()
    rows = con.execute(
        "SELECT * FROM sessions ORDER BY started_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def get_session(session_id: int) -> dict | None:
    con = _conn()
    row = con.execute(
        "SELECT * FROM sessions WHERE id=?", (session_id,)
    ).fetchone()
    return dict(row) if row else None


# ─── Clips ───────────────────────────────────────────────────────────────────

def insert_clip(
    content: str,
    content_type: str,
    session_id: int,
    copied_at: datetime,
    language: str | None = None,
    page_title: str | None = None,
    is_redacted: bool = False,
) -> int:
    con = _conn()
    cur = con.execute(
        """INSERT INTO clips
           (content, content_type, language, page_title, session_id, copied_at, is_redacted)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            content,
            content_type,
            language,
            page_title,
            session_id,
            copied_at.isoformat(),
            1 if is_redacted else 0,
        ),
    )
    con.commit()
    return cur.lastrowid


def get_clips_for_session(session_id: int) -> list[dict]:
    con = _conn()
    rows = con.execute(
        "SELECT * FROM clips WHERE session_id=? ORDER BY copied_at ASC",
        (session_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_clips_by_ids(clip_ids: list[int]) -> list[dict]:
    if not clip_ids:
        return []
    placeholders = ",".join("?" * len(clip_ids))
    con = _conn()
    rows = con.execute(
        f"SELECT * FROM clips WHERE id IN ({placeholders}) ORDER BY copied_at ASC",
        clip_ids,
    ).fetchall()
    return [dict(r) for r in rows]


def get_recent_clips(session_id: int, limit: int = 5) -> list[dict]:
    """Return the N most recent clips in a session (for dedup check)."""
    con = _conn()
    rows = con.execute(
        "SELECT * FROM clips WHERE session_id=? ORDER BY copied_at DESC LIMIT ?",
        (session_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


# ─── Outputs ─────────────────────────────────────────────────────────────────

def save_output(
    session_id: int,
    mode: str,
    content: str,
    clip_ids: list[int] | None = None,
) -> int:
    con = _conn()
    cur = con.execute(
        """INSERT INTO outputs (session_id, mode, content, clip_ids, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (
            session_id,
            mode,
            content,
            json.dumps(clip_ids) if clip_ids else None,
            datetime.now().isoformat(),
        ),
    )
    con.commit()
    return cur.lastrowid


def get_outputs_for_session(session_id: int) -> list[dict]:
    con = _conn()
    rows = con.execute(
        "SELECT * FROM outputs WHERE session_id=? ORDER BY created_at DESC",
        (session_id,),
    ).fetchall()
    return [dict(r) for r in rows]

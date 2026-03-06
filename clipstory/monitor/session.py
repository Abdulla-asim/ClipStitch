"""
Session detection and management for ClipStory.
Handles creating/resuming sessions based on the idle gap threshold.
"""

from datetime import datetime, timedelta
from clipstory import db
from clipstory.config import get


class SessionManager:
    """
    Maintains the current active session.
    A new session is started when the gap since the last clip
    exceeds `session_gap_minutes` from config.
    """

    def __init__(self):
        self._current_session_id: int | None = None
        self._last_clip_time: datetime | None = None
        self._gap = timedelta(minutes=get("monitor.session_gap_minutes", 30))
        self._resume_or_create()

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def current_session_id(self) -> int:
        return self._current_session_id

    def record_clip(self, timestamp: datetime) -> None:
        """
        Called after a clip is stored.
        Checks if we need to start a new session first.
        """
        if self._should_start_new_session(timestamp):
            self._close_current(timestamp)
            self._start_new(timestamp)
        self._last_clip_time = timestamp

    def close(self) -> None:
        """Close the current session on app shutdown."""
        if self._current_session_id is not None:
            self._close_current(datetime.now())

    # ── Internals ─────────────────────────────────────────────────────────────

    def _resume_or_create(self) -> None:
        """On startup, resume a recent open session or create a fresh one."""
        latest = db.store.get_latest_session()
        now = datetime.now()

        if latest and latest["ended_at"] is None:
            started = datetime.fromisoformat(latest["started_at"])
            # Resume if the session started within the gap window
            if now - started < self._gap * 2:
                self._current_session_id = latest["id"]
                self._last_clip_time = started
                return

        self._start_new(now)

    def _start_new(self, ts: datetime) -> None:
        self._current_session_id = db.store.create_session(ts)
        self._last_clip_time = ts

    def _close_current(self, ts: datetime) -> None:
        if self._current_session_id is not None:
            db.store.close_session(self._current_session_id, ts)

    def _should_start_new_session(self, ts: datetime) -> bool:
        if self._last_clip_time is None:
            return False
        return (ts - self._last_clip_time) > self._gap

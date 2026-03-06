"""
Tests for session creation, gap detection, and resume logic.
Uses an in-memory SQLite database to avoid touching the real DB.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock


# ── In-memory DB fixture ───────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def mem_db(tmp_path, monkeypatch):
    """
    Redirect store to a fresh in-memory (tmp) database for every test.
    """
    import clipstitch.db.store as store_mod
    db_file = tmp_path / "test.db"
    monkeypatch.setattr(store_mod, "DB_PATH", db_file)
    # Clear any cached thread-local connection
    if hasattr(store_mod._local, "conn") and store_mod._local.conn is not None:
        store_mod._local.conn.close()
        store_mod._local.conn = None
    store_mod.init_db()
    yield store_mod
    if hasattr(store_mod._local, "conn") and store_mod._local.conn is not None:
        store_mod._local.conn.close()
        store_mod._local.conn = None


# ── SessionManager ─────────────────────────────────────────────────────────────

from clipstitch.monitor.session import SessionManager  # noqa: E402


class TestSessionManager:
    def test_creates_session_on_init(self):
        sm = SessionManager()
        assert sm.current_session_id is not None
        assert sm.current_session_id > 0

    def test_new_session_after_gap(self):
        sm = SessionManager()
        first_id = sm.current_session_id

        # Simulate a clip recorded long ago
        past = datetime.now() - timedelta(hours=2)
        sm._last_clip_time = past

        now = datetime.now()
        sm.record_clip(now)

        assert sm.current_session_id != first_id, \
            "Expected a new session after exceeding gap threshold."

    def test_same_session_within_gap(self):
        sm = SessionManager()
        first_id = sm.current_session_id

        # Record a clip just 1 minute after the last
        sm._last_clip_time = datetime.now() - timedelta(minutes=1)
        sm.record_clip(datetime.now())

        assert sm.current_session_id == first_id, \
            "Session should NOT change within gap threshold."

    def test_resume_existing_open_session(self, mem_db):
        """
        If an open session exists and was started recently,
        a new SessionManager should resume it.
        """
        sm1 = SessionManager()
        first_id = sm1.current_session_id

        sm2 = SessionManager()
        assert sm2.current_session_id == first_id, \
            "Expected second SessionManager to resume the existing open session."

    def test_close_session(self, mem_db):
        sm = SessionManager()
        sid = sm.current_session_id
        sm.close()

        sess = mem_db.get_session(sid)
        assert sess["ended_at"] is not None, "Session should have ended_at after close()."

    def test_gap_boundary(self):
        sm = SessionManager()
        first_id = sm.current_session_id

        # Exactly at the gap boundary — should NOT trigger new session
        gap_mins = 30  # default
        sm._last_clip_time = datetime.now() - timedelta(minutes=gap_mins - 1)
        sm.record_clip(datetime.now())
        assert sm.current_session_id == first_id

        # One minute past — SHOULD trigger new session
        sm._last_clip_time = datetime.now() - timedelta(minutes=gap_mins + 1)
        sm.record_clip(datetime.now())
        assert sm.current_session_id != first_id

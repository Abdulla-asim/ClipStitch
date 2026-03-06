"""
Tests for the SQLite storage layer (store.py).
All tests use a temporary database file.
"""

import json
import sqlite3
import pytest
from datetime import datetime, timedelta
from pathlib import Path


# ── Fixture: isolated DB per test ─────────────────────────────────────────────

@pytest.fixture()
def store(tmp_path, monkeypatch):
    import clipstitch.db.store as store_mod
    monkeypatch.setattr(store_mod, "DB_PATH", tmp_path / "test.db")
    # Clear any cached thread-local connection so next _conn() opens a fresh DB
    if hasattr(store_mod._local, "conn") and store_mod._local.conn is not None:
        store_mod._local.conn.close()
        store_mod._local.conn = None
    store_mod.init_db()
    yield store_mod
    # Cleanup after test
    if hasattr(store_mod._local, "conn") and store_mod._local.conn is not None:
        store_mod._local.conn.close()
        store_mod._local.conn = None


# ── Sessions ───────────────────────────────────────────────────────────────────

class TestSessions:
    def test_create_and_get_session(self, store):
        ts  = datetime(2026, 3, 6, 14, 0, 0)
        sid = store.create_session(ts)
        s   = store.get_session(sid)
        assert s is not None
        assert s["id"] == sid
        assert "2026-03-06" in s["started_at"]
        assert s["ended_at"] is None

    def test_close_session(self, store):
        sid = store.create_session(datetime.now())
        end = datetime.now() + timedelta(hours=1)
        store.close_session(sid, end)
        s = store.get_session(sid)
        assert s["ended_at"] is not None

    def test_list_sessions_most_recent_first(self, store):
        ts1 = datetime(2026, 1, 1)
        ts2 = datetime(2026, 3, 1)
        store.create_session(ts1)
        store.create_session(ts2)
        sessions = store.list_sessions()
        assert len(sessions) >= 2
        # Most recent first
        assert sessions[0]["started_at"] > sessions[1]["started_at"]

    def test_get_latest_session(self, store):
        # Create two sessions in the isolated DB; most recent should be returned
        store.create_session(datetime(2026, 1, 1))
        sid2 = store.create_session(datetime(2026, 3, 1))
        latest = store.get_latest_session()
        # The latest session should be the one started on 2026-03-01
        assert latest["id"] == sid2

    def test_set_session_label(self, store):
        sid = store.create_session(datetime.now())
        store.set_session_label(sid, "Test label")
        s = store.get_session(sid)
        assert s["label"] == "Test label"

    def test_get_nonexistent_session(self, store):
        assert store.get_session(9999) is None


# ── Clips ───────────────────────────────────────────────────────────────────────

class TestClips:
    @pytest.fixture()
    def session_id(self, store):
        return store.create_session(datetime.now())

    def test_insert_and_get_clip(self, store, session_id):
        ts  = datetime.now()
        cid = store.insert_clip("Hello world", "text", session_id, ts)
        clips = store.get_clips_for_session(session_id)
        assert len(clips) == 1
        assert clips[0]["id"] == cid
        assert clips[0]["content"] == "Hello world"
        assert clips[0]["content_type"] == "text"

    def test_insert_url_clip_with_title(self, store, session_id):
        store.insert_clip("https://example.com", "url", session_id,
                          datetime.now(), page_title="Example Domain")
        clips = store.get_clips_for_session(session_id)
        assert clips[0]["page_title"] == "Example Domain"

    def test_insert_code_clip_with_language(self, store, session_id):
        store.insert_clip("def f(): pass", "code", session_id,
                          datetime.now(), language="Python")
        clips = store.get_clips_for_session(session_id)
        assert clips[0]["language"] == "Python"

    def test_redacted_clip(self, store, session_id):
        store.insert_clip("sk-secret", "text", session_id,
                          datetime.now(), is_redacted=True)
        clips = store.get_clips_for_session(session_id)
        assert clips[0]["is_redacted"] == 1

    def test_clips_ordered_chronologically(self, store, session_id):
        t0 = datetime(2026, 3, 6, 10, 0)
        t1 = datetime(2026, 3, 6, 10, 5)
        store.insert_clip("first",  "text", session_id, t0)
        store.insert_clip("second", "text", session_id, t1)
        clips = store.get_clips_for_session(session_id)
        assert clips[0]["content"] == "first"
        assert clips[1]["content"] == "second"

    def test_get_clips_by_ids(self, store, session_id):
        id1 = store.insert_clip("A", "text", session_id, datetime(2026,3,6,10,0))
        id2 = store.insert_clip("B", "text", session_id, datetime(2026,3,6,10,1))
        _   = store.insert_clip("C", "text", session_id, datetime(2026,3,6,10,2))
        clips = store.get_clips_by_ids([id1, id2])
        assert len(clips) == 2
        assert {c["content"] for c in clips} == {"A", "B"}

    def test_get_recent_clips(self, store, session_id):
        for i in range(10):
            store.insert_clip(f"clip{i}", "text", session_id,
                              datetime(2026, 3, 6, 10, i))
        recent = store.get_recent_clips(session_id, limit=3)
        assert len(recent) == 3

    def test_get_clips_empty_session(self, store, session_id):
        assert store.get_clips_for_session(session_id) == []

    def test_get_clips_by_ids_empty(self, store):
        assert store.get_clips_by_ids([]) == []


# ── Outputs ────────────────────────────────────────────────────────────────────

class TestOutputs:
    @pytest.fixture()
    def session_id(self, store):
        return store.create_session(datetime.now())

    def test_save_and_retrieve_output(self, store, session_id):
        oid = store.save_output(session_id, "summary", "Bullet points here", [1, 2, 3])
        outputs = store.get_outputs_for_session(session_id)
        assert len(outputs) == 1
        assert outputs[0]["id"] == oid
        assert outputs[0]["mode"] == "summary"
        assert outputs[0]["content"] == "Bullet points here"

    def test_output_clip_ids_serialised(self, store, session_id):
        store.save_output(session_id, "story", "Once upon a time", [5, 6, 7])
        outputs = store.get_outputs_for_session(session_id)
        stored_ids = json.loads(outputs[0]["clip_ids"])
        assert stored_ids == [5, 6, 7]

    def test_outputs_most_recent_first(self, store, session_id):
        store.save_output(session_id, "summary", "First",  None)
        store.save_output(session_id, "story",   "Second", None)
        outputs = store.get_outputs_for_session(session_id)
        assert outputs[0]["mode"] == "story"

    def test_no_outputs(self, store, session_id):
        assert store.get_outputs_for_session(session_id) == []


class TestSchema:
    def test_tables_exist(self, store):
        import sqlite3
        con = sqlite3.connect(str(store.DB_PATH))
        tables = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        con.close()
        assert {"sessions", "clips", "outputs"}.issubset(tables)

"""
Tests for LLM generator — prompt formatting and mock provider calls.
No real LLM calls are made; provider is mocked.
"""

import json
import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch


# ── Fixture: isolated DB ───────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def mem_db(tmp_path, monkeypatch):
    import clipstory.db.store as store_mod
    monkeypatch.setattr(store_mod, "DB_PATH", tmp_path / "test.db")
    if hasattr(store_mod._local, "conn") and store_mod._local.conn is not None:
        store_mod._local.conn.close()
        store_mod._local.conn = None
    store_mod.init_db()
    yield store_mod
    if hasattr(store_mod._local, "conn") and store_mod._local.conn is not None:
        store_mod._local.conn.close()
        store_mod._local.conn = None


# ── Fixture: mock LLM provider ────────────────────────────────────────────────

@pytest.fixture()
def mock_provider():
    provider = MagicMock()
    provider.complete.return_value = "Mocked LLM response."
    with patch("clipstory.llm.generator.get_provider", return_value=provider):
        yield provider


# ── Prompt formatting ─────────────────────────────────────────────────────────

from clipstory.llm.prompts import _format_clips, _meta, MODES, MODE_LABELS  # noqa: E402


_DUMMY_SESSION = {
    "id": 1,
    "started_at": "2026-03-06T10:00:00",
    "ended_at":   "2026-03-06T11:30:00",
    "label": None,
}

_DUMMY_CLIPS = [
    {"id": 1, "content": "Hello world",            "content_type": "text",
     "copied_at": "2026-03-06T10:05:00", "language": None, "page_title": None},
    {"id": 2, "content": "https://example.com",    "content_type": "url",
     "copied_at": "2026-03-06T10:10:00", "language": None, "page_title": "Example Domain"},
    {"id": 3, "content": "def foo(): pass",        "content_type": "code",
     "copied_at": "2026-03-06T10:15:00", "language": "Python", "page_title": None},
]


class TestPromptFormatting:
    def test_format_clips_contains_content(self):
        text = _format_clips(_DUMMY_CLIPS)
        assert "Hello world" in text
        assert "https://example.com" in text
        assert "def foo(): pass" in text

    def test_format_clips_contains_timestamps(self):
        text = _format_clips(_DUMMY_CLIPS)
        assert "10:05" in text

    def test_format_clips_contains_type_labels(self):
        text = _format_clips(_DUMMY_CLIPS)
        assert "TEXT" in text
        assert "URL" in text
        assert "CODE" in text

    def test_format_clips_url_shows_page_title(self):
        text = _format_clips(_DUMMY_CLIPS)
        assert "Example Domain" in text

    def test_format_clips_code_shows_language(self):
        text = _format_clips(_DUMMY_CLIPS)
        assert "Python" in text

    def test_meta_duration(self):
        m = _meta(_DUMMY_SESSION, _DUMMY_CLIPS)
        assert m["duration"] == "1h 30m"

    def test_meta_count(self):
        m = _meta(_DUMMY_SESSION, _DUMMY_CLIPS)
        assert m["count"] == 3

    def test_long_clip_truncated(self):
        long_clip = {"id": 99, "content": "X" * 1000, "content_type": "text",
                     "copied_at": "2026-03-06T10:00:00", "language": None, "page_title": None}
        text = _format_clips([long_clip])
        assert "[truncated]" in text

    def test_all_modes_return_two_strings(self):
        for mode, fn in MODES.items():
            sys_p, usr_p = fn(_DUMMY_SESSION, _DUMMY_CLIPS)
            assert isinstance(sys_p, str) and len(sys_p) > 0, f"mode={mode} empty system prompt"
            assert isinstance(usr_p, str) and len(usr_p) > 0, f"mode={mode} empty user prompt"

    def test_mode_labels_complete(self):
        assert set(MODE_LABELS.keys()) == set(MODES.keys())


# ── Generator ─────────────────────────────────────────────────────────────────

from clipstory.llm import generator  # noqa: E402


class TestGenerator:
    @pytest.fixture()
    def session_with_clips(self, mem_db):
        sid = mem_db.create_session(datetime(2026, 3, 6, 10, 0))
        mem_db.close_session(sid, datetime(2026, 3, 6, 11, 30))
        mem_db.insert_clip("Hello",             "text", sid, datetime(2026,3,6,10,5))
        mem_db.insert_clip("https://x.com",     "url",  sid, datetime(2026,3,6,10,10))
        mem_db.insert_clip("def f(): pass",     "code", sid, datetime(2026,3,6,10,15))
        return sid

    def test_generate_returns_string(self, session_with_clips, mock_provider):
        result = generator.generate(session_with_clips, "summary")
        assert isinstance(result, str)
        assert result == "Mocked LLM response."

    def test_generate_calls_provider(self, session_with_clips, mock_provider):
        generator.generate(session_with_clips, "story")
        mock_provider.complete.assert_called_once()

    def test_generate_saves_output(self, session_with_clips, mock_provider, mem_db):
        generator.generate(session_with_clips, "worklog")
        outputs = mem_db.get_outputs_for_session(session_with_clips)
        assert len(outputs) == 1
        assert outputs[0]["mode"] == "worklog"
        assert outputs[0]["content"] == "Mocked LLM response."

    def test_generate_with_clip_ids(self, session_with_clips, mock_provider, mem_db):
        clips = mem_db.get_clips_for_session(session_with_clips)
        subset_ids = [clips[0]["id"]]
        generator.generate(session_with_clips, "summary", clip_ids=subset_ids)
        # Provider should have been called with a user prompt mentioning only 1 clip
        call_args = mock_provider.complete.call_args
        user_prompt = call_args[0][1]
        # Only the first clip content should appear
        assert clips[0]["content"] in user_prompt

    def test_generate_unknown_mode_raises(self, session_with_clips, mock_provider):
        with pytest.raises(ValueError, match="Unknown mode"):
            generator.generate(session_with_clips, "invalid_mode")

    def test_generate_nonexistent_session_raises(self, mock_provider):
        with pytest.raises(ValueError, match="Session"):
            generator.generate(9999, "summary")

    def test_generate_empty_session_raises(self, mem_db, mock_provider):
        sid = mem_db.create_session(datetime.now())
        with pytest.raises(ValueError, match="No clips"):
            generator.generate(sid, "summary")

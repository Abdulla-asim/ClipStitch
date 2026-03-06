"""
Tests for PDF and Markdown export.
"""

import io
import pytest
from datetime import datetime


# ── Fixture: isolated DB with test data ───────────────────────────────────────

@pytest.fixture()
def store(tmp_path, monkeypatch):
    import clipstory.db.store as store_mod
    monkeypatch.setattr(store_mod, "DB_PATH", tmp_path / "test.db")
    store_mod.init_db()
    return store_mod


@pytest.fixture()
def populated_session(store):
    """Create a session with clips and a saved output."""
    sid = store.create_session(datetime(2026, 3, 6, 10, 0, 0))
    store.close_session(sid, datetime(2026, 3, 6, 11, 30, 0))
    store.insert_clip("Copied some text",        "text", sid, datetime(2026,3,6,10,5))
    store.insert_clip("https://example.com",     "url",  sid, datetime(2026,3,6,10,10),
                      page_title="Example Domain")
    store.insert_clip("def hello(): return 42",  "code", sid, datetime(2026,3,6,10,15),
                      language="Python")
    oid = store.save_output(sid, "summary",
                             "## Summary\n\nDid some work today.\n\n- Task A\n- Task B",
                             [1, 2, 3])
    return sid, oid


# ── PDF export ────────────────────────────────────────────────────────────────

class TestPDFExport:
    def test_pdf_returns_bytes(self, populated_session):
        sid, oid = populated_session
        from clipstory.export.pdf import export_pdf
        data = export_pdf(sid, oid)
        assert isinstance(data, bytes)

    def test_pdf_starts_with_pdf_magic(self, populated_session):
        sid, oid = populated_session
        from clipstory.export.pdf import export_pdf
        data = export_pdf(sid, oid)
        assert data.startswith(b"%PDF"), "PDF bytes should start with %PDF magic bytes"

    def test_pdf_without_output(self, populated_session):
        """PDF without a saved LLM output should still work (clip timeline only)."""
        sid, _ = populated_session
        from clipstory.export.pdf import export_pdf
        data = export_pdf(sid, output_id=None)
        assert data.startswith(b"%PDF")

    def test_pdf_nonexistent_session_raises(self):
        from clipstory.export.pdf import export_pdf
        with pytest.raises(Exception):
            export_pdf(9999)

    def test_pdf_not_empty(self, populated_session):
        sid, oid = populated_session
        from clipstory.export.pdf import export_pdf
        data = export_pdf(sid, oid)
        assert len(data) > 1024, "PDF should be more than 1 KB"


# ── Markdown export ───────────────────────────────────────────────────────────

class TestMarkdownExport:
    def test_markdown_returns_string(self, populated_session):
        sid, oid = populated_session
        from clipstory.export.markdown import export_markdown
        md = export_markdown(sid, oid)
        assert isinstance(md, str)

    def test_markdown_contains_session_date(self, populated_session):
        sid, oid = populated_session
        from clipstory.export.markdown import export_markdown
        md = export_markdown(sid, oid)
        assert "2026" in md

    def test_markdown_contains_clip_content(self, populated_session):
        sid, oid = populated_session
        from clipstory.export.markdown import export_markdown
        md = export_markdown(sid, oid)
        assert "Copied some text" in md

    def test_markdown_contains_url(self, populated_session):
        sid, oid = populated_session
        from clipstory.export.markdown import export_markdown
        md = export_markdown(sid, oid)
        assert "https://example.com" in md

    def test_markdown_contains_llm_output(self, populated_session):
        sid, oid = populated_session
        from clipstory.export.markdown import export_markdown
        md = export_markdown(sid, oid)
        assert "Did some work today" in md

    def test_markdown_without_output(self, populated_session):
        sid, _ = populated_session
        from clipstory.export.markdown import export_markdown
        md = export_markdown(sid, output_id=None)
        assert "Copied some text" in md

    def test_filename_for_session(self, populated_session):
        sid, _ = populated_session
        from clipstory.export.markdown import filename_for_session
        name = filename_for_session(sid, "pdf")
        assert name.endswith(".pdf")
        assert "clipstory" in name.lower() or str(sid) in name

    def test_markdown_has_header(self, populated_session):
        sid, oid = populated_session
        from clipstory.export.markdown import export_markdown
        md = export_markdown(sid, oid)
        assert md.startswith("# ")

    def test_markdown_clip_timeline_table(self, populated_session):
        sid, oid = populated_session
        from clipstory.export.markdown import export_markdown
        md = export_markdown(sid, oid)
        assert "| Time" in md or "##" in md, \
            "Markdown should contain a timeline section"

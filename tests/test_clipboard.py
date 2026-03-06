"""
Tests for clipboard type detection, deduplication, and privacy filter.
These tests do NOT require the Win32 clipboard or pywin32.
"""

import hashlib
import pytest
from unittest.mock import MagicMock, patch


# ── Helpers pulled from clipboard.py without importing pywin32 ────────────────

import importlib, sys, types

# Stub out win32 modules so clipboard.py can be imported headlessly
for mod_name in ["win32api", "win32clipboard", "win32con", "win32gui"]:
    stub = types.ModuleType(mod_name)
    stub.WM_CLIPBOARDUPDATE = 0x031D
    stub.CF_UNICODETEXT = 13
    stub.HWND_MESSAGE = -3
    sys.modules.setdefault(mod_name, stub)

from clipstory.monitor.clipboard import _classify, _detect_language, _hash  # noqa: E402


# ── Type classification ────────────────────────────────────────────────────────

class TestClassify:
    def test_url_http(self):
        assert _classify("https://example.com/path?q=1") == "url"

    def test_url_http_plain(self):
        assert _classify("http://localhost:8080") == "url"

    def test_url_http_with_whitespace(self):
        assert _classify("  https://google.com  ") == "url"

    def test_code_python(self):
        snippet = "def foo():\n    import os\n    return os.getcwd()"
        assert _classify(snippet) == "code"

    def test_code_javascript(self):
        snippet = "function bar() {\n  console.log('hi');\n}"
        assert _classify(snippet) == "code"

    def test_code_java(self):
        snippet = "public static void main(String[] args) {\n  import java.util.*;\n}"
        assert _classify(snippet) == "code"

    def test_text_plain(self):
        assert _classify("Hello, world!") == "text"

    def test_text_single_code_hint(self):
        # Only one hint — should NOT be classified as code
        assert _classify("def foo(): pass") == "text"

    def test_empty_string(self):
        assert _classify("") == "text"


# ── Deduplication hash ─────────────────────────────────────────────────────────

class TestHash:
    def test_same_input_same_hash(self):
        assert _hash("hello") == _hash("hello")

    def test_different_input_different_hash(self):
        assert _hash("hello") != _hash("world")

    def test_unicode(self):
        h = _hash("🧠 AI")
        assert isinstance(h, str) and len(h) == 64


# ── Privacy filter ─────────────────────────────────────────────────────────────

from clipstory.monitor.privacy import apply_privacy_filter  # noqa: E402


class TestPrivacyFilter:
    def test_password_pattern(self):
        text, redacted = apply_privacy_filter("password=mysecret123")
        assert redacted is True
        assert "[REDACTED]" in text
        assert "mysecret123" not in text

    def test_api_key_prefix_sk(self):
        text, redacted = apply_privacy_filter("sk-" + "a" * 40)
        assert redacted is True
        assert "[REDACTED_KEY]" in text

    def test_api_key_prefix_AIza(self):
        text, redacted = apply_privacy_filter("AIza" + "b" * 35)
        assert redacted is True

    def test_long_alphanum_token(self):
        # 40-char alphanumeric string — should be redacted
        token = "A" * 40
        text, redacted = apply_privacy_filter(token)
        assert redacted is True

    def test_clean_text_not_redacted(self):
        text, redacted = apply_privacy_filter("Hello, this is clean text.")
        assert redacted is False
        assert text == "Hello, this is clean text."

    def test_email_not_redacted_by_default(self):
        """Emails should remain unless the privacy config says otherwise."""
        text, redacted = apply_privacy_filter("user@example.com")
        # Email redaction defaults to False in config, so no redaction expected
        assert "user@example.com" in text

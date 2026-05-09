"""
Event-driven Win32 clipboard monitor for clipstitch.

Uses WM_CLIPBOARDUPDATE message (AddClipboardFormatListener) so the OS
notifies us instantly on every clipboard change — no polling, zero CPU waste.
"""

import hashlib
import re
import threading
import logging
import ctypes
import ctypes.wintypes
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import win32api
import win32clipboard
import win32con
import win32gui

import requests
from pygments.lexers import guess_lexer
from pygments.util import ClassNotFound

from clipstitch.config import get
from clipstitch.db import store
from clipstitch.monitor.privacy import apply_privacy_filter
from clipstitch.monitor.session import SessionManager

log = logging.getLogger(__name__)

# WM_CLIPBOARDUPDATE is not exposed in older pywin32 builds — define it directly.
WM_CLIPBOARDUPDATE = 0x031D

# AddClipboardFormatListener / RemoveClipboardFormatListener are also missing
# from some pywin32 builds; call them via ctypes instead.
_user32 = ctypes.windll.user32
_user32.AddClipboardFormatListener.argtypes    = [ctypes.wintypes.HWND]
_user32.AddClipboardFormatListener.restype     = ctypes.wintypes.BOOL
_user32.RemoveClipboardFormatListener.argtypes = [ctypes.wintypes.HWND]
_user32.RemoveClipboardFormatListener.restype  = ctypes.wintypes.BOOL


def _add_clipboard_listener(hwnd: int) -> None:
    if not _user32.AddClipboardFormatListener(hwnd):
        raise ctypes.WinError()


def _remove_clipboard_listener(hwnd: int) -> None:
    _user32.RemoveClipboardFormatListener(hwnd)

# URL pattern
_URL_RE = re.compile(r'^https?://\S+', re.IGNORECASE)

# Code heuristics — presence of multiple indicators → classify as code
_CODE_HINTS = [
    r'\bdef\s+\w+\s*\(',
    r'\bclass\s+\w+[\s(:]',
    r'\bimport\s+\w+',
    r'\bfrom\s+\w+\s+import\b',
    r'#include\s*<',
    r'\bfunction\s+\w+\s*\(',
    r'=>\s*\{',
    r'console\.log\(',
    r'\bpublic\s+static\s+void\b',
    r'<\w+>.*</\w+>',  # XML/HTML tags
]
_CODE_RE = re.compile('|'.join(_CODE_HINTS), re.MULTILINE)


class ClipboardMonitor(threading.Thread):
    """
    Background thread that registers a hidden Win32 window as a clipboard
    listener and processes every clipboard change event.
    """

    def __init__(self):
        super().__init__(name="ClipboardMonitor", daemon=True)
        self._session = SessionManager()
        self._last_hash: str | None = None
        self._dedup_window: int = get("monitor.dedup_window", 5)
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ClipWorker")
        self._hwnd: int | None = None
        self._stop_event = threading.Event()
        self._paused: bool = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def run(self) -> None:
        """Create a hidden window and pump Win32 messages."""
        wc = win32gui.WNDCLASS()
        wc.lpszClassName = "clipstitchListener"
        wc.lpfnWndProc = self._wnd_proc
        wc.hInstance = win32api.GetModuleHandle(None)
        win32gui.RegisterClass(wc)

        self._hwnd = win32gui.CreateWindow(
            wc.lpszClassName,
            "clipstitchListener",
            0, 0, 0, 0, 0,
            win32con.HWND_MESSAGE,  # message-only window
            None, wc.hInstance, None,
        )
        _add_clipboard_listener(self._hwnd)
        log.info("Clipboard monitor started (event-driven).")

        # Pump messages until stop requested
        while not self._stop_event.is_set():
            win32gui.PumpWaitingMessages()
            self._stop_event.wait(timeout=0.1)

        # Cleanup
        _remove_clipboard_listener(self._hwnd)
        win32gui.DestroyWindow(self._hwnd)
        self._session.close()
        self._executor.shutdown(wait=False)
        log.info("Clipboard monitor stopped.")

    def stop(self) -> None:
        self._stop_event.set()

    def pause(self) -> None:
        """Pause clip processing (clipboard events still received but discarded)."""
        self._paused = True
        log.info("Clipboard monitoring paused.")

    def resume(self) -> None:
        """Resume clip processing."""
        self._paused = False
        log.info("Clipboard monitoring resumed.")

    @property
    def current_session_id(self) -> int | None:
        return self._session.current_session_id

    # ── Win32 message handler ─────────────────────────────────────────────────

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_CLIPBOARDUPDATE:
            self._on_clipboard_change()
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    # ── Core processing ───────────────────────────────────────────────────────

    def _on_clipboard_change(self) -> None:
        """Called by the Win32 message loop on every clipboard change."""
        if self._paused:
            return

        # ── Image path (check BEFORE text) ────────────────────────────────────
        from clipstitch.monitor.image import has_image_on_clipboard
        if has_image_on_clipboard():
            self._executor.submit(self._store_image_clip, datetime.now())
            return

        # ── Text / URL / Code path ────────────────────────────────────────────
        try:
            win32clipboard.OpenClipboard()
            try:
                if not win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                    return
                content = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
            finally:
                win32clipboard.CloseClipboard()
        except Exception as e:
            log.debug("Clipboard read error: %s", e)
            return

        if not content or not content.strip():
            return

        # Deduplicate against last hash
        h = _hash(content)
        if h == self._last_hash:
            return
        self._last_hash = h

        now = datetime.now()

        # Apply privacy filter
        filtered, was_redacted = apply_privacy_filter(content)

        # Deduplicate against recent DB clips
        if self._is_duplicate(filtered):
            return

        # Classify type
        ctype = _classify(filtered)

        # Update session (may start a new one)
        self._session.record_clip(now)
        sid = self._session.current_session_id

        if ctype == "url":
            # Fetch page title asynchronously, then store
            self._executor.submit(self._store_url_clip, filtered, sid, now, was_redacted)
        elif ctype == "code":
            lang = _detect_language(filtered)
            store.insert_clip(filtered, "code", sid, now, language=lang, is_redacted=was_redacted)
            log.debug("Stored code clip (lang=%s)", lang)
        else:
            store.insert_clip(filtered, "text", sid, now, is_redacted=was_redacted)
            log.debug("Stored text clip (%d chars)", len(filtered))

    def _store_url_clip(self, url: str, sid: int, ts: datetime, redacted: bool) -> None:
        title = _fetch_page_title(url)
        store.insert_clip(url, "url", sid, ts, page_title=title, is_redacted=redacted)
        log.debug("Stored URL clip: %s (title=%s)", url, title)

    def _store_image_clip(self, ts: datetime) -> None:
        """Capture image from clipboard, save thumbnail, store clip, trigger vision AI."""
        from clipstitch.monitor.image import (
            capture_image_from_clipboard, save_thumbnail, describe_image_async
        )
        img = capture_image_from_clipboard()
        if img is None:
            return

        self._session.record_clip(ts)
        sid = self._session.current_session_id

        # Save thumbnail first (we need a path for the DB record)
        try:
            thumb_path = save_thumbnail(img, f"s{sid}")
        except Exception as e:
            log.warning("Could not save thumbnail: %s", e)
            return

        # Content field stores a human-readable label
        label = f"[Image {img.width}×{img.height}px]"
        clip_id = store.insert_clip(
            label, "image", sid, ts,
            thumbnail_path=thumb_path,
        )
        log.debug("Stored image clip id=%d (%s)", clip_id, label)

        # Ask vision AI to describe it asynchronously (won't block monitoring)
        if get("monitor.vision_describe", True):
            describe_image_async(clip_id, thumb_path)

    def _is_duplicate(self, content: str) -> bool:
        """Return True if content matches any of the last N clips in the session."""
        sid = self._session.current_session_id
        if sid is None:
            return False
        recent = store.get_recent_clips(sid, self._dedup_window)
        h = _hash(content)
        return any(_hash(c["content"]) == h for c in recent)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _classify(text: str) -> str:
    """Classify a clip as 'url', 'code', or 'text'."""
    stripped = text.strip()
    if _URL_RE.match(stripped):
        return "url"
    # Require at least 2 code hint matches to avoid false positives
    matches = len(_CODE_RE.findall(stripped))
    if matches >= 2:
        return "code"
    return "text"


def _detect_language(code: str) -> str | None:
    """Use Pygments to guess the programming language."""
    try:
        lexer = guess_lexer(code)
        name = lexer.name
        # Skip generic/fallback lexers
        if name.lower() in ("text only", "plaintext"):
            return None
        return name
    except ClassNotFound:
        return None


def _fetch_page_title(url: str) -> str | None:
    """Fetch the <title> of a web page. Returns None on failure."""
    try:
        resp = requests.get(url, timeout=5, headers={"User-Agent": "clipstitch/1.0"})
        resp.raise_for_status()
        # Quick regex extract rather than full HTML parse
        m = re.search(r'<title[^>]*>(.*?)</title>', resp.text, re.IGNORECASE | re.DOTALL)
        if m:
            return m.group(1).strip()[:256]
    except Exception as e:
        log.debug("Failed to fetch title for %s: %s", url, e)
    return None

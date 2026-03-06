"""
System tray icon and menu for ClipStory.

Uses pystray + Pillow for the tray icon and keyboard for global hotkeys.
Must be started from the main thread on Windows.
"""

import logging
import threading
import webbrowser
from pathlib import Path

import keyboard
import pystray
from PIL import Image, ImageDraw, ImageFont

from clipstory import config as cfg

log = logging.getLogger(__name__)

_DEFAULT_ICON = Path(__file__).parent.parent.parent / "assets" / "icon.png"


# ─── Icon drawing ─────────────────────────────────────────────────────────────

def _make_icon_image(size: int = 64) -> Image.Image:
    """
    Return a PIL Image for the tray icon.
    Falls back to a generated indigo-gradient icon if assets/icon.png
    is not available.
    """
    if _DEFAULT_ICON.exists():
        img = Image.open(_DEFAULT_ICON).convert("RGBA")
        return img.resize((size, size), Image.LANCZOS)

    # Generated fallback icon
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Indigo circle background
    draw.ellipse([0, 0, size - 1, size - 1], fill=(99, 102, 241, 255))
    # White "C" glyph
    margin  = size // 5
    w       = size // 10
    draw.arc([margin, margin, size - margin, size - margin],
             start=45, end=315, fill=(255, 255, 255, 255), width=w)
    return img


# ─── Tray setup ───────────────────────────────────────────────────────────────

class TrayIcon:
    """
    Owns the pystray icon and keyboard hotkeys.
    Run `start()` from the main thread; it blocks until `stop()` is called.
    """

    def __init__(self, monitor=None, on_quit=None):
        self._monitor  = monitor
        self._on_quit  = on_quit
        self._port     = cfg.get("web.port", 5050)
        self._icon     = None
        self._paused   = False

    # ── Public API ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Build the icon and start the tray (blocking)."""
        self._register_hotkeys()
        img  = _make_icon_image(64)
        menu = self._build_menu()
        self._icon = pystray.Icon(
            "ClipStory",
            img,
            "ClipStory",
            menu=menu,
        )
        log.info("System tray started.")
        self._icon.run()  # Blocks until icon.stop() is called

    def stop(self) -> None:
        if self._icon:
            self._icon.stop()
        keyboard.unhook_all()

    def update_tooltip(self, clip_count: int) -> None:
        """Update tray tooltip with current clip count."""
        if self._icon:
            self._icon.title = f"ClipStory — {clip_count} clips"

    # ── Menu ───────────────────────────────────────────────────────────────────

    def _build_menu(self) -> pystray.Menu:
        return pystray.Menu(
            pystray.MenuItem("📋 Open Dashboard",  self._open_dashboard, default=True),
            pystray.MenuItem("✦ Generate Summary", self._quick_generate),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "⏸ Pause Monitoring",
                self._toggle_pause,
                checked=lambda item: self._paused,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("❌ Quit",             self._quit),
        )

    # ── Actions ────────────────────────────────────────────────────────────────

    def _open_dashboard(self, icon=None, item=None) -> None:
        url = f"http://localhost:{self._port}"
        log.info("Opening dashboard: %s", url)
        webbrowser.open(url)

    def _quick_generate(self, icon=None, item=None) -> None:
        """Generate a summary for the current session and open the dashboard."""
        threading.Thread(target=self._do_quick_generate, daemon=True).start()

    def _do_quick_generate(self) -> None:
        try:
            from clipstory.llm import generator
            if self._monitor and self._monitor.current_session_id:
                sid = self._monitor.current_session_id
                generator.generate(sid, "summary")
                log.info("Quick generate complete for session %d", sid)
            self._open_dashboard()
        except Exception as e:
            log.error("Quick generate failed: %s", e)

    def _toggle_pause(self, icon=None, item=None) -> None:
        self._paused = not self._paused
        if self._monitor:
            if self._paused:
                self._monitor.pause()
            else:
                self._monitor.resume()
        log.info("Monitor %s", "paused" if self._paused else "resumed")

    def _quit(self, icon=None, item=None) -> None:
        log.info("Quit requested from tray.")
        self.stop()
        if self._on_quit:
            self._on_quit()

    # ── Hotkeys ────────────────────────────────────────────────────────────────

    def _register_hotkeys(self) -> None:
        open_hk    = cfg.get("hotkeys.open_dashboard", "ctrl+shift+s")
        generate_hk = cfg.get("hotkeys.quick_generate",  "ctrl+shift+g")

        try:
            keyboard.add_hotkey(open_hk,    self._open_dashboard,  suppress=True)
            keyboard.add_hotkey(generate_hk, self._quick_generate,  suppress=True)
            log.info("Hotkeys registered: %s (open), %s (generate)", open_hk, generate_hk)
        except Exception as e:
            log.warning("Failed to register hotkeys: %s", e)

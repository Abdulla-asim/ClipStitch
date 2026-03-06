"""
ClipStory — Entry point.

Starts three subsystems:
  1. SQLite database initialisation
  2. Clipboard monitor (background thread)
  3. Flask web server (background thread)
  4. System tray icon (main thread — required by pystray on Windows)
"""

import logging
import sys
import threading
import webbrowser
from pathlib import Path

# Load .env before anything else (side-effect: dotenv is loaded when config imports)
from clipstory import config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            Path(__file__).parent.parent / "clipstory.log",
            encoding="utf-8",
        ),
    ],
)

log = logging.getLogger("clipstory.main")


def main() -> None:
    # ── 1. Database ────────────────────────────────────────────────────────────
    from clipstory.db import store
    store.init_db()
    log.info("Database initialised.")

    # ── 2. Clipboard monitor ───────────────────────────────────────────────────
    from clipstory.monitor.clipboard import ClipboardMonitor
    monitor = ClipboardMonitor()
    monitor.start()
    log.info("Clipboard monitor thread started.")

    # ── 3. Flask web server ────────────────────────────────────────────────────
    from clipstory.web.app import app, set_monitor
    set_monitor(monitor)

    port = config.get("web.port", 5050)

    flask_thread = threading.Thread(
        target=lambda: app.run(
            host="127.0.0.1",
            port=port,
            debug=False,
            use_reloader=False,
        ),
        name="FlaskServer",
        daemon=True,
    )
    flask_thread.start()
    log.info("Web server started on http://127.0.0.1:%d", port)

    # Optionally open browser on start
    if config.get("web.open_on_start", False):
        webbrowser.open(f"http://127.0.0.1:{port}")

    # ── 4. Graceful shutdown callback ──────────────────────────────────────────
    def on_quit():
        log.info("Shutting down ClipStory…")
        monitor.stop()
        monitor.join(timeout=3)
        log.info("Goodbye.")
        sys.exit(0)

    # ── 5. System tray (blocks main thread) ────────────────────────────────────
    try:
        from clipstory.tray.icon import TrayIcon
        tray = TrayIcon(monitor=monitor, on_quit=on_quit)
        tray.start()
    except Exception as e:
        log.warning("Tray icon unavailable (%s). Running headless — press Ctrl+C to quit.", e)
        try:
            flask_thread.join()
        except KeyboardInterrupt:
            on_quit()


if __name__ == "__main__":
    main()

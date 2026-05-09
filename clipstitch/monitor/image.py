"""
Image clip handler for ClipStitch.

Detects when the clipboard contains a bitmap/screenshot,
saves a PNG thumbnail to disk, and optionally requests an
AI-generated description via the vision-capable LLM provider.
"""

import base64
import io
import logging
import threading
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

# Where thumbnails are stored (sibling of the DB file)
_THUMB_DIR = Path(__file__).parent.parent.parent / "thumbnails"

# Max thumbnail dimension (longest side)
_THUMB_MAX_PX = 512


def _ensure_thumb_dir() -> Path:
    _THUMB_DIR.mkdir(parents=True, exist_ok=True)
    return _THUMB_DIR


def capture_image_from_clipboard() -> "PIL.Image.Image | None":
    """
    Try to read a DIB/bitmap from the Win32 clipboard.
    Returns a PIL Image, or None if no image is available.
    Must be called with the clipboard already CLOSED (we open it ourselves).
    """
    try:
        import win32clipboard
        import win32con
        from PIL import Image

        win32clipboard.OpenClipboard()
        try:
            if win32clipboard.IsClipboardFormatAvailable(win32con.CF_DIB):
                data = win32clipboard.GetClipboardData(win32con.CF_DIB)
                # CF_DIB is a BITMAPINFO header + pixel data; wrap in BMP file header
                bmp_header = b"BM" + (len(data) + 14).to_bytes(4, "little") + b"\x00\x00\x00\x00" + b"\x36\x00\x00\x00"
                bmp_data = bmp_header + data
                img = Image.open(io.BytesIO(bmp_data))
                return img.convert("RGBA")
            # Fallback: PNG on clipboard (e.g. from browser "copy image")
            CF_PNG = win32clipboard.RegisterClipboardFormat("PNG")
            if win32clipboard.IsClipboardFormatAvailable(CF_PNG):
                data = win32clipboard.GetClipboardData(CF_PNG)
                img = Image.open(io.BytesIO(data))
                return img.convert("RGBA")
        finally:
            win32clipboard.CloseClipboard()
    except Exception as e:
        log.debug("Image clipboard read failed: %s", e)
    return None


def has_image_on_clipboard() -> bool:
    """Quick check — does the clipboard currently hold an image?"""
    try:
        import win32clipboard
        import win32con

        win32clipboard.OpenClipboard()
        try:
            has_dib = win32clipboard.IsClipboardFormatAvailable(win32con.CF_DIB)
            CF_PNG = win32clipboard.RegisterClipboardFormat("PNG")
            has_png = win32clipboard.IsClipboardFormatAvailable(CF_PNG)
            return bool(has_dib or has_png)
        finally:
            win32clipboard.CloseClipboard()
    except Exception:
        return False


def save_thumbnail(img: "PIL.Image.Image", clip_id_hint: str) -> str:
    """
    Resize image to _THUMB_MAX_PX on the longest side and save as PNG.
    Returns the absolute path string of the saved thumbnail.
    """
    from PIL import Image

    thumb_dir = _ensure_thumb_dir()
    img.thumbnail((_THUMB_MAX_PX, _THUMB_MAX_PX), Image.LANCZOS)
    # Convert RGBA → RGB so JPEG-safe if ever needed; keep PNG for lossless
    if img.mode in ("RGBA", "P"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[3] if img.mode == "RGBA" else None)
        img = background
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"img_{ts}_{clip_id_hint}.png"
    path = thumb_dir / filename
    img.save(str(path), format="PNG")
    log.info("Thumbnail saved: %s", path)
    return str(path)


def image_to_base64(image_path: str) -> str:
    """Return a base64-encoded PNG string for the given file path."""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def describe_image_async(clip_id: int, thumbnail_path: str) -> None:
    """
    Fire-and-forget: ask the LLM provider to describe the image,
    then update the DB record. Runs in a daemon thread.
    """
    def _run():
        try:
            from clipstitch.llm.provider import get_provider
            from clipstitch.db import store

            provider = get_provider()
            description = provider.describe_image(thumbnail_path)
            if description:
                store.update_clip_image_description(clip_id, description)
                log.info("Image description stored for clip %d", clip_id)
        except Exception as e:
            log.warning("Image description failed for clip %d: %s", clip_id, e)

    t = threading.Thread(target=_run, name=f"VisionDescribe-{clip_id}", daemon=True)
    t.start()

"""
Apprise-based fan-out for post-generation notifications.
Called after the image is already posted to Matrix natively.
"""
import tempfile
from pathlib import Path

from loguru import logger


def fan_out(
    urls: list[str],
    title: str,
    body: str,
    image_data: bytes = None,
    mime: str = "image/png",
) -> None:
    """Send notification to all configured Apprise URLs, optionally with an image attachment."""
    if not urls:
        return
    try:
        import apprise
    except ImportError:
        logger.warning("apprise not installed — skipping fan-out")
        return

    ap = apprise.Apprise()
    for url in urls:
        ap.add(url)

    attach = None
    tmp_path = None
    if image_data:
        suffix = ".mp4" if "mp4" in mime or "video" in mime else ".png"
        tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        tmp.write(image_data)
        tmp.close()
        tmp_path = tmp.name
        attach = apprise.AppriseAttachment()
        attach.add(tmp_path)

    try:
        ap.notify(title=title, body=body, attach=attach)
    except Exception as e:
        logger.warning(f"Apprise fan-out failed: {e}")
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)

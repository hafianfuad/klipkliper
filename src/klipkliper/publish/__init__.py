"""Publisher autopost Klipkliper (EKSPERIMENTAL).

Platform: youtube, tiktok, instagram, facebook.
Semua mendukung dry_run=True untuk tes tanpa kredensial.
"""
from .base import Publisher, PublishError

__all__ = ["Publisher", "PublishError", "make_publisher", "AVAILABLE"]

AVAILABLE = ("youtube", "tiktok", "instagram", "facebook")


def make_publisher(name: str, **kw) -> Publisher:
    """Factory publisher. name: youtube|tiktok|instagram|facebook."""
    key = (name or "").strip().lower()
    if key == "youtube":
        from .youtube import YouTubePublisher
        return YouTubePublisher(**kw)
    if key == "tiktok":
        from .tiktok import TikTokPublisher
        return TikTokPublisher(**kw)
    if key == "instagram":
        from .instagram import InstagramPublisher
        return InstagramPublisher(**kw)
    if key == "facebook":
        from .facebook import FacebookPublisher
        return FacebookPublisher(**kw)
    raise ValueError(
        f"publisher tak dikenal: {name!r} (tersedia: {', '.join(AVAILABLE)})"
    )

"""Publisher service -- orchestrates content distribution across platforms.

Provides a high-level interface for publishing content to Instagram,
YouTube, and TikTok using the corresponding integration clients.
"""
from __future__ import annotations

from typing import Dict, Optional

from sqlalchemy.orm import Session

from app.integrations.instagram_client import InstagramClient, InstagramPublishError
from app.integrations.tiktok_client import TikTokClient, TikTokPublishError
from app.integrations.youtube_client import YouTubeClient, YouTubeUploadError
from app.models.bot import Bot
from app.models.content import ContentItem
from app.models.credential import SocialCredential
from app.utils.encryption import FieldEncryptor
from app.utils.logging_config import get_logger

logger = get_logger(__name__)

# Maps platform name -> (content description field, published-id field)
_PLATFORM_MAP: Dict[str, tuple] = {
    "instagram": ("description_instagram", "publish_instagram_id"),
    "youtube": ("description_youtube", "publish_youtube_id"),
    "tiktok": ("description_tiktok", "publish_tiktok_id"),
}


class PublishError(Exception):
    """Raised when a publish operation fails for a specific platform."""

    def __init__(self, platform: str, reason: str) -> None:
        self.platform = platform
        self.reason = reason
        super().__init__(f"[{platform}] {reason}")


def _decrypt_token(encrypted: Optional[str]) -> str:
    """Decrypt a credential token.  Returns empty string on failure."""
    if not encrypted:
        return ""
    try:
        from app.config import settings
        enc = FieldEncryptor(settings.encryption_key)
        return enc.decrypt(encrypted)
    except Exception:
        # Token might be stored in plaintext (e.g. during tests)
        return encrypted


# ------------------------------------------------------------------
# Single-platform publishing
# ------------------------------------------------------------------

async def publish_to_platform(
    content: ContentItem,
    credential: SocialCredential,
    platform: str,
) -> str:
    """Publish *content* to a single *platform*.

    Parameters
    ----------
    content:
        The ContentItem model with video and description data.
    credential:
        SocialCredential with encrypted tokens.
    platform:
        One of ``"instagram"``, ``"youtube"``, or ``"tiktok"``.

    Returns
    -------
    str
        The platform-specific published / media ID.
    """
    platform = platform.lower().strip()
    access_token = _decrypt_token(credential.access_token_encrypted)

    if not access_token:
        raise PublishError(platform, "No access token available")

    logger.info(
        "Publishing content (id=%s) to %s",
        content.id,
        platform,
    )

    try:
        if platform == "instagram":
            if not content.video_url:
                raise PublishError(platform, "No video_url set on content")
            client = InstagramClient(access_token=access_token)
            caption = content.description_instagram or ""
            published_id = await client.publish_reel(
                ig_user_id=credential.platform_user_id or "",
                video_url=content.video_url,
                caption=caption,
            )

        elif platform == "youtube":
            if not content.video_file_path:
                raise PublishError(platform, "No video_file_path set on content")
            client = YouTubeClient(access_token=access_token)
            # Parse YouTube description for title/description/tags
            yt_desc = content.description_youtube or ""
            parts = yt_desc.split("\n\n", 2)
            title = parts[0] if parts else (content.trend_topic or "Short")
            description = parts[1] if len(parts) > 1 else yt_desc
            tags = []
            if len(parts) > 2 and parts[2].startswith("Tags: "):
                tags = [t.strip() for t in parts[2][6:].split(",")]
            if not title.endswith("#Shorts"):
                title = f"{title} #Shorts"
            published_id = await client.upload_short(
                video_path=content.video_file_path,
                title=title[:100],
                description=description,
                tags=tags,
            )

        elif platform == "tiktok":
            if not content.video_file_path:
                raise PublishError(platform, "No video_file_path set on content")
            client = TikTokClient(access_token=access_token)
            caption = content.description_tiktok or ""
            published_id = await client.publish_video(
                video_path=content.video_file_path,
                caption=caption,
            )

        else:
            raise ValueError(f"Unsupported platform: {platform!r}")

    except (InstagramPublishError, YouTubeUploadError, TikTokPublishError) as exc:
        logger.error("Publish to %s failed: %s", platform, exc)
        raise PublishError(platform, str(exc)) from exc

    logger.info(
        "Successfully published to %s: published_id=%s", platform, published_id
    )
    return published_id


# ------------------------------------------------------------------
# Multi-platform publishing
# ------------------------------------------------------------------

async def publish_to_all(
    bot: Bot,
    content: ContentItem,
    db: Session,
) -> Dict[str, str]:
    """Publish *content* to every active platform configured on *bot*.

    Iterates over ``bot.credentials``, selects only those that are
    active, and calls :func:`publish_to_platform` for each.
    Results are written back to the content model and committed.

    Returns
    -------
    dict
        Mapping of ``{platform: published_id}`` for every platform
        that succeeded.
    """
    results: Dict[str, str] = {}
    credentials = bot.credentials or []

    if not credentials:
        logger.warning(
            "Bot %s has no credentials -- nothing to publish", bot.id
        )
        return results

    for credential in credentials:
        platform: str = credential.platform.lower().strip()

        if not credential.is_active:
            logger.info("Skipping inactive credential for %s", platform)
            continue

        try:
            published_id = await publish_to_platform(
                content=content,
                credential=credential,
                platform=platform,
            )
        except (PublishError, ValueError) as exc:
            logger.error(
                "Failed to publish to %s for bot %s: %s",
                platform, bot.id, exc,
            )
            continue

        # Persist the published ID
        mapping = _PLATFORM_MAP.get(platform)
        if mapping:
            setattr(content, mapping[1], published_id)

        results[platform] = published_id

    # Flush changes
    if results:
        try:
            db.commit()
        except Exception:
            logger.exception("Failed to commit publish results")
            db.rollback()

    return results

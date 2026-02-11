"""Service layer for sending content through the Telegram approval workflow."""
from __future__ import annotations

from typing import Optional

from app.config import settings
from app.integrations.telegram_client import TelegramApprovalClient
from app.models.bot import Bot
from app.models.content import ContentItem
from app.utils.logging_config import get_logger

logger = get_logger("telegram_approver")

# Telegram video caption limit is 1024 characters; keep previews short so the
# structured caption (bot name + topic + descriptions) fits comfortably.
_DESCRIPTION_PREVIEW_LENGTH = 200


def _preview(text: Optional[str], max_length: int = _DESCRIPTION_PREVIEW_LENGTH) -> str:
    """Return a short preview of *text*, or a placeholder if empty."""
    if not text:
        return "(sin descripcion)"
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def _build_caption(bot: Bot, content: ContentItem) -> str:
    """Build a human-readable caption for the approval message.

    Layout::

        [Bot name] - Contenido #<id>
        Tema: <topic>

        -- Instagram --
        <preview>

        -- YouTube --
        <preview>

        -- TikTok --
        <preview>
    """
    topic = content.trend_topic or content.custom_prompt or "(sin tema)"

    lines = [
        f"[{bot.name}] - Contenido #{content.id}",
        f"Tema: {topic}",
        "",
        "-- Instagram --",
        _preview(content.description_instagram),
        "",
        "-- YouTube --",
        _preview(content.description_youtube),
        "",
        "-- TikTok --",
        _preview(content.description_tiktok),
    ]
    return "\n".join(lines)


def _get_client() -> TelegramApprovalClient:
    return TelegramApprovalClient(settings.telegram_bot_token)


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------


async def send_content_for_approval(bot: Bot, content: ContentItem) -> int:
    """Send a content item's video to Telegram for human approval.

    Parameters
    ----------
    bot:
        The :class:`Bot` that owns the content (provides ``telegram_chat_id``).
    content:
        The :class:`ContentItem` whose video will be sent.

    Returns
    -------
    int
        The Telegram ``message_id`` of the sent approval message.

    Raises
    ------
    ValueError
        If the bot has no ``telegram_chat_id`` configured or the content has
        no ``video_file_path``.
    """
    if not bot.telegram_chat_id:
        raise ValueError(f"Bot '{bot.name}' (id={bot.id}) has no telegram_chat_id configured")
    if not content.video_file_path:
        raise ValueError(f"ContentItem {content.id} has no video_file_path")

    caption = _build_caption(bot, content)
    client = _get_client()

    message_id = await client.send_for_approval(
        chat_id=bot.telegram_chat_id,
        video_path=content.video_file_path,
        caption=caption,
        content_id=content.id,
    )
    logger.info(
        "Sent content %d for approval (bot=%s, message_id=%d)",
        content.id,
        bot.name,
        message_id,
    )
    return message_id


async def notify_published(bot: Bot, content: ContentItem) -> None:
    """Notify the operator that *content* has been published to all platforms.

    Includes direct links when platform IDs are available.
    """
    if not bot.telegram_chat_id:
        logger.warning("Cannot notify: bot '%s' has no telegram_chat_id", bot.name)
        return

    lines = [
        f"Contenido #{content.id} publicado exitosamente.",
        "",
    ]

    if content.publish_instagram_id:
        lines.append(
            f"Instagram: https://www.instagram.com/reel/{content.publish_instagram_id}/"
        )
    if content.publish_youtube_id:
        lines.append(
            f"YouTube: https://youtube.com/shorts/{content.publish_youtube_id}"
        )
    if content.publish_tiktok_id:
        lines.append(
            f"TikTok: https://www.tiktok.com/@user/video/{content.publish_tiktok_id}"
        )

    if len(lines) == 2:
        # No platform IDs available yet
        lines.append("(enlaces no disponibles todavia)")

    text = "\n".join(lines)
    client = _get_client()

    try:
        await client.send_notification(chat_id=bot.telegram_chat_id, text=text)
        logger.info("Sent publish notification for content %d", content.id)
    except Exception:
        logger.exception(
            "Failed to send publish notification for content %d", content.id
        )


async def notify_error(bot: Bot, content: ContentItem, error_message: str) -> None:
    """Notify the operator about an error during content processing."""
    if not bot.telegram_chat_id:
        logger.warning("Cannot notify error: bot '%s' has no telegram_chat_id", bot.name)
        return

    topic = content.trend_topic or content.custom_prompt or "(sin tema)"
    text = (
        f"Error en contenido #{content.id}\n"
        f"Bot: {bot.name}\n"
        f"Tema: {topic}\n"
        f"Estado: {content.status}\n\n"
        f"Error: {error_message}"
    )

    client = _get_client()
    try:
        await client.send_notification(chat_id=bot.telegram_chat_id, text=text)
        logger.info("Sent error notification for content %d", content.id)
    except Exception:
        logger.exception(
            "Failed to send error notification for content %d", content.id
        )

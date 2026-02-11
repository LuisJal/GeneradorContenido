"""Telegram bot client for the content approval workflow."""
from __future__ import annotations

from typing import Optional

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

from app.utils.logging_config import get_logger

logger = get_logger("telegram_client")

# Telegram caption limit for videos
_CAPTION_MAX_LENGTH = 1024


def _truncate(text: str, max_length: int) -> str:
    """Truncate *text* to *max_length*, adding ellipsis if needed."""
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


class TelegramApprovalClient:
    """Sends videos for approval and manages follow-up messages via Telegram."""

    def __init__(self, bot_token: str) -> None:
        self._bot = Bot(token=bot_token)

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    async def send_for_approval(
        self,
        chat_id: str,
        video_path: str,
        caption: str,
        content_id: int,
    ) -> int:
        """Send a video to *chat_id* with approve / reject / edit buttons.

        Parameters
        ----------
        chat_id:
            Telegram chat to send the message to.
        video_path:
            Local filesystem path to the video file.
        caption:
            Preformatted caption text (bot name, topic, descriptions).
            Will be truncated to respect the Telegram 1024-char limit.
        content_id:
            Database id of the :class:`ContentItem` (used in callback_data).

        Returns
        -------
        int
            The ``message_id`` of the sent message (used for later edits).
        """
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "Aprobar",
                        callback_data=f"approve:{content_id}",
                    ),
                    InlineKeyboardButton(
                        "Rechazar",
                        callback_data=f"reject:{content_id}",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "Editar y Aprobar",
                        callback_data=f"edit:{content_id}",
                    ),
                ],
            ]
        )

        truncated_caption = _truncate(caption, _CAPTION_MAX_LENGTH)

        try:
            with open(video_path, "rb") as video_file:
                message = await self._bot.send_video(
                    chat_id=chat_id,
                    video=video_file,
                    caption=truncated_caption,
                    reply_markup=keyboard,
                )
            logger.info(
                "Sent approval request for content %d to chat %s (message_id=%d)",
                content_id,
                chat_id,
                message.message_id,
            )
            return message.message_id
        except Exception:
            logger.exception(
                "Failed to send approval video for content %d to chat %s",
                content_id,
                chat_id,
            )
            raise

    async def send_notification(self, chat_id: str, text: str) -> None:
        """Send a plain text notification (status updates, errors, etc.)."""
        try:
            await self._bot.send_message(chat_id=chat_id, text=text)
            logger.info("Sent notification to chat %s", chat_id)
        except Exception:
            logger.exception("Failed to send notification to chat %s", chat_id)
            raise

    async def update_message(
        self,
        chat_id: str,
        message_id: int,
        text: str,
    ) -> None:
        """Edit the text of an existing message (e.g. to remove inline buttons)."""
        try:
            await self._bot.edit_message_caption(
                chat_id=chat_id,
                message_id=message_id,
                caption=text,
                reply_markup=None,
            )
            logger.info(
                "Updated message %d in chat %s",
                message_id,
                chat_id,
            )
        except Exception:
            logger.exception(
                "Failed to update message %d in chat %s",
                message_id,
                chat_id,
            )
            raise

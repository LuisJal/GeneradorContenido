"""Tests for Telegram integration: approver service, caption building, webhook."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.telegram_approver import (
    _build_caption,
    _preview,
    send_content_for_approval,
    notify_published,
    notify_error,
)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_bot(**overrides) -> MagicMock:
    bot = MagicMock()
    bot.name = overrides.get("name", "FitBot")
    bot.id = overrides.get("id", 1)
    bot.telegram_chat_id = overrides.get("telegram_chat_id", "12345")
    return bot


def _make_content(**overrides) -> MagicMock:
    content = MagicMock()
    content.id = overrides.get("id", 42)
    content.trend_topic = overrides.get("trend_topic", "fitness tips")
    content.custom_prompt = overrides.get("custom_prompt", None)
    content.description_instagram = overrides.get("description_instagram", "IG caption")
    content.description_youtube = overrides.get("description_youtube", "YT desc")
    content.description_tiktok = overrides.get("description_tiktok", "TT caption")
    content.video_file_path = overrides.get("video_file_path", "/tmp/video.mp4")
    content.status = overrides.get("status", "pending_approval")
    content.publish_instagram_id = overrides.get("publish_instagram_id", None)
    content.publish_youtube_id = overrides.get("publish_youtube_id", None)
    content.publish_tiktok_id = overrides.get("publish_tiktok_id", None)
    return content


# ------------------------------------------------------------------
# _preview
# ------------------------------------------------------------------


def test_preview_short_text():
    assert _preview("Hello") == "Hello"


def test_preview_none():
    assert _preview(None) == "(sin descripcion)"


def test_preview_empty():
    assert _preview("") == "(sin descripcion)"


def test_preview_long_text():
    long = "A" * 300
    result = _preview(long)
    assert len(result) == 200
    assert result.endswith("...")


# ------------------------------------------------------------------
# _build_caption
# ------------------------------------------------------------------


def test_build_caption_format():
    bot = _make_bot()
    content = _make_content()
    caption = _build_caption(bot, content)

    assert "[FitBot]" in caption
    assert "Contenido #42" in caption
    assert "fitness tips" in caption
    assert "-- Instagram --" in caption
    assert "-- YouTube --" in caption
    assert "-- TikTok --" in caption


def test_build_caption_no_topic():
    bot = _make_bot()
    content = _make_content(trend_topic=None, custom_prompt=None)
    caption = _build_caption(bot, content)
    assert "(sin tema)" in caption


# ------------------------------------------------------------------
# send_content_for_approval
# ------------------------------------------------------------------


def test_send_for_approval_no_chat_id():
    """Should raise ValueError if bot has no telegram_chat_id."""
    bot = _make_bot(telegram_chat_id=None)
    content = _make_content()

    with pytest.raises(ValueError, match="telegram_chat_id"):
        asyncio.get_event_loop().run_until_complete(
            send_content_for_approval(bot, content)
        )


def test_send_for_approval_no_video():
    """Should raise ValueError if content has no video_file_path."""
    bot = _make_bot()
    content = _make_content(video_file_path=None)

    with pytest.raises(ValueError, match="video_file_path"):
        asyncio.get_event_loop().run_until_complete(
            send_content_for_approval(bot, content)
        )


def test_send_for_approval_success():
    """Should call the client and return message_id."""
    bot = _make_bot()
    content = _make_content()

    mock_client = AsyncMock()
    mock_client.send_for_approval = AsyncMock(return_value=999)

    with patch("app.services.telegram_approver._get_client", return_value=mock_client):
        result = asyncio.get_event_loop().run_until_complete(
            send_content_for_approval(bot, content)
        )

    assert result == 999
    mock_client.send_for_approval.assert_called_once()


# ------------------------------------------------------------------
# notify_published
# ------------------------------------------------------------------


def test_notify_published_with_links():
    """Should send notification with platform links."""
    bot = _make_bot()
    content = _make_content(
        publish_instagram_id="ig123",
        publish_youtube_id="yt456",
        publish_tiktok_id="tt789",
    )

    mock_client = AsyncMock()
    mock_client.send_notification = AsyncMock()

    with patch("app.services.telegram_approver._get_client", return_value=mock_client):
        asyncio.get_event_loop().run_until_complete(notify_published(bot, content))

    call_text = mock_client.send_notification.call_args[1]["text"]
    assert "ig123" in call_text
    assert "yt456" in call_text
    assert "tt789" in call_text


def test_notify_published_no_chat_id():
    """Should silently return if bot has no chat_id."""
    bot = _make_bot(telegram_chat_id=None)
    content = _make_content()

    # Should not raise
    asyncio.get_event_loop().run_until_complete(notify_published(bot, content))


# ------------------------------------------------------------------
# notify_error
# ------------------------------------------------------------------


def test_notify_error_sends_message():
    """Should send error notification with details."""
    bot = _make_bot()
    content = _make_content()

    mock_client = AsyncMock()
    mock_client.send_notification = AsyncMock()

    with patch("app.services.telegram_approver._get_client", return_value=mock_client):
        asyncio.get_event_loop().run_until_complete(
            notify_error(bot, content, "Connection timeout")
        )

    call_text = mock_client.send_notification.call_args[1]["text"]
    assert "Connection timeout" in call_text
    assert "FitBot" in call_text

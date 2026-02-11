"""Tests for video_generator service -- strategy pattern and provider selection."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.video_generator import (
    _get_client,
    check_video_status,
    download_video,
    submit_video_generation,
)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_bot(provider: str = "veo3") -> MagicMock:
    """Create a fake Bot with video-related fields."""
    bot = MagicMock()
    bot.video_provider = provider
    bot.video_duration_seconds = 15
    bot.video_aspect_ratio = "9:16"
    bot.slug = "testbot"
    return bot


# ------------------------------------------------------------------
# Strategy pattern: provider selection
# ------------------------------------------------------------------


def test_get_client_veo3():
    """provider='veo3' should create a Veo3Client."""
    bot = _make_bot("veo3")

    with patch("app.services.video_generator.settings") as mock_settings:
        mock_settings.google_cloud_project = "my-project"
        with patch("app.services.video_generator.Veo3Client") as veo_cls:
            result = _get_client(bot)
            veo_cls.assert_called_once_with(project_id="my-project")


def test_get_client_kling3():
    """provider='kling3' should create a KlingClient."""
    bot = _make_bot("kling3")

    with patch("app.services.video_generator.settings") as mock_settings:
        mock_settings.kling_api_key = "kling-key-123"
        with patch("app.services.video_generator.KlingClient") as kling_cls:
            result = _get_client(bot)
            kling_cls.assert_called_once_with(api_key="kling-key-123")


def test_get_client_unsupported():
    """Unknown provider should raise ValueError."""
    bot = _make_bot("dalle")
    with pytest.raises(ValueError, match="Unsupported video provider"):
        _get_client(bot)


def test_get_client_veo3_no_project():
    """Missing project should raise ValueError."""
    bot = _make_bot("veo3")

    with patch("app.services.video_generator.settings") as mock_settings:
        mock_settings.google_cloud_project = ""
        with pytest.raises(ValueError, match="GOOGLE_CLOUD_PROJECT"):
            _get_client(bot)


def test_get_client_kling3_no_key():
    """Missing API key should raise ValueError."""
    bot = _make_bot("kling3")

    with patch("app.services.video_generator.settings") as mock_settings:
        mock_settings.kling_api_key = ""
        with pytest.raises(ValueError, match="KLING_API_KEY"):
            _get_client(bot)


# ------------------------------------------------------------------
# submit_video_generation
# ------------------------------------------------------------------


def test_submit_video_generation():
    """Should call generate_video on the chosen client and return task_id."""
    bot = _make_bot("kling3")

    mock_client = AsyncMock()
    mock_client.generate_video = AsyncMock(return_value="task-abc")
    mock_client.close = AsyncMock()

    with patch("app.services.video_generator._get_client", return_value=mock_client):
        result = asyncio.get_event_loop().run_until_complete(
            submit_video_generation(bot, "A person running", content_id=1)
        )

    assert result == "task-abc"
    mock_client.generate_video.assert_called_once_with(
        prompt="A person running",
        duration=15,
        aspect_ratio="9:16",
    )
    mock_client.close.assert_called_once()


# ------------------------------------------------------------------
# check_video_status
# ------------------------------------------------------------------


def test_check_video_status():
    """Should call poll_status on the client and return the result dict."""
    bot = _make_bot("kling3")

    mock_client = AsyncMock()
    mock_client.poll_status = AsyncMock(
        return_value={"status": "completed", "video_url": "https://cdn/video.mp4"}
    )
    mock_client.close = AsyncMock()

    with patch("app.services.video_generator._get_client", return_value=mock_client):
        result = asyncio.get_event_loop().run_until_complete(
            check_video_status(bot, "task-abc")
        )

    assert result["status"] == "completed"
    assert "video_url" in result


# ------------------------------------------------------------------
# download_video
# ------------------------------------------------------------------


def test_download_video():
    """Should call download_video on the client and return local path."""
    bot = _make_bot("kling3")

    mock_client = AsyncMock()
    mock_client.download_video = AsyncMock(return_value="/tmp/video.mp4")
    mock_client.close = AsyncMock()

    with patch("app.services.video_generator._get_client", return_value=mock_client):
        with patch("app.services.video_generator.get_video_path", return_value="/tmp/video.mp4"):
            result = asyncio.get_event_loop().run_until_complete(
                download_video(bot, "https://cdn/video.mp4", content_id=1)
            )

    assert result == "/tmp/video.mp4"

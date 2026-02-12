"""Tests for AimlKlingClient -- Kling V3 video generation via AIML API."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from app.integrations.aiml_kling_client import AimlKlingClient


# ------------------------------------------------------------------
# Construction
# ------------------------------------------------------------------


def test_init_sets_model():
    """Client should use V3 standard by default."""
    with patch("app.integrations.aiml_kling_client.BaseAPIClient.__init__"):
        client = AimlKlingClient.__new__(AimlKlingClient)
        client._model = "klingai/video-v3-standard-text-to-video"
        assert "v3-standard" in client._model


# ------------------------------------------------------------------
# generate_video
# ------------------------------------------------------------------


def test_generate_video_clamps_duration_high():
    """Duration > 15 should be clamped to 15."""
    client = AimlKlingClient.__new__(AimlKlingClient)
    client._model = "klingai/video-v3-standard-text-to-video"
    client.post = AsyncMock(return_value={"id": "gen-123"})

    result = asyncio.get_event_loop().run_until_complete(
        client.generate_video("test prompt", duration=30, aspect_ratio="9:16")
    )

    assert result == "gen-123"
    call_kwargs = client.post.call_args
    payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
    assert payload["duration"] == 15


def test_generate_video_clamps_duration_low():
    """Duration < 3 should be clamped to 3."""
    client = AimlKlingClient.__new__(AimlKlingClient)
    client._model = "klingai/video-v3-standard-text-to-video"
    client.post = AsyncMock(return_value={"id": "gen-456"})

    result = asyncio.get_event_loop().run_until_complete(
        client.generate_video("test prompt", duration=1, aspect_ratio="16:9")
    )

    assert result == "gen-456"
    call_kwargs = client.post.call_args
    payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
    assert payload["duration"] == 3


def test_generate_video_passes_correct_payload():
    """Should send correct model, prompt, duration, aspect_ratio, and audio."""
    client = AimlKlingClient.__new__(AimlKlingClient)
    client._model = "klingai/video-v3-standard-text-to-video"
    client.post = AsyncMock(return_value={"id": "gen-789"})

    asyncio.get_event_loop().run_until_complete(
        client.generate_video(
            "An epic battle scene",
            duration=10,
            aspect_ratio="9:16",
            generate_audio=True,
        )
    )

    call_kwargs = client.post.call_args
    payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
    assert payload["model"] == "klingai/video-v3-standard-text-to-video"
    assert payload["prompt"] == "An epic battle scene"
    assert payload["duration"] == 10
    assert payload["aspect_ratio"] == "9:16"
    assert payload["generate_audio"] is True


def test_generate_video_includes_negative_prompt():
    """Negative prompt should be included when provided."""
    client = AimlKlingClient.__new__(AimlKlingClient)
    client._model = "klingai/video-v3-standard-text-to-video"
    client.post = AsyncMock(return_value={"id": "gen-neg"})

    asyncio.get_event_loop().run_until_complete(
        client.generate_video(
            "A cat",
            duration=5,
            negative_prompt="blurry, low quality",
        )
    )

    call_kwargs = client.post.call_args
    payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
    assert payload["negative_prompt"] == "blurry, low quality"


# ------------------------------------------------------------------
# poll_status
# ------------------------------------------------------------------


def test_poll_status_completed():
    """Should return completed with video_url when status is completed."""
    client = AimlKlingClient.__new__(AimlKlingClient)
    client.get = AsyncMock(return_value={
        "id": "gen-123",
        "status": "completed",
        "video": {"url": "https://cdn.aimlapi.com/video.mp4"},
    })

    result = asyncio.get_event_loop().run_until_complete(
        client.poll_status("gen-123")
    )

    assert result["status"] == "completed"
    assert result["video_url"] == "https://cdn.aimlapi.com/video.mp4"


def test_poll_status_error():
    """Should return failed with error message on error status."""
    client = AimlKlingClient.__new__(AimlKlingClient)
    client.get = AsyncMock(return_value={
        "id": "gen-123",
        "status": "error",
        "error": {"name": "ContentPolicyViolation", "message": "Blocked"},
    })

    result = asyncio.get_event_loop().run_until_complete(
        client.poll_status("gen-123")
    )

    assert result["status"] == "failed"
    assert "Blocked" in result["error"]


def test_poll_status_timeout():
    """Should return failed on timeout."""
    client = AimlKlingClient.__new__(AimlKlingClient)
    client.get = AsyncMock(return_value={
        "id": "gen-123",
        "status": "generating",
    })

    result = asyncio.get_event_loop().run_until_complete(
        client.poll_status("gen-123", timeout=1, interval=0.5)
    )

    assert result["status"] == "failed"
    assert "timed out" in result["error"].lower()


# ------------------------------------------------------------------
# Integration with video_generator strategy
# ------------------------------------------------------------------


def test_get_client_aiml_kling():
    """provider='aiml_kling' should create an AimlKlingClient."""
    from app.services.video_generator import _get_client

    bot = MagicMock()
    bot.video_provider = "aiml_kling"

    with patch("app.services.video_generator.settings") as mock_settings:
        mock_settings.aiml_api_key = "test-aiml-key"
        with patch("app.services.video_generator.AimlKlingClient") as aiml_cls:
            _get_client(bot)
            aiml_cls.assert_called_once_with(api_key="test-aiml-key")


def test_get_client_aiml_kling_no_key():
    """Missing AIML API key should raise ValueError."""
    from app.services.video_generator import _get_client

    bot = MagicMock()
    bot.video_provider = "aiml_kling"

    with patch("app.services.video_generator.settings") as mock_settings:
        mock_settings.aiml_api_key = ""
        with pytest.raises(ValueError, match="AIML_API_KEY"):
            _get_client(bot)

"""Tests for the publisher service."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.publisher import (
    PublishError,
    publish_to_all,
    publish_to_platform,
)


# ------------------------------------------------------------------
# Helpers -- lightweight stand-ins for DB models
# ------------------------------------------------------------------


class FakeCredential:
    def __init__(
        self,
        platform: str = "instagram",
        access_token_encrypted: str = "test-token",
        platform_user_id: str = "user-1",
        is_active: bool = True,
    ):
        self.platform = platform
        self.access_token_encrypted = access_token_encrypted
        self.refresh_token_encrypted = None
        self.token_expires_at = None
        self.platform_user_id = platform_user_id
        self.is_active = is_active
        self.id = 1


class FakeContent:
    def __init__(self):
        self.id = 1
        self.video_url = "https://example.com/video.mp4"
        self.video_file_path = "/tmp/video.mp4"
        self.description_instagram = "IG caption"
        self.description_youtube = "YT Title\n\nDescription\n\nTags: a, b, c"
        self.description_tiktok = "TT caption"
        self.trend_topic = "AI tips"
        self.publish_instagram_id = None
        self.publish_youtube_id = None
        self.publish_tiktok_id = None


class FakeBot:
    def __init__(self, credentials=None):
        self.id = 1
        self.credentials = credentials or []


class FakeDb:
    def __init__(self):
        self.committed = False
        self.rolled_back = False

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


_DECRYPT_PATCH = "app.services.publisher._decrypt_token"


# ------------------------------------------------------------------
# publish_to_platform
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_instagram():
    cred = FakeCredential(platform="instagram")
    content = FakeContent()

    with patch(_DECRYPT_PATCH, return_value="decrypted-token"), \
         patch("app.services.publisher.InstagramClient") as MockIG:
        mock_instance = AsyncMock()
        mock_instance.publish_reel = AsyncMock(return_value="ig-media-42")
        MockIG.return_value = mock_instance

        result = await publish_to_platform(content, cred, "instagram")

    assert result == "ig-media-42"
    mock_instance.publish_reel.assert_awaited_once()


@pytest.mark.asyncio
async def test_publish_youtube():
    cred = FakeCredential(platform="youtube")
    content = FakeContent()

    with patch(_DECRYPT_PATCH, return_value="decrypted-token"), \
         patch("app.services.publisher.YouTubeClient") as MockYT:
        mock_instance = AsyncMock()
        mock_instance.upload_short = AsyncMock(return_value="yt-video-1")
        MockYT.return_value = mock_instance

        result = await publish_to_platform(content, cred, "youtube")

    assert result == "yt-video-1"
    call_kwargs = mock_instance.upload_short.call_args.kwargs
    assert "#Shorts" in call_kwargs["title"]
    assert call_kwargs["tags"] == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_publish_tiktok():
    cred = FakeCredential(platform="tiktok")
    content = FakeContent()

    with patch(_DECRYPT_PATCH, return_value="decrypted-token"), \
         patch("app.services.publisher.TikTokClient") as MockTT:
        mock_instance = AsyncMock()
        mock_instance.publish_video = AsyncMock(return_value="tt-pub-1")
        MockTT.return_value = mock_instance

        result = await publish_to_platform(content, cred, "tiktok")

    assert result == "tt-pub-1"


@pytest.mark.asyncio
async def test_publish_no_token():
    cred = FakeCredential(access_token_encrypted="")
    content = FakeContent()

    with patch(_DECRYPT_PATCH, return_value=""):
        with pytest.raises(PublishError, match="No access token"):
            await publish_to_platform(content, cred, "instagram")


@pytest.mark.asyncio
async def test_publish_unsupported_platform():
    cred = FakeCredential(platform="snapchat", access_token_encrypted="t")
    content = FakeContent()

    with patch(_DECRYPT_PATCH, return_value="token"):
        with pytest.raises(ValueError, match="Unsupported"):
            await publish_to_platform(content, cred, "snapchat")


@pytest.mark.asyncio
async def test_publish_instagram_no_video_url():
    cred = FakeCredential(platform="instagram")
    content = FakeContent()
    content.video_url = None

    with patch(_DECRYPT_PATCH, return_value="token"):
        with pytest.raises(PublishError, match="video_url"):
            await publish_to_platform(content, cred, "instagram")


@pytest.mark.asyncio
async def test_publish_youtube_no_file():
    cred = FakeCredential(platform="youtube")
    content = FakeContent()
    content.video_file_path = None

    with patch(_DECRYPT_PATCH, return_value="token"):
        with pytest.raises(PublishError, match="video_file_path"):
            await publish_to_platform(content, cred, "youtube")


@pytest.mark.asyncio
async def test_publish_client_error_wraps():
    """Platform client errors should be wrapped in PublishError."""
    from app.integrations.instagram_client import InstagramPublishError

    cred = FakeCredential(platform="instagram")
    content = FakeContent()

    with patch(_DECRYPT_PATCH, return_value="token"), \
         patch("app.services.publisher.InstagramClient") as MockIG:
        mock_instance = AsyncMock()
        mock_instance.publish_reel = AsyncMock(
            side_effect=InstagramPublishError("timeout")
        )
        MockIG.return_value = mock_instance

        with pytest.raises(PublishError, match="timeout"):
            await publish_to_platform(content, cred, "instagram")


# ------------------------------------------------------------------
# publish_to_all
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_to_all_success():
    cred_ig = FakeCredential(platform="instagram")
    cred_tt = FakeCredential(platform="tiktok")
    bot = FakeBot(credentials=[cred_ig, cred_tt])
    content = FakeContent()
    db = FakeDb()

    with patch("app.services.publisher.publish_to_platform") as mock_pub:
        mock_pub.side_effect = [
            "ig-42",  # instagram
            "tt-7",   # tiktok
        ]
        results = await publish_to_all(bot, content, db)

    assert results == {"instagram": "ig-42", "tiktok": "tt-7"}
    assert content.publish_instagram_id == "ig-42"
    assert content.publish_tiktok_id == "tt-7"
    assert db.committed


@pytest.mark.asyncio
async def test_publish_to_all_partial_failure():
    cred_ig = FakeCredential(platform="instagram")
    cred_yt = FakeCredential(platform="youtube")
    bot = FakeBot(credentials=[cred_ig, cred_yt])
    content = FakeContent()
    db = FakeDb()

    with patch("app.services.publisher.publish_to_platform") as mock_pub:
        mock_pub.side_effect = [
            "ig-42",
            PublishError("youtube", "upload failed"),
        ]
        results = await publish_to_all(bot, content, db)

    assert results == {"instagram": "ig-42"}
    assert content.publish_instagram_id == "ig-42"
    assert db.committed


@pytest.mark.asyncio
async def test_publish_to_all_skips_inactive():
    cred = FakeCredential(platform="instagram", is_active=False)
    bot = FakeBot(credentials=[cred])
    content = FakeContent()
    db = FakeDb()

    with patch("app.services.publisher.publish_to_platform") as mock_pub:
        results = await publish_to_all(bot, content, db)

    assert results == {}
    mock_pub.assert_not_called()


@pytest.mark.asyncio
async def test_publish_to_all_no_credentials():
    bot = FakeBot(credentials=[])
    content = FakeContent()
    db = FakeDb()

    results = await publish_to_all(bot, content, db)
    assert results == {}

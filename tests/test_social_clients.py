"""Tests for Instagram, YouTube, and TikTok integration clients."""
from __future__ import annotations

import asyncio
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.integrations.instagram_client import (
    InstagramClient,
    InstagramPublishError,
)
from app.integrations.youtube_client import YouTubeClient, YouTubeUploadError
from app.integrations.tiktok_client import TikTokClient, TikTokPublishError


# ------------------------------------------------------------------
# Instagram
# ------------------------------------------------------------------


class TestInstagramClient:
    """Tests for InstagramClient."""

    def test_init(self):
        client = InstagramClient(access_token="test-token")
        assert client._access_token == "test-token"
        assert "v21.0" in client._base_url

    def test_init_custom_version(self):
        client = InstagramClient(access_token="t", api_version="v20.0")
        assert "v20.0" in client._base_url

    @pytest.mark.asyncio
    async def test_publish_reel_success(self):
        """Full publish flow: create container -> poll -> publish."""
        client = InstagramClient(access_token="token-123")

        mock_http = AsyncMock(spec=httpx.AsyncClient)

        # Step 1: create container
        create_resp = MagicMock()
        create_resp.json.return_value = {"id": "container-1"}
        create_resp.raise_for_status = MagicMock()

        # Step 2: poll (FINISHED)
        poll_resp = MagicMock()
        poll_resp.json.return_value = {"status_code": "FINISHED"}
        poll_resp.raise_for_status = MagicMock()

        # Step 3: publish
        pub_resp = MagicMock()
        pub_resp.json.return_value = {"id": "media-42"}
        pub_resp.raise_for_status = MagicMock()

        mock_http.post = AsyncMock(side_effect=[create_resp, pub_resp])
        mock_http.get = AsyncMock(return_value=poll_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch.object(client, "_build_client", return_value=mock_http):
            media_id = await client.publish_reel(
                ig_user_id="123456",
                video_url="https://example.com/video.mp4",
                caption="Test caption",
            )

        assert media_id == "media-42"
        assert mock_http.post.call_count == 2

    @pytest.mark.asyncio
    async def test_publish_reel_container_error(self):
        """Container enters ERROR state."""
        client = InstagramClient(access_token="token")

        mock_http = AsyncMock(spec=httpx.AsyncClient)

        create_resp = MagicMock()
        create_resp.json.return_value = {"id": "container-err"}
        create_resp.raise_for_status = MagicMock()

        poll_resp = MagicMock()
        poll_resp.json.return_value = {"status_code": "ERROR"}
        poll_resp.raise_for_status = MagicMock()

        mock_http.post = AsyncMock(return_value=create_resp)
        mock_http.get = AsyncMock(return_value=poll_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch.object(client, "_build_client", return_value=mock_http):
            with pytest.raises(InstagramPublishError, match="ERROR state"):
                await client.publish_reel("u1", "http://x.com/v.mp4", "cap")

    @pytest.mark.asyncio
    async def test_refresh_token(self):
        client = InstagramClient(access_token="old-token")

        mock_http = AsyncMock(spec=httpx.AsyncClient)
        resp = MagicMock()
        resp.json.return_value = {"access_token": "new-token", "expires_in": 5184000}
        resp.raise_for_status = MagicMock()
        mock_http.get = AsyncMock(return_value=resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch.object(client, "_build_client", return_value=mock_http):
            data = await client.refresh_token("short-lived")

        assert data["access_token"] == "new-token"


# ------------------------------------------------------------------
# YouTube
# ------------------------------------------------------------------


class TestYouTubeClient:
    """Tests for YouTubeClient."""

    def test_init(self):
        client = YouTubeClient(access_token="yt-token")
        assert client._access_token == "yt-token"

    def test_build_snippet(self):
        snippet = YouTubeClient._build_snippet(
            title="Test", description="Desc", tags=["a"], category_id="22",
        )
        assert snippet["snippet"]["title"] == "Test"
        assert snippet["status"]["privacyStatus"] == "public"

    @pytest.mark.asyncio
    async def test_upload_short_success(self):
        """Upload with a single chunk that fits."""
        client = YouTubeClient(access_token="yt-token")

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(b"fake video content")
            video_path = f.name

        try:
            mock_http = AsyncMock(spec=httpx.AsyncClient)

            # Init response with Location header
            init_resp = MagicMock()
            init_resp.status_code = 200
            init_resp.json.return_value = {}
            init_resp.headers = {"Location": "https://upload.example.com/upload123"}

            # Chunk upload final response
            chunk_resp = MagicMock()
            chunk_resp.status_code = 200
            chunk_resp.json.return_value = {"id": "yt-video-1"}

            mock_http.post = AsyncMock(return_value=init_resp)
            mock_http.put = AsyncMock(return_value=chunk_resp)
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)

            with patch.object(client, "_build_client", return_value=mock_http):
                video_id = await client.upload_short(
                    video_path=video_path,
                    title="Test Short #Shorts",
                    description="Test description",
                )

            assert video_id == "yt-video-1"
        finally:
            os.unlink(video_path)

    @pytest.mark.asyncio
    async def test_upload_short_no_location(self):
        """Init response without Location header."""
        client = YouTubeClient(access_token="yt-token")

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(b"data")
            video_path = f.name

        try:
            mock_http = AsyncMock(spec=httpx.AsyncClient)
            init_resp = MagicMock()
            init_resp.status_code = 200
            init_resp.headers = {}
            mock_http.post = AsyncMock(return_value=init_resp)
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)

            with patch.object(client, "_build_client", return_value=mock_http):
                with pytest.raises(YouTubeUploadError, match="Location"):
                    await client.upload_short(video_path, "t", "d")
        finally:
            os.unlink(video_path)

    @pytest.mark.asyncio
    async def test_upload_short_init_error(self):
        """Init response with non-200/308 status."""
        client = YouTubeClient(access_token="yt-token")

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(b"data")
            video_path = f.name

        try:
            mock_http = AsyncMock(spec=httpx.AsyncClient)
            init_resp = MagicMock()
            init_resp.status_code = 403
            init_resp.text = "Forbidden"
            mock_http.post = AsyncMock(return_value=init_resp)
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)

            with patch.object(client, "_build_client", return_value=mock_http):
                with pytest.raises(YouTubeUploadError, match="403"):
                    await client.upload_short(video_path, "t", "d")
        finally:
            os.unlink(video_path)

    @pytest.mark.asyncio
    async def test_refresh_token(self):
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        resp = MagicMock()
        resp.json.return_value = {"access_token": "new-yt", "expires_in": 3600}
        resp.raise_for_status = MagicMock()
        mock_http.post = AsyncMock(return_value=resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_http):
            client = YouTubeClient(access_token="old")
            data = await client.refresh_token("cid", "csec", "rt")

        assert data["access_token"] == "new-yt"


# ------------------------------------------------------------------
# TikTok
# ------------------------------------------------------------------


class TestTikTokClient:
    """Tests for TikTokClient."""

    def test_init(self):
        client = TikTokClient(access_token="tt-token")
        assert client._access_token == "tt-token"

    @pytest.mark.asyncio
    async def test_publish_video_success(self):
        """Full TikTok publish: init -> upload -> poll."""
        client = TikTokClient(access_token="tt-token")

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(b"fake tiktok video")
            video_path = f.name

        try:
            mock_http = AsyncMock(spec=httpx.AsyncClient)

            # Init response
            init_resp = MagicMock()
            init_resp.json.return_value = {
                "data": {
                    "publish_id": "pub-1",
                    "upload_url": "https://upload.tiktok.com/abc",
                }
            }
            init_resp.raise_for_status = MagicMock()

            # Chunk upload
            chunk_resp = MagicMock()
            chunk_resp.status_code = 200

            # Poll status
            poll_resp = MagicMock()
            poll_resp.json.return_value = {
                "data": {"status": "PUBLISH_COMPLETE"}
            }
            poll_resp.raise_for_status = MagicMock()

            mock_http.post = AsyncMock(side_effect=[init_resp, poll_resp])
            mock_http.put = AsyncMock(return_value=chunk_resp)
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)

            with patch.object(client, "_build_client", return_value=mock_http):
                publish_id = await client.publish_video(
                    video_path=video_path,
                    caption="TikTok test",
                )

            assert publish_id == "pub-1"
        finally:
            os.unlink(video_path)

    @pytest.mark.asyncio
    async def test_publish_video_init_missing_data(self):
        """Init response missing required fields."""
        client = TikTokClient(access_token="tt")

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(b"data")
            video_path = f.name

        try:
            mock_http = AsyncMock(spec=httpx.AsyncClient)
            init_resp = MagicMock()
            init_resp.json.return_value = {"data": {}}
            init_resp.raise_for_status = MagicMock()
            mock_http.post = AsyncMock(return_value=init_resp)
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)

            with patch.object(client, "_build_client", return_value=mock_http):
                with pytest.raises(TikTokPublishError, match="publish_id"):
                    await client.publish_video(video_path, "cap")
        finally:
            os.unlink(video_path)

    @pytest.mark.asyncio
    async def test_publish_video_poll_failed(self):
        """Publish job fails during polling."""
        client = TikTokClient(access_token="tt")

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(b"data")
            video_path = f.name

        try:
            mock_http = AsyncMock(spec=httpx.AsyncClient)

            init_resp = MagicMock()
            init_resp.json.return_value = {
                "data": {"publish_id": "pub-2", "upload_url": "https://up.tt/abc"}
            }
            init_resp.raise_for_status = MagicMock()

            chunk_resp = MagicMock()
            chunk_resp.status_code = 200

            poll_resp = MagicMock()
            poll_resp.json.return_value = {
                "data": {"status": "FAILED", "fail_reason": "video too long"}
            }
            poll_resp.raise_for_status = MagicMock()

            mock_http.post = AsyncMock(side_effect=[init_resp, poll_resp])
            mock_http.put = AsyncMock(return_value=chunk_resp)
            mock_http.__aenter__ = AsyncMock(return_value=mock_http)
            mock_http.__aexit__ = AsyncMock(return_value=False)

            with patch.object(client, "_build_client", return_value=mock_http):
                with pytest.raises(TikTokPublishError, match="video too long"):
                    await client.publish_video(video_path, "cap")
        finally:
            os.unlink(video_path)

    @pytest.mark.asyncio
    async def test_refresh_token(self):
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        resp = MagicMock()
        resp.json.return_value = {
            "data": {"access_token": "new-tt", "expires_in": 86400}
        }
        resp.raise_for_status = MagicMock()
        mock_http.post = AsyncMock(return_value=resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_http):
            client = TikTokClient(access_token="old")
            data = await client.refresh_token("ck", "cs", "rt")

        assert data["data"]["access_token"] == "new-tt"

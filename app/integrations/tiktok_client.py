"""TikTok Content Posting API client.

Provides an async interface for uploading and publishing videos to
TikTok via the official Content Posting API (v2).
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, Optional

import httpx

from app.utils.logging_config import get_logger

logger = get_logger(__name__)

_BASE_URL = "https://open.tiktokapis.com"
_CHUNK_SIZE = 10 * 1024 * 1024  # 10 MiB per chunk
_PUBLISH_POLL_INTERVAL = 5  # seconds
_PUBLISH_POLL_TIMEOUT = 120  # seconds


class TikTokPublishError(Exception):
    """Raised when a TikTok publish operation fails."""


class TikTokClient:
    """Async client for the TikTok Content Posting API.

    Parameters
    ----------
    access_token:
        A valid TikTok OAuth2 access token with the
        ``video.upload`` and ``video.publish`` scopes.
    """

    def __init__(self, access_token: str) -> None:
        self._access_token = access_token

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _auth_headers(self) -> Dict[str, str]:
        """Return common authorization headers."""
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        }

    def _build_client(self, timeout: float = 60.0) -> httpx.AsyncClient:
        """Return a configured ``httpx.AsyncClient``."""
        return httpx.AsyncClient(
            base_url=_BASE_URL,
            headers=self._auth_headers(),
            timeout=timeout,
        )

    async def _upload_chunks(
        self,
        client: httpx.AsyncClient,
        upload_url: str,
        video_path: str,
        file_size: int,
    ) -> None:
        """Upload the video file in chunks to the provided *upload_url*.

        Raises
        ------
        TikTokPublishError
            If any chunk transfer fails.
        """
        offset = 0

        with open(video_path, "rb") as fh:
            while offset < file_size:
                chunk = fh.read(_CHUNK_SIZE)
                chunk_len = len(chunk)
                end = offset + chunk_len - 1

                content_range = f"bytes {offset}-{end}/{file_size}"
                logger.debug("Uploading TikTok chunk: %s", content_range)

                resp = await client.put(
                    upload_url,
                    content=chunk,
                    headers={
                        "Content-Type": "video/mp4",
                        "Content-Length": str(chunk_len),
                        "Content-Range": content_range,
                    },
                )

                if resp.status_code not in (200, 201, 206):
                    raise TikTokPublishError(
                        f"Chunk upload failed at offset {offset}: "
                        f"{resp.status_code} {resp.text}"
                    )

                offset += chunk_len

        logger.info("All chunks uploaded (%d bytes total)", file_size)

    async def _poll_publish_status(
        self,
        client: httpx.AsyncClient,
        publish_id: str,
    ) -> None:
        """Poll until the publish job reaches a terminal state.

        Raises
        ------
        TikTokPublishError
            If the publish job fails or times out.
        """
        elapsed = 0

        while elapsed < _PUBLISH_POLL_TIMEOUT:
            resp = await client.post(
                "/v2/post/publish/status/fetch/",
                json={"publish_id": publish_id},
            )
            resp.raise_for_status()
            data: Dict[str, Any] = resp.json()
            status = data.get("data", {}).get("status")

            logger.debug(
                "TikTok publish_id %s status: %s (elapsed %ds)",
                publish_id,
                status,
                elapsed,
            )

            if status == "PUBLISH_COMPLETE":
                return
            if status in ("FAILED", "PUBLISH_FAILED"):
                fail_reason = data.get("data", {}).get("fail_reason", "unknown")
                raise TikTokPublishError(
                    f"Publish failed for {publish_id}: {fail_reason}"
                )

            await asyncio.sleep(_PUBLISH_POLL_INTERVAL)
            elapsed += _PUBLISH_POLL_INTERVAL

        raise TikTokPublishError(
            f"Timed out waiting for publish_id {publish_id} after "
            f"{_PUBLISH_POLL_TIMEOUT}s"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def publish_video(
        self,
        video_path: str,
        caption: str,
    ) -> str:
        """Upload and publish a video to TikTok.

        The workflow follows the TikTok Content Posting API:

        1. **Init** -- request an upload URL and publish ID.
        2. **Upload** -- transfer the video file in chunks.
        3. **Poll** -- wait for the publish job to finish.

        Parameters
        ----------
        video_path:
            Local filesystem path to the video file.
        caption:
            The caption / description for the TikTok post.

        Returns
        -------
        str
            The ``publish_id`` assigned by TikTok.

        Raises
        ------
        TikTokPublishError
            On any failure during init, upload, or publishing.
        FileNotFoundError
            If *video_path* does not exist.
        """
        file_size = os.path.getsize(video_path)
        logger.info(
            "Publishing TikTok video: caption=%r, file=%s (%d bytes)",
            caption[:60],
            video_path,
            file_size,
        )

        async with self._build_client(timeout=300.0) as client:
            # Step 1 -- initialise the upload
            init_body: Dict[str, Any] = {
                "post_info": {
                    "title": caption,
                    "privacy_level": "SELF_ONLY",
                    "disable_duet": False,
                    "disable_comment": False,
                    "disable_stitch": False,
                },
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": file_size,
                    "chunk_size": _CHUNK_SIZE,
                    "total_chunk_count": -(-file_size // _CHUNK_SIZE),  # ceil division
                },
            }

            init_resp = await client.post(
                "/v2/post/publish/video/init/",
                json=init_body,
            )
            init_resp.raise_for_status()
            init_data: Dict[str, Any] = init_resp.json()

            publish_id: Optional[str] = init_data.get("data", {}).get("publish_id")
            upload_url: Optional[str] = init_data.get("data", {}).get("upload_url")

            if publish_id is None or upload_url is None:
                raise TikTokPublishError(
                    f"Init response missing publish_id or upload_url: {init_data}"
                )
            logger.info(
                "TikTok upload initialised: publish_id=%s", publish_id
            )

            # Step 2 -- upload video chunks
            await self._upload_chunks(client, upload_url, video_path, file_size)

            # Step 3 -- poll until published
            await self._poll_publish_status(client, publish_id)

        logger.info(
            "TikTok video published successfully: publish_id=%s", publish_id
        )
        return publish_id

    async def refresh_token(
        self,
        client_key: str,
        client_secret: str,
        refresh_token_str: str,
    ) -> dict:
        """Exchange a refresh token for a new access token.

        Uses the TikTok OAuth2 token endpoint.

        Parameters
        ----------
        client_key:
            The TikTok app's client key.
        client_secret:
            The TikTok app's client secret.
        refresh_token_str:
            The refresh token obtained during authorisation.

        Returns
        -------
        dict
            The full JSON response containing ``access_token``,
            ``refresh_token``, ``expires_in``, and related fields.
        """
        logger.info("Refreshing TikTok access token")

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{_BASE_URL}/v2/oauth/token/",
                json={
                    "client_key": client_key,
                    "client_secret": client_secret,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token_str,
                },
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data: dict = resp.json()

        logger.info(
            "TikTok token refreshed; expires in %s seconds",
            data.get("data", {}).get("expires_in", "unknown"),
        )
        return data

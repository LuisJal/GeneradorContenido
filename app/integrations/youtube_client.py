"""YouTube Data API v3 client for uploading Shorts.

Provides an async interface for resumable video uploads and OAuth2
token refresh via the Google APIs.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import httpx

from app.utils.logging_config import get_logger

logger = get_logger(__name__)

_BASE_URL = "https://www.googleapis.com"
_UPLOAD_URL = f"{_BASE_URL}/upload/youtube/v3/videos"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_CHUNK_SIZE = 10 * 1024 * 1024  # 10 MiB per chunk


class YouTubeUploadError(Exception):
    """Raised when a YouTube upload operation fails."""


class YouTubeClient:
    """Async client for the YouTube Data API v3.

    Parameters
    ----------
    access_token:
        A valid OAuth2 access token with the ``youtube.upload`` scope.
    """

    def __init__(self, access_token: str) -> None:
        self._access_token = access_token

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _auth_headers(self) -> Dict[str, str]:
        """Return the ``Authorization`` header dict."""
        return {"Authorization": f"Bearer {self._access_token}"}

    def _build_client(self, timeout: float = 60.0) -> httpx.AsyncClient:
        """Return a configured ``httpx.AsyncClient``."""
        return httpx.AsyncClient(
            headers=self._auth_headers(),
            timeout=timeout,
        )

    @staticmethod
    def _build_snippet(
        title: str,
        description: str,
        tags: List[str],
        category_id: str,
    ) -> Dict[str, Any]:
        """Build the JSON body for the resumable upload init request."""
        return {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": category_id,
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False,
            },
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def upload_short(
        self,
        video_path: str,
        title: str,
        description: str,
        tags: Optional[List[str]] = None,
        category_id: str = "22",
    ) -> str:
        """Upload a video as a YouTube Short using resumable upload.

        The upload follows Google's resumable upload protocol:

        1. **Initiate** the upload session and obtain an upload URI.
        2. **Transfer** the video file in *_CHUNK_SIZE* chunks.
        3. **Parse** the final response to extract the video ID.

        Parameters
        ----------
        video_path:
            Local filesystem path to the video file.
        title:
            Video title (should contain ``#Shorts`` for Short detection).
        description:
            Video description text.
        tags:
            Optional list of tag strings.
        category_id:
            YouTube video category ID.  Defaults to ``"22"``
            (People & Blogs).

        Returns
        -------
        str
            The YouTube video ID (e.g. ``"dQw4w9WgXcQ"``).

        Raises
        ------
        YouTubeUploadError
            If the initiation or any chunk transfer fails.
        FileNotFoundError
            If *video_path* does not exist.
        """
        if tags is None:
            tags = []

        file_size = os.path.getsize(video_path)
        logger.info(
            "Starting YouTube Short upload: title=%r, file=%s (%d bytes)",
            title,
            video_path,
            file_size,
        )

        snippet_body = self._build_snippet(title, description, tags, category_id)

        async with self._build_client(timeout=300.0) as client:
            # Step 1 -- initiate resumable upload
            init_resp = await client.post(
                _UPLOAD_URL,
                params={
                    "uploadType": "resumable",
                    "part": "snippet,status",
                },
                json=snippet_body,
                headers={
                    **self._auth_headers(),
                    "Content-Type": "application/json; charset=UTF-8",
                    "X-Upload-Content-Length": str(file_size),
                    "X-Upload-Content-Type": "video/*",
                },
            )
            if init_resp.status_code not in (200, 308):
                raise YouTubeUploadError(
                    f"Failed to initiate resumable upload: "
                    f"{init_resp.status_code} {init_resp.text}"
                )

            upload_url: Optional[str] = init_resp.headers.get("Location")
            if upload_url is None:
                raise YouTubeUploadError(
                    "No upload Location header in initiation response"
                )
            logger.debug("Resumable upload URL obtained: %s", upload_url)

            # Step 2 -- upload video in chunks
            video_id = await self._upload_chunks(client, upload_url, video_path, file_size)

        logger.info("YouTube Short uploaded successfully: video_id=%s", video_id)
        return video_id

    async def _upload_chunks(
        self,
        client: httpx.AsyncClient,
        upload_url: str,
        video_path: str,
        file_size: int,
    ) -> str:
        """Stream the video file in chunks to *upload_url*.

        Returns the video ID from the final chunk response.
        """
        offset = 0

        with open(video_path, "rb") as fh:
            while offset < file_size:
                chunk = fh.read(_CHUNK_SIZE)
                chunk_len = len(chunk)
                end = offset + chunk_len - 1

                content_range = f"bytes {offset}-{end}/{file_size}"
                logger.debug("Uploading chunk: %s", content_range)

                resp = await client.put(
                    upload_url,
                    content=chunk,
                    headers={
                        "Content-Length": str(chunk_len),
                        "Content-Range": content_range,
                        "Content-Type": "video/*",
                    },
                )

                if resp.status_code == 200 or resp.status_code == 201:
                    # Final chunk accepted -- extract video ID
                    data = resp.json()
                    video_id: Optional[str] = data.get("id")
                    if video_id is None:
                        raise YouTubeUploadError(
                            f"Upload completed but no video id in response: {data}"
                        )
                    return video_id

                if resp.status_code == 308:
                    # Chunk accepted, continue
                    offset += chunk_len
                    continue

                raise YouTubeUploadError(
                    f"Unexpected status during chunk upload: "
                    f"{resp.status_code} {resp.text}"
                )

        raise YouTubeUploadError(
            "Upload loop ended without a final 200/201 response"
        )

    async def refresh_token(
        self,
        client_id: str,
        client_secret: str,
        refresh_token_str: str,
    ) -> dict:
        """Exchange a refresh token for a new access token.

        Uses Google's OAuth2 token endpoint.

        Parameters
        ----------
        client_id:
            The OAuth2 client ID.
        client_secret:
            The OAuth2 client secret.
        refresh_token_str:
            The refresh token previously obtained during authorization.

        Returns
        -------
        dict
            The full JSON response containing ``access_token``,
            ``expires_in``, ``token_type``, and optionally a new
            ``refresh_token``.
        """
        logger.info("Refreshing YouTube / Google OAuth2 token")

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                _TOKEN_URL,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token_str,
                    "grant_type": "refresh_token",
                },
            )
            resp.raise_for_status()
            data: dict = resp.json()

        logger.info(
            "Google token refreshed; expires in %s seconds",
            data.get("expires_in", "unknown"),
        )
        return data

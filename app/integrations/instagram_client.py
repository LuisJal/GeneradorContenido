"""Instagram Graph API client for publishing Reels.

Wraps the Meta Graph API to create and publish Instagram Reels,
and to manage long-lived access tokens.
"""

from __future__ import annotations

import asyncio
from typing import Optional

import httpx

from app.utils.logging_config import get_logger

logger = get_logger(__name__)

_DEFAULT_API_VERSION = "v21.0"
_BASE_URL = "https://graph.facebook.com"
_POLL_INTERVAL_SECONDS = 5
_POLL_TIMEOUT_SECONDS = 120


class InstagramPublishError(Exception):
    """Raised when an Instagram publish operation fails."""


class InstagramClient:
    """Async client for the Meta Graph API (Instagram Reels).

    Parameters
    ----------
    access_token:
        A valid Facebook / Instagram access token with the
        ``instagram_content_publish`` permission.
    api_version:
        Graph API version string, e.g. ``"v21.0"``.
    """

    def __init__(
        self,
        access_token: str,
        api_version: str = _DEFAULT_API_VERSION,
    ) -> None:
        self._access_token = access_token
        self._api_version = api_version
        self._base_url = f"{_BASE_URL}/{self._api_version}"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_client(self, timeout: float = 30.0) -> httpx.AsyncClient:
        """Return a configured ``httpx.AsyncClient``."""
        return httpx.AsyncClient(
            base_url=self._base_url,
            params={"access_token": self._access_token},
            timeout=timeout,
        )

    async def _wait_for_container(
        self,
        client: httpx.AsyncClient,
        container_id: str,
    ) -> None:
        """Poll the media container until its status is ``FINISHED``.

        Raises
        ------
        InstagramPublishError
            If the container is not ready within *_POLL_TIMEOUT_SECONDS*
            or the API reports an error status.
        """
        elapsed = 0
        while elapsed < _POLL_TIMEOUT_SECONDS:
            resp = await client.get(
                f"/{container_id}",
                params={"fields": "status_code"},
            )
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status_code")

            logger.debug(
                "Container %s status: %s (elapsed %ds)",
                container_id,
                status,
                elapsed,
            )

            if status == "FINISHED":
                return
            if status == "ERROR":
                raise InstagramPublishError(
                    f"Media container {container_id} entered ERROR state: {data}"
                )

            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
            elapsed += _POLL_INTERVAL_SECONDS

        raise InstagramPublishError(
            f"Timed out waiting for container {container_id} after "
            f"{_POLL_TIMEOUT_SECONDS}s"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def publish_reel(
        self,
        ig_user_id: str,
        video_url: str,
        caption: str,
    ) -> str:
        """Create and publish an Instagram Reel.

        The workflow follows the three-step Container Publishing flow
        documented by Meta:

        1. **Create** a media container for the Reel.
        2. **Wait** for the container to finish processing (server-side
           video encoding).
        3. **Publish** the container to the user's feed.

        Parameters
        ----------
        ig_user_id:
            The Instagram-scoped user ID (numeric string).
        video_url:
            A publicly-accessible URL of the video file.
        caption:
            The caption / description text for the Reel.

        Returns
        -------
        str
            The published media ID.

        Raises
        ------
        InstagramPublishError
            On any failure during creation, polling, or publishing.
        httpx.HTTPStatusError
            On unexpected HTTP-level errors from the Graph API.
        """
        logger.info(
            "Publishing Reel for IG user %s (video_url=%s)",
            ig_user_id,
            video_url,
        )

        async with self._build_client(timeout=60.0) as client:
            # Step 1 -- create media container
            create_resp = await client.post(
                f"/{ig_user_id}/media",
                data={
                    "media_type": "REELS",
                    "video_url": video_url,
                    "caption": caption,
                },
            )
            create_resp.raise_for_status()
            container_id: str = create_resp.json()["id"]
            logger.info("Created media container %s", container_id)

            # Step 2 -- poll until container is ready
            await self._wait_for_container(client, container_id)

            # Step 3 -- publish the container
            publish_resp = await client.post(
                f"/{ig_user_id}/media_publish",
                data={"creation_id": container_id},
            )
            publish_resp.raise_for_status()
            media_id: str = publish_resp.json()["id"]
            logger.info("Reel published successfully: media_id=%s", media_id)

        return media_id

    async def refresh_token(self, current_token: str) -> dict:
        """Exchange a short-lived token for a long-lived one.

        Uses the ``/oauth/access_token`` endpoint with
        ``grant_type=fb_exchange_token``.

        Parameters
        ----------
        current_token:
            The short-lived token to exchange.

        Returns
        -------
        dict
            The full JSON response, which includes ``access_token`` and
            ``expires_in`` among other fields.
        """
        logger.info("Refreshing Instagram / Facebook access token")

        async with self._build_client() as client:
            resp = await client.get(
                "/oauth/access_token",
                params={
                    "grant_type": "fb_exchange_token",
                    "fb_exchange_token": current_token,
                },
            )
            resp.raise_for_status()
            data: dict = resp.json()

        logger.info(
            "Token refreshed; new token expires in %s seconds",
            data.get("expires_in", "unknown"),
        )
        return data

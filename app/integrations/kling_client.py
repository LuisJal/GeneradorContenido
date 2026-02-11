"""Kling 3.0 video generation client using the direct HTTP API."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from app.integrations.base_client import BaseAPIClient
from app.utils.logging_config import get_logger

logger = get_logger("integrations.kling_client")

_KLING_BASE_URL = "https://api.klingapi.com"

# Polling defaults
_POLL_TIMEOUT_SECONDS: int = 15 * 60  # 15 minutes
_POLL_INTERVAL_SECONDS: int = 10


class KlingClient(BaseAPIClient):
    """Client for Kling 3.0 text-to-video generation via HTTP API.

    Inherits retry / rate-limit logic from :class:`BaseAPIClient`.
    """

    def __init__(self, api_key: str) -> None:
        super().__init__(
            base_url=_KLING_BASE_URL,
            timeout=60.0,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        logger.info("KlingClient initialised (base_url=%s)", _KLING_BASE_URL)

    # ------------------------------------------------------------------
    # Video generation
    # ------------------------------------------------------------------

    async def generate_video(
        self,
        prompt: str,
        duration: int = 10,
        aspect_ratio: str = "9:16",
    ) -> str:
        """Submit a text-to-video generation request.

        Parameters
        ----------
        prompt:
            Natural-language description of the desired video.
        duration:
            Target video duration in seconds (default ``10``).
        aspect_ratio:
            Aspect ratio string, e.g. ``"9:16"`` or ``"16:9"``.

        Returns
        -------
        str
            The ``task_id`` used for polling status.
        """
        logger.info(
            "Submitting Kling 3.0 video generation (duration=%ss, ratio=%s)",
            duration,
            aspect_ratio,
        )

        payload: Dict[str, Any] = {
            "model": "kling-v3",
            "prompt": prompt,
            "duration": duration,
            "aspect_ratio": aspect_ratio,
            "mode": "quality",
        }

        data = await self.post("/v1/videos/text2video", json=payload)

        task_id: str = data["data"]["task_id"]
        logger.info("Kling 3.0 task submitted: %s", task_id)
        return task_id

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    async def poll_status(
        self,
        task_id: str,
        timeout: int = _POLL_TIMEOUT_SECONDS,
        interval: int = _POLL_INTERVAL_SECONDS,
    ) -> Dict[str, Any]:
        """Poll a video generation task until completion or timeout.

        Parameters
        ----------
        task_id:
            The task ID returned by :meth:`generate_video`.
        timeout:
            Maximum wall-clock seconds to wait (default 15 min).
        interval:
            Seconds between successive polls (default 10 s).

        Returns
        -------
        dict
            ``{"status": "completed", "video_url": "..."}`` on success or
            ``{"status": "failed", "error": "..."}`` on failure / timeout.
            Also returns ``{"status": "processing"}`` while still in progress
            (only when called individually -- :meth:`poll_status` blocks until
            a terminal state when using the default parameters).
        """
        logger.info("Polling Kling 3.0 task: %s", task_id)
        start = time.monotonic()

        while time.monotonic() - start < timeout:
            data = await self.get(f"/v1/videos/text2video/{task_id}")

            task_data = data.get("data", {})
            task_status = task_data.get("task_status", "unknown")

            if task_status == "completed":
                videos = task_data.get("task_result", {}).get("videos", [])
                if videos:
                    video_url = videos[0].get("url", "")
                    logger.info(
                        "Kling 3.0 task completed: %s -> %s", task_id, video_url
                    )
                    return {"status": "completed", "video_url": video_url}

                logger.warning(
                    "Kling 3.0 task completed but no videos: %s", task_id
                )
                return {
                    "status": "failed",
                    "error": "Task completed but no video URL was returned.",
                }

            if task_status == "failed":
                error_msg = task_data.get("task_status_msg", "Unknown error")
                logger.error(
                    "Kling 3.0 task failed: %s -- %s", task_id, error_msg
                )
                return {"status": "failed", "error": error_msg}

            elapsed = int(time.monotonic() - start)
            logger.debug(
                "Kling 3.0 task %s still %s (%ss elapsed)",
                task_id,
                task_status,
                elapsed,
            )
            await asyncio.sleep(interval)

        logger.error(
            "Kling 3.0 task timed out after %ss: %s", timeout, task_id
        )
        return {
            "status": "failed",
            "error": f"Polling timed out after {timeout} seconds.",
        }

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    async def download_video(
        self,
        video_url: str,
        local_path: str,
    ) -> str:
        """Download a generated video to a local file.

        Parameters
        ----------
        video_url:
            The remote URL of the generated video.
        local_path:
            Destination path on the local file system.

        Returns
        -------
        str
            The ``local_path`` where the video was saved.
        """
        logger.info("Downloading Kling 3.0 video to %s", local_path)
        dest = Path(local_path)
        dest.parent.mkdir(parents=True, exist_ok=True)

        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            async with client.stream("GET", video_url) as response:
                response.raise_for_status()
                with open(dest, "wb") as fh:
                    async for chunk in response.aiter_bytes(chunk_size=1024 * 64):
                        fh.write(chunk)

        file_size_mb = dest.stat().st_size / (1024 * 1024)
        logger.info(
            "Kling 3.0 video downloaded: %s (%.1f MB)", local_path, file_size_mb
        )
        return str(dest)

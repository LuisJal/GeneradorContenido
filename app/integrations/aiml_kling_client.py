"""Kling video generation via AIML API (aimlapi.com).

Uses Kling V3 Standard model which supports 3-15 second native generation
with audio. More economical than direct Kling API (no large prepaid packages).

API docs: https://docs.aimlapi.com/api-references/video-models/kling-ai
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from app.integrations.base_client import BaseAPIClient
from app.utils.logging_config import get_logger

logger = get_logger("integrations.aiml_kling")

_AIML_BASE_URL = "https://api.aimlapi.com"

# Polling defaults
_POLL_TIMEOUT_SECONDS: int = 15 * 60  # 15 minutes
_POLL_INTERVAL_SECONDS: int = 15

# V3 supports 3-15 seconds; clamp to this range.
_MIN_DURATION = 3
_MAX_DURATION = 15


class AimlKlingClient(BaseAPIClient):
    """Client for Kling video generation via the AIML API proxy.

    Inherits retry / rate-limit logic from :class:`BaseAPIClient`.
    """

    def __init__(self, api_key: str, model: str = "klingai/video-v3-standard-text-to-video") -> None:
        super().__init__(
            base_url=_AIML_BASE_URL,
            timeout=60.0,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        self._model = model
        logger.info("AimlKlingClient initialised (model=%s)", self._model)

    # ------------------------------------------------------------------
    # Video generation
    # ------------------------------------------------------------------

    async def generate_video(
        self,
        prompt: str,
        duration: int = 10,
        aspect_ratio: str = "9:16",
        negative_prompt: Optional[str] = None,
        generate_audio: bool = True,
    ) -> str:
        """Submit a text-to-video generation request.

        Parameters
        ----------
        prompt:
            Natural-language description of the desired video.
        duration:
            Target video duration in seconds (3-15 for V3 models).
        aspect_ratio:
            Aspect ratio string, e.g. ``"9:16"`` or ``"16:9"``.
        negative_prompt:
            Elements to exclude from the video.
        generate_audio:
            Whether to generate audio (V3 only).

        Returns
        -------
        str
            The generation ID used for polling status.
        """
        # Clamp duration to V3 range
        clamped = max(_MIN_DURATION, min(_MAX_DURATION, duration))
        if clamped != duration:
            logger.warning(
                "AIML Kling V3 supports %d-%ds; clamping %ds -> %ds",
                _MIN_DURATION, _MAX_DURATION, duration, clamped,
            )
            duration = clamped

        logger.info(
            "Submitting AIML Kling video (model=%s, duration=%ds, ratio=%s, audio=%s)",
            self._model, duration, aspect_ratio, generate_audio,
        )

        payload: Dict[str, Any] = {
            "model": self._model,
            "prompt": prompt,
            "duration": duration,
            "aspect_ratio": aspect_ratio,
            "generate_audio": generate_audio,
        }
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt

        data = await self.post("/v2/video/generations", json=payload)

        generation_id: str = data["id"]
        logger.info("AIML Kling generation submitted: %s", generation_id)
        return generation_id

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    async def poll_status(
        self,
        generation_id: str,
        timeout: int = _POLL_TIMEOUT_SECONDS,
        interval: int = _POLL_INTERVAL_SECONDS,
    ) -> Dict[str, Any]:
        """Poll a video generation task until completion or timeout.

        Returns
        -------
        dict
            ``{"status": "completed", "video_url": "..."}`` on success or
            ``{"status": "failed", "error": "..."}`` on failure / timeout.
        """
        logger.info("Polling AIML Kling generation: %s", generation_id)
        start = time.monotonic()

        while time.monotonic() - start < timeout:
            data = await self.get(
                "/v2/video/generations",
                params={"generation_id": generation_id},
            )

            status = data.get("status", "unknown")

            if status == "completed":
                video_info = data.get("video", {})
                video_url = video_info.get("url", "") if isinstance(video_info, dict) else ""
                if video_url:
                    logger.info(
                        "AIML Kling generation completed: %s -> %s",
                        generation_id, video_url,
                    )
                    return {"status": "completed", "video_url": video_url}

                logger.warning(
                    "AIML Kling generation completed but no video URL: %s", generation_id
                )
                return {
                    "status": "failed",
                    "error": "Generation completed but no video URL was returned.",
                }

            if status == "error":
                error_info = data.get("error", {})
                error_msg = (
                    f"{error_info.get('name', 'Error')}: {error_info.get('message', 'Unknown error')}"
                    if isinstance(error_info, dict)
                    else str(error_info)
                )
                logger.error(
                    "AIML Kling generation failed: %s -- %s", generation_id, error_msg
                )
                return {"status": "failed", "error": error_msg}

            elapsed = int(time.monotonic() - start)
            logger.debug(
                "AIML Kling generation %s still %s (%ds elapsed)",
                generation_id, status, elapsed,
            )
            await asyncio.sleep(interval)

        logger.error(
            "AIML Kling generation timed out after %ds: %s", timeout, generation_id
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

        The AIML CDN URLs do not require authentication.
        """
        logger.info("Downloading AIML Kling video to %s", local_path)
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
            "AIML Kling video downloaded: %s (%.1f MB)", local_path, file_size_mb
        )
        return str(dest)

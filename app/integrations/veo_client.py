"""Google Veo 3 video generation client using the google-genai SDK."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from google import genai
from google.genai.types import GenerateVideosConfig

from app.utils.logging_config import get_logger

logger = get_logger("integrations.veo_client")

# Maximum time (in seconds) to wait while polling a video operation.
_POLL_TIMEOUT_SECONDS: int = 15 * 60  # 15 minutes
_POLL_INTERVAL_SECONDS: int = 15


class Veo3Client:
    """Client for Google Veo 3.1 video generation via Vertex AI.

    Uses the ``google-genai`` SDK (v1.47+) with ``vertexai=True``.
    """

    def __init__(
        self,
        project_id: str,
        location: Optional[str] = None,
    ) -> None:
        self._project_id = project_id
        self._location = location or "us-central1"
        self._client = genai.Client(
            vertexai=True,
            project=self._project_id,
            location=self._location,
        )
        logger.info(
            "Veo3Client initialised (project=%s, location=%s)",
            self._project_id,
            self._location,
        )

    # ------------------------------------------------------------------
    # Video generation
    # ------------------------------------------------------------------

    async def generate_video(
        self,
        prompt: str,
        duration: int = 15,
        aspect_ratio: str = "9:16",
    ) -> str:
        """Submit a video generation request.

        Parameters
        ----------
        prompt:
            Natural-language description of the desired video.
        duration:
            Target video duration in seconds (default ``15``).
        aspect_ratio:
            Aspect ratio string, e.g. ``"9:16"`` or ``"16:9"``.

        Returns
        -------
        str
            The long-running operation name / ID used for polling.
        """
        logger.info(
            "Submitting Veo 3 video generation (duration=%ss, ratio=%s)",
            duration,
            aspect_ratio,
        )

        config = GenerateVideosConfig(
            aspect_ratio=aspect_ratio,
            duration_seconds=duration,
            generate_audio=True,
            person_generation="allow_all",
        )

        # The SDK call is synchronous; run it in a thread so we don't block
        # the event loop.
        operation = await asyncio.to_thread(
            self._client.models.generate_videos,
            model="veo-3.1-generate-001",
            prompt=prompt,
            config=config,
        )

        operation_name: str = operation.name
        logger.info("Veo 3 operation submitted: %s", operation_name)
        return operation_name

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    async def poll_status(
        self,
        operation_name: str,
        timeout: int = _POLL_TIMEOUT_SECONDS,
        interval: int = _POLL_INTERVAL_SECONDS,
    ) -> Dict[str, Any]:
        """Poll a video generation operation until completion or timeout.

        Parameters
        ----------
        operation_name:
            The operation name returned by :meth:`generate_video`.
        timeout:
            Maximum wall-clock seconds to wait (default 15 min).
        interval:
            Seconds between successive polls (default 15 s).

        Returns
        -------
        dict
            ``{"status": "completed", "video_url": "..."}`` on success or
            ``{"status": "failed", "error": "..."}`` on failure / timeout.
        """
        logger.info("Polling Veo 3 operation: %s", operation_name)
        start = time.monotonic()

        while time.monotonic() - start < timeout:
            operation = await asyncio.to_thread(
                self._client.operations.get,
                operation=operation_name,
            )

            if operation.done:
                # Check for an error payload
                if operation.error is not None:
                    error_msg = str(operation.error)
                    logger.error(
                        "Veo 3 operation failed: %s -- %s",
                        operation_name,
                        error_msg,
                    )
                    return {"status": "failed", "error": error_msg}

                # Extract the generated video URL from the result
                result = operation.response
                if result and hasattr(result, "generated_videos") and result.generated_videos:
                    video = result.generated_videos[0]
                    video_url = video.video.uri if hasattr(video, "video") else str(video)
                    logger.info(
                        "Veo 3 operation completed: %s -> %s",
                        operation_name,
                        video_url,
                    )
                    return {"status": "completed", "video_url": video_url}

                logger.warning(
                    "Veo 3 operation done but no video found: %s",
                    operation_name,
                )
                return {
                    "status": "failed",
                    "error": "Operation completed but no video was returned.",
                }

            elapsed = int(time.monotonic() - start)
            logger.debug(
                "Veo 3 operation %s still running (%ss elapsed)",
                operation_name,
                elapsed,
            )
            await asyncio.sleep(interval)

        logger.error(
            "Veo 3 operation timed out after %ss: %s", timeout, operation_name
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
            The remote URL (typically a GCS signed URL) of the video.
        local_path:
            Destination path on the local file system.

        Returns
        -------
        str
            The ``local_path`` where the video was saved.
        """
        logger.info("Downloading Veo 3 video to %s", local_path)
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
            "Veo 3 video downloaded: %s (%.1f MB)", local_path, file_size_mb
        )
        return str(dest)

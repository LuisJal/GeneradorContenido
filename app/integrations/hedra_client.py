"""Hedra Character-3 talking-head video generation client."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from app.utils.logging_config import get_logger

logger = get_logger("integrations.hedra")

_BASE_URL = "https://api.hedra.com/web-app/public"

# Hedra Avatar (Character-3) model -- talking head with lip sync, up to 200s.
_AVATAR_MODEL_ID = "26f0fc66-152b-40ab-abed-76c43df99bc8"

_POLL_TIMEOUT_SECONDS: int = 15 * 60  # 15 minutes
_POLL_INTERVAL_SECONDS: int = 30


class HedraClient:
    """Client for Hedra's Character-3 talking-head video API.

    Workflow: upload face image + audio → generate lip-synced video →
    poll until complete → download.
    """

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._headers: Dict[str, str] = {"X-API-Key": api_key}
        logger.info("HedraClient initialised")

    # ------------------------------------------------------------------
    # Asset management
    # ------------------------------------------------------------------

    async def _create_asset(
        self,
        client: httpx.AsyncClient,
        name: str,
        asset_type: str,
    ) -> str:
        """Create an asset record and return its UUID."""
        resp = await client.post(
            f"{_BASE_URL}/assets",
            headers={**self._headers, "Content-Type": "application/json"},
            json={"name": name, "type": asset_type},
        )
        resp.raise_for_status()
        asset_id: str = resp.json()["id"]
        logger.debug("Created %s asset: %s", asset_type, asset_id)
        return asset_id

    async def _upload_asset(
        self,
        client: httpx.AsyncClient,
        asset_id: str,
        file_path: str,
    ) -> None:
        """Upload a local file to an existing asset record."""
        path = Path(file_path)
        with open(path, "rb") as fh:
            resp = await client.post(
                f"{_BASE_URL}/assets/{asset_id}/upload",
                headers=self._headers,
                files={"file": (path.name, fh)},
            )
        resp.raise_for_status()
        logger.debug("Uploaded file to asset %s: %s", asset_id, path.name)

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    async def generate_talking_head(
        self,
        face_image_path: str,
        audio_path: str,
        aspect_ratio: str = "9:16",
        resolution: str = "720p",
    ) -> str:
        """Submit a talking-head video generation request.

        Parameters
        ----------
        face_image_path:
            Local path to the character's face reference image.
        audio_path:
            Local path to the speech audio file (MP3/WAV).
        aspect_ratio:
            ``"9:16"`` (vertical), ``"16:9"``, or ``"1:1"``.
        resolution:
            ``"540p"`` or ``"720p"`` (720p uses 2x credits).

        Returns
        -------
        str
            The generation ID used for polling.
        """
        logger.info(
            "Submitting Hedra talking-head: face=%s, audio=%s, ratio=%s, res=%s",
            face_image_path, audio_path, aspect_ratio, resolution,
        )

        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            # 1. Upload face image
            image_id = await self._create_asset(
                client, Path(face_image_path).name, "image"
            )
            await self._upload_asset(client, image_id, face_image_path)

            # 2. Upload audio
            audio_id = await self._create_asset(
                client, Path(audio_path).name, "audio"
            )
            await self._upload_asset(client, audio_id, audio_path)

            # 3. Start generation
            payload = {
                "type": "video",
                "ai_model_id": _AVATAR_MODEL_ID,
                "start_keyframe_id": image_id,
                "audio_id": audio_id,
                "generated_video_inputs": {
                    "text_prompt": "A person speaking naturally to camera",
                    "aspect_ratio": aspect_ratio,
                    "resolution": resolution,
                },
            }
            resp = await client.post(
                f"{_BASE_URL}/generations",
                headers={**self._headers, "Content-Type": "application/json"},
                json=payload,
            )
            resp.raise_for_status()
            generation_id: str = resp.json()["id"]

        logger.info("Hedra generation submitted: %s", generation_id)
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
        """Poll a generation until completion or timeout.

        Returns
        -------
        dict
            ``{"status": "completed", "video_url": "..."}`` on success,
            ``{"status": "processing"}`` while still running, or
            ``{"status": "failed", "error": "..."}`` on failure.
        """
        logger.info("Polling Hedra generation: %s", generation_id)
        start = time.monotonic()

        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            while time.monotonic() - start < timeout:
                resp = await client.get(
                    f"{_BASE_URL}/generations/{generation_id}/status",
                    headers=self._headers,
                )
                resp.raise_for_status()
                data = resp.json()
                status = data.get("status", "")

                if status == "complete":
                    video_url = data.get("download_url") or data.get("url", "")
                    logger.info(
                        "Hedra generation complete: %s -> %s",
                        generation_id, video_url,
                    )
                    return {"status": "completed", "video_url": video_url}

                if status == "error":
                    error_msg = data.get("error_message", "Unknown Hedra error")
                    logger.error(
                        "Hedra generation failed: %s -- %s",
                        generation_id, error_msg,
                    )
                    return {"status": "failed", "error": error_msg}

                elapsed = int(time.monotonic() - start)
                progress = data.get("progress", 0)
                logger.debug(
                    "Hedra %s: status=%s progress=%.0f%% (%ds elapsed)",
                    generation_id, status, progress * 100, elapsed,
                )
                await asyncio.sleep(interval)

        logger.error(
            "Hedra generation timed out after %ds: %s",
            timeout, generation_id,
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

        Returns the *local_path* where the video was saved.
        """
        logger.info("Downloading Hedra video to %s", local_path)
        dest = Path(local_path)
        dest.parent.mkdir(parents=True, exist_ok=True)

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(120.0), follow_redirects=True
        ) as client:
            async with client.stream("GET", video_url) as response:
                response.raise_for_status()
                with open(dest, "wb") as fh:
                    async for chunk in response.aiter_bytes(chunk_size=1024 * 64):
                        fh.write(chunk)

        file_size_mb = dest.stat().st_size / (1024 * 1024)
        logger.info(
            "Hedra video downloaded: %s (%.1f MB)", local_path, file_size_mb,
        )
        return str(dest)

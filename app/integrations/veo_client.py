"""Google Veo 3 video generation client using the google-genai SDK."""
from __future__ import annotations

import asyncio
import math
import time
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from google import genai
from google.genai.types import GenerateVideosConfig, GenerateVideosOperation

from app.utils.logging_config import get_logger

logger = get_logger("integrations.veo_client")

# Maximum time (in seconds) to wait while polling a video operation.
_POLL_TIMEOUT_SECONDS: int = 15 * 60  # 15 minutes
_POLL_INTERVAL_SECONDS: int = 15

# Valid single-call durations for the Gemini API.
_GEMINI_API_VALID_DURATIONS = (4, 6, 8)

# Scene Extension constants.
# Max duration achievable in a single API call.
_MAX_SINGLE_DURATION: int = 8
# Each scene extension adds exactly 7 seconds.
_EXTENSION_SECONDS: int = 7
# Google allows up to 20 extensions (8 + 20*7 = 148s max).
_MAX_EXTENSIONS: int = 20

# Model names per authentication mode.
_MODEL_VERTEX = "veo-3.1-generate-001"
_MODEL_GEMINI_API = "veo-3.1-generate-preview"


class Veo3Client:
    """Client for Google Veo 3.1 video generation.

    Supports two authentication modes:
    - **Gemini API key**: pass ``api_key`` (simpler, uses Google AI Studio quota).
    - **Vertex AI**: pass ``project_id`` (requires GCP billing).

    When ``api_key`` is provided it takes precedence over ``project_id``.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        project_id: Optional[str] = None,
        location: Optional[str] = None,
    ) -> None:
        if api_key:
            self._mode = "gemini_api"
            self._api_key = api_key
            self._client = genai.Client(api_key=api_key)
            self._model = _MODEL_GEMINI_API
            logger.info("Veo3Client initialised (mode=gemini_api)")
        elif project_id:
            self._mode = "vertex"
            self._api_key = None
            self._location = location or "us-central1"
            self._client = genai.Client(
                vertexai=True,
                project=project_id,
                location=self._location,
            )
            self._model = _MODEL_VERTEX
            logger.info(
                "Veo3Client initialised (mode=vertex, project=%s, location=%s)",
                project_id,
                self._location,
            )
        else:
            raise ValueError(
                "Veo3Client requires either api_key or project_id."
            )

    # ------------------------------------------------------------------
    # Video generation
    # ------------------------------------------------------------------

    async def generate_video(
        self,
        prompt: str,
        duration: int = 8,
        aspect_ratio: str = "9:16",
    ) -> str:
        """Submit a video generation request.

        Parameters
        ----------
        prompt:
            Natural-language description of the desired video.
        duration:
            Target video duration in seconds.  For single-call durations
            (4, 6, 8) the API is called once.  For longer durations the
            Scene Extension API is used: an initial 8 s clip is generated,
            then iteratively extended (+7 s each) until the target is
            reached.  The method blocks until the full chain completes.
        aspect_ratio:
            Aspect ratio string, e.g. ``"9:16"`` or ``"16:9"``.

        Returns
        -------
        str
            The long-running operation name / ID used for polling.
            For extended videos this is the *last* operation in the chain
            (already completed when returned).
        """
        # For durations beyond the single-call max, use scene extension.
        if duration > _MAX_SINGLE_DURATION:
            return await self._generate_extended_video(prompt, duration, aspect_ratio)

        # Clamp duration for Gemini API mode.
        if self._mode == "gemini_api" and duration not in _GEMINI_API_VALID_DURATIONS:
            clamped = min(
                _GEMINI_API_VALID_DURATIONS, key=lambda d: abs(d - duration)
            )
            logger.warning(
                "Gemini API only supports durations %s; clamping %ss -> %ss",
                _GEMINI_API_VALID_DURATIONS,
                duration,
                clamped,
            )
            duration = clamped

        logger.info(
            "Submitting Veo 3 video generation (model=%s, duration=%ss, ratio=%s)",
            self._model,
            duration,
            aspect_ratio,
        )

        config_kwargs: Dict[str, Any] = {
            "aspect_ratio": aspect_ratio,
            "duration_seconds": duration,
            "person_generation": "allow_all",
        }
        # generate_audio is only supported in Vertex AI mode.
        if self._mode == "vertex":
            config_kwargs["generate_audio"] = True

        config = GenerateVideosConfig(**config_kwargs)

        # The SDK call is synchronous; run it in a thread so we don't block
        # the event loop.
        operation = await asyncio.to_thread(
            self._client.models.generate_videos,
            model=self._model,
            prompt=prompt,
            config=config,
        )

        operation_name: str = operation.name
        logger.info("Veo 3 operation submitted: %s", operation_name)
        return operation_name

    # ------------------------------------------------------------------
    # Scene Extension (long videos)
    # ------------------------------------------------------------------

    async def _generate_extended_video(
        self,
        prompt: str,
        target_duration: int,
        aspect_ratio: str,
    ) -> str:
        """Generate a long video via initial clip + iterative scene extensions.

        The Veo API limits a single call to 8 s.  Scene Extension appends
        7 s per iteration by feeding the previous result back.  This method
        blocks until the full chain is done or an unrecoverable error occurs.

        Returns the operation name of the *last* successful step.
        """
        extensions_needed = min(
            math.ceil((target_duration - _MAX_SINGLE_DURATION) / _EXTENSION_SECONDS),
            _MAX_EXTENSIONS,
        )
        total_expected = _MAX_SINGLE_DURATION + extensions_needed * _EXTENSION_SECONDS

        logger.info(
            "Extended video: target=%ds, plan: %ds initial + %d extensions "
            "(+%ds each) = ~%ds total",
            target_duration,
            _MAX_SINGLE_DURATION,
            extensions_needed,
            _EXTENSION_SECONDS,
            total_expected,
        )

        # --- Step 1: initial 8 s clip ------------------------------------
        init_config_kwargs: Dict[str, Any] = {
            "aspect_ratio": aspect_ratio,
            "duration_seconds": _MAX_SINGLE_DURATION,
            "person_generation": "allow_all",
            "number_of_videos": 1,
        }
        if self._mode == "vertex":
            init_config_kwargs["generate_audio"] = True

        operation = await asyncio.to_thread(
            self._client.models.generate_videos,
            model=self._model,
            prompt=prompt,
            config=GenerateVideosConfig(**init_config_kwargs),
        )
        logger.info("Initial %ds clip submitted: %s", _MAX_SINGLE_DURATION, operation.name)

        completed_op = await self._poll_operation_until_done(operation.name)
        if completed_op is None:
            # Initial generation failed -- return its name so poll_status
            # reports the error to the pipeline.
            return operation.name

        video_ref = completed_op.response.generated_videos[0].video
        last_op_name: str = operation.name

        # --- Step 2: iterative scene extensions ---------------------------
        for i in range(1, extensions_needed + 1):
            logger.info("Scene extension %d/%d starting...", i, extensions_needed)

            ext_config_kwargs: Dict[str, Any] = {
                "number_of_videos": 1,
                "person_generation": "allow_all",
            }
            if self._mode == "vertex":
                ext_config_kwargs["generate_audio"] = True

            ext_operation = await asyncio.to_thread(
                self._client.models.generate_videos,
                model=self._model,
                prompt=prompt,
                video=video_ref,
                config=GenerateVideosConfig(**ext_config_kwargs),
            )
            logger.info(
                "Extension %d/%d submitted: %s", i, extensions_needed, ext_operation.name
            )

            completed_ext = await self._poll_operation_until_done(ext_operation.name)
            if completed_ext is None:
                current_secs = _MAX_SINGLE_DURATION + (i - 1) * _EXTENSION_SECONDS
                logger.warning(
                    "Extension %d/%d failed. Returning partial video (~%ds).",
                    i,
                    extensions_needed,
                    current_secs,
                )
                break

            video_ref = completed_ext.response.generated_videos[0].video
            last_op_name = ext_operation.name

            # Brief pause between extensions to be gentle on rate limits.
            if i < extensions_needed:
                await asyncio.sleep(3)

        logger.info("Extended video generation complete: %s", last_op_name)
        return last_op_name

    async def _poll_operation_until_done(
        self,
        operation_name: str,
        timeout: int = _POLL_TIMEOUT_SECONDS,
    ) -> Optional[Any]:
        """Poll an operation until done, returning the raw SDK operation.

        Returns ``None`` on failure or timeout so callers can decide whether
        to abort or return a partial result.
        """
        start = time.monotonic()

        while time.monotonic() - start < timeout:
            op_ref = GenerateVideosOperation(name=operation_name)
            operation = await asyncio.to_thread(
                self._client.operations.get,
                operation=op_ref,
            )

            if operation.done:
                if operation.error is not None:
                    logger.error(
                        "Operation failed: %s -- %s", operation_name, operation.error
                    )
                    return None

                resp = operation.response
                if resp and hasattr(resp, "generated_videos") and resp.generated_videos:
                    logger.info("Operation completed: %s", operation_name)
                    return operation

                logger.error("Operation done but no video: %s", operation_name)
                return None

            elapsed = int(time.monotonic() - start)
            logger.debug("Operation %s still running (%ds)", operation_name, elapsed)
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)

        logger.error("Operation timed out after %ds: %s", timeout, operation_name)
        return None

    # ------------------------------------------------------------------
    # Polling (public)
    # ------------------------------------------------------------------

    async def poll_status(
        self,
        operation_name: str,
        timeout: int = _POLL_TIMEOUT_SECONDS,
        interval: int = _POLL_INTERVAL_SECONDS,
    ) -> Dict[str, Any]:
        """Poll a video generation operation until completion or timeout.

        Returns
        -------
        dict
            ``{"status": "completed", "video_url": "..."}`` on success or
            ``{"status": "failed", "error": "..."}`` on failure / timeout.
        """
        logger.info("Polling Veo 3 operation: %s", operation_name)
        start = time.monotonic()

        while time.monotonic() - start < timeout:
            # The SDK expects a GenerateVideosOperation object.
            op_ref = GenerateVideosOperation(name=operation_name)
            operation = await asyncio.to_thread(
                self._client.operations.get,
                operation=op_ref,
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
            The remote URL of the video.
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

        headers = {}
        if self._api_key:
            headers["x-goog-api-key"] = self._api_key

        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0), follow_redirects=True) as client:
            async with client.stream("GET", video_url, headers=headers) as response:
                response.raise_for_status()
                with open(dest, "wb") as fh:
                    async for chunk in response.aiter_bytes(chunk_size=1024 * 64):
                        fh.write(chunk)

        file_size_mb = dest.stat().st_size / (1024 * 1024)
        logger.info(
            "Veo 3 video downloaded: %s (%.1f MB)", local_path, file_size_mb
        )
        return str(dest)

"""Video generation service -- strategy pattern for multiple providers."""
from __future__ import annotations

from typing import Any, Dict, Union

from app.config import settings
from app.integrations.kling_client import KlingClient
from app.integrations.veo_client import Veo3Client
from app.models.bot import Bot
from app.utils.file_storage import get_video_path
from app.utils.logging_config import get_logger

logger = get_logger("services.video_generator")

# ---------------------------------------------------------------------------
# Provider factory
# ---------------------------------------------------------------------------

def _get_veo3_client(bot: Bot) -> Veo3Client:
    """Build a :class:`Veo3Client` using bot / global settings.

    Prefers Gemini API key (simpler) over Vertex AI project.
    """
    # Try Gemini API key first (bot-level override or global).
    from app.utils.encryption import FieldEncryptor
    api_key = None
    if bot.gemini_api_key_encrypted and settings.encryption_key:
        enc = FieldEncryptor(settings.encryption_key)
        api_key = enc.decrypt(bot.gemini_api_key_encrypted)
    if not api_key:
        api_key = settings.gemini_api_key

    if api_key:
        return Veo3Client(api_key=api_key)

    # Fall back to Vertex AI.
    project_id = settings.google_cloud_project
    if not project_id:
        raise ValueError(
            "No video generation credentials configured. "
            "Set GEMINI_API_KEY or GOOGLE_CLOUD_PROJECT in .env"
        )
    return Veo3Client(project_id=project_id)


def _get_kling_client(bot: Bot) -> KlingClient:
    """Build a :class:`KlingClient` using bot / global settings."""
    api_key = settings.kling_api_key
    if not api_key:
        raise ValueError(
            "Kling API key is not configured (set KLING_API_KEY in .env)"
        )
    return KlingClient(api_key=api_key)


def _get_client(bot: Bot) -> Union[Veo3Client, KlingClient]:
    """Return the appropriate video client based on ``bot.video_provider``."""
    provider = bot.video_provider

    if provider == "veo3":
        return _get_veo3_client(bot)
    if provider == "kling3":
        return _get_kling_client(bot)

    raise ValueError(f"Unsupported video provider: {provider!r}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def submit_video_generation(
    bot: Bot,
    video_prompt: str,
    content_id: int,
) -> str:
    """Select the video provider and submit a generation request.

    Parameters
    ----------
    bot:
        The bot whose ``video_provider``, ``video_duration_seconds``, and
        ``video_aspect_ratio`` settings drive provider selection.
    video_prompt:
        Natural-language prompt describing the desired video.
    content_id:
        Associated :class:`ContentItem` ID (used for logging context).

    Returns
    -------
    str
        The task / operation ID that can be used to poll for status.
    """
    provider = bot.video_provider
    logger.info(
        "Submitting video generation for content_id=%s via provider=%s",
        content_id,
        provider,
    )

    client = _get_client(bot)

    try:
        task_id = await client.generate_video(
            prompt=video_prompt,
            duration=bot.video_duration_seconds,
            aspect_ratio=bot.video_aspect_ratio,
        )
    finally:
        # Ensure we clean up the HTTP client for BaseAPIClient subclasses
        if hasattr(client, "close"):
            await client.close()

    logger.info(
        "Video generation submitted: content_id=%s, provider=%s, task_id=%s",
        content_id,
        provider,
        task_id,
    )
    return task_id


async def check_video_status(
    bot: Bot,
    task_id: str,
) -> Dict[str, Any]:
    """Poll the provider for the current status of a generation task.

    Parameters
    ----------
    bot:
        Bot whose ``video_provider`` drives which client to use.
    task_id:
        The task / operation ID returned by :func:`submit_video_generation`.

    Returns
    -------
    dict
        ``{"status": "completed", "video_url": "..."}`` on success,
        ``{"status": "processing"}`` while still running, or
        ``{"status": "failed", "error": "..."}`` on failure.
    """
    provider = bot.video_provider
    logger.info(
        "Checking video status: provider=%s, task_id=%s", provider, task_id
    )

    client = _get_client(bot)

    try:
        result = await client.poll_status(task_id)
    finally:
        if hasattr(client, "close"):
            await client.close()

    logger.info(
        "Video status for task_id=%s: %s", task_id, result.get("status")
    )
    return result


async def download_video(
    bot: Bot,
    video_url: str,
    content_id: int,
) -> str:
    """Download a completed video to local storage.

    Parameters
    ----------
    bot:
        Bot instance (``slug`` is used for directory organisation).
    video_url:
        Remote URL of the generated video.
    content_id:
        Associated :class:`ContentItem` ID (drives the local filename).

    Returns
    -------
    str
        Absolute local file path where the video was saved.
    """
    local_path = get_video_path(bot.slug, content_id)
    logger.info(
        "Downloading video for content_id=%s to %s", content_id, local_path
    )

    client = _get_client(bot)

    try:
        saved_path = await client.download_video(
            video_url=video_url,
            local_path=str(local_path),
        )
    finally:
        if hasattr(client, "close"):
            await client.close()

    logger.info(
        "Video downloaded for content_id=%s: %s", content_id, saved_path
    )
    return saved_path

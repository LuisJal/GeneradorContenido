"""Video generation service -- strategy pattern for multiple providers."""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Union

import httpx

from app.config import settings
from app.integrations.aiml_kling_client import AimlKlingClient
from app.integrations.hedra_client import HedraClient
from app.integrations.kling_client import KlingClient
from app.integrations.veo_client import Veo3Client
from app.models.bot import Bot
from app.utils.file_storage import get_video_path
from app.utils.logging_config import get_logger

logger = get_logger("services.video_generator")


def _settings_db_session():
    """Create a short-lived sync Session for reading global settings."""
    from sqlalchemy.orm import Session as OrmSession

    from app.database import sync_engine
    return OrmSession(sync_engine)


# ---------------------------------------------------------------------------
# Provider factory
# ---------------------------------------------------------------------------

def _get_veo3_client(bot: Bot) -> Veo3Client:
    """Build a :class:`Veo3Client` using bot / global settings.

    Prefers Gemini API key (simpler) over Vertex AI project.
    """
    from app.services.settings_manager import get_setting
    from app.utils.encryption import FieldEncryptor

    # Try Gemini API key first (bot-level override or global).
    api_key = None
    if bot.gemini_api_key_encrypted and settings.encryption_key:
        enc = FieldEncryptor(settings.encryption_key)
        api_key = enc.decrypt(bot.gemini_api_key_encrypted)
    if not api_key:
        db = _settings_db_session()
        try:
            api_key = get_setting(db, "gemini_api_key")
        finally:
            db.close()

    if api_key:
        return Veo3Client(api_key=api_key)

    # Fall back to Vertex AI.
    db = _settings_db_session()
    try:
        project_id = get_setting(db, "google_cloud_project")
    finally:
        db.close()

    if not project_id:
        raise ValueError(
            "No video generation credentials configured. "
            "Set Gemini API Key or Google Cloud Project in Settings"
        )
    return Veo3Client(project_id=project_id)


def _get_kling_client(bot: Bot) -> KlingClient:
    """Build a :class:`KlingClient` using bot / global settings.

    Prefers JWT auth (access_key + secret_key) over legacy api_key.
    Keys are read from DB settings first, then .env fallback.
    """
    from app.services.settings_manager import get_setting

    db = _settings_db_session()
    try:
        access_key = get_setting(db, "kling_access_key")
        secret_key = get_setting(db, "kling_secret_key")
    finally:
        db.close()

    if access_key and secret_key:
        return KlingClient(access_key=access_key, secret_key=secret_key)

    # Fallback to legacy api_key
    api_key = settings.kling_api_key
    if not api_key:
        raise ValueError(
            "Kling credentials not configured. Set Access Key + Secret Key "
            "in Settings, or KLING_API_KEY in .env"
        )
    return KlingClient(api_key=api_key)


def _get_aiml_kling_client(bot: Bot) -> AimlKlingClient:
    """Build an :class:`AimlKlingClient` using global settings."""
    from app.services.settings_manager import get_setting

    db = _settings_db_session()
    try:
        api_key = get_setting(db, "aiml_api_key")
    finally:
        db.close()

    if not api_key:
        raise ValueError(
            "AIML API key is not configured. Set it in Settings or AIML_API_KEY in .env"
        )
    return AimlKlingClient(api_key=api_key)


def _get_talking_head_client(bot: Bot) -> HedraClient:
    """Build a :class:`HedraClient` using global settings."""
    from app.services.settings_manager import get_setting

    db = _settings_db_session()
    try:
        api_key = get_setting(db, "hedra_api_key")
    finally:
        db.close()

    if not api_key:
        raise ValueError(
            "Hedra API key is not configured. Set it in Settings."
        )
    return HedraClient(api_key=api_key)


async def _download_face_image(url: str) -> str:
    """Download a face reference image from URL to a temp file."""
    suffix = Path(url.split("?")[0]).suffix or ".png"
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False, prefix="face_")
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0), follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        tmp.write(resp.content)
    tmp.close()
    logger.debug("Face image downloaded to %s", tmp.name)
    return tmp.name


def _get_client(bot: Bot) -> Union[Veo3Client, KlingClient, AimlKlingClient, HedraClient]:
    """Return the appropriate video client based on ``bot.video_provider``."""
    provider = bot.video_provider

    if provider == "veo3":
        return _get_veo3_client(bot)
    if provider == "kling3":
        return _get_kling_client(bot)
    if provider == "aiml_kling":
        return _get_aiml_kling_client(bot)
    if provider == "talking_head":
        return _get_talking_head_client(bot)

    raise ValueError(f"Unsupported video provider: {provider!r}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def submit_video_generation(
    bot: Bot,
    video_prompt: str,
    content_id: int,
    *,
    audio_path: Optional[str] = None,
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
    audio_path:
        Path to TTS audio file.  Required for ``talking_head`` provider.

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
        if provider == "talking_head":
            # Talking-head: face image + audio → lip-synced video (Hedra)
            if not audio_path:
                raise ValueError("audio_path is required for talking_head provider")
            face_url = bot.character_face_url
            if not face_url:
                raise ValueError("Bot has no character_face_url for talking_head")

            # Download face image if it's a URL
            if face_url.startswith("http"):
                face_local = await _download_face_image(face_url)
            else:
                face_local = face_url

            task_id = await client.generate_talking_head(
                face_image_path=face_local,
                audio_path=audio_path,
                aspect_ratio=bot.video_aspect_ratio,
            )
        else:
            task_id = await client.generate_video(
                prompt=video_prompt,
                duration=bot.video_duration_seconds,
                aspect_ratio=bot.video_aspect_ratio,
            )
    finally:
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

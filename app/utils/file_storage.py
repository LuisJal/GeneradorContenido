from datetime import datetime
from pathlib import Path

from app.config import settings


def get_video_path(bot_slug: str, content_id: int, extension: str = "mp4") -> Path:
    """Get local file path for a generated video."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    directory = settings.videos_dir / bot_slug / date_str
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"content_{content_id}.{extension}"


def get_audio_path(bot_slug: str, content_id: int, extension: str = "mp3") -> Path:
    """Get local file path for TTS audio output."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    directory = settings.storage_dir / "audio" / bot_slug / date_str
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"content_{content_id}.{extension}"


def get_video_url(bot_slug: str, content_id: int, extension: str = "mp4") -> str:
    """Get public URL for a generated video (served by FastAPI)."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    return (
        f"{settings.app_base_url}/storage/videos"
        f"/{bot_slug}/{date_str}/content_{content_id}.{extension}"
    )

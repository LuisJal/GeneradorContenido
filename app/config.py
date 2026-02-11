from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    app_env: str = "development"
    app_secret_key: str = "change-me"
    app_base_url: str = "http://localhost:8000"
    database_url: str = f"sqlite+aiosqlite:///{BASE_DIR / 'generador.db'}"

    # Encryption
    encryption_key: str = "change-me"

    # Telegram
    telegram_bot_token: str = ""

    # Google Cloud (Veo 3)
    google_cloud_project: str = ""
    google_application_credentials: str = ""

    # Gemini
    gemini_api_key: str = ""

    # Kling
    kling_api_key: str = ""

    # Logging
    log_level: str = "INFO"

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"

    @property
    def storage_dir(self) -> Path:
        return BASE_DIR / "storage"

    @property
    def videos_dir(self) -> Path:
        path = self.storage_dir / "videos"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def thumbnails_dir(self) -> Path:
        path = self.storage_dir / "thumbnails"
        path.mkdir(parents=True, exist_ok=True)
        return path


settings = Settings()

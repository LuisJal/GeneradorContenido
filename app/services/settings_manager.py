"""Global settings manager -- CRUD for shared API keys stored in DB."""
from __future__ import annotations

from typing import Dict, Optional

from sqlalchemy.orm import Session

from app.models.global_setting import GlobalSetting
from app.utils.encryption import FieldEncryptor
from app.utils.logging_config import get_logger

logger = get_logger(__name__)

# Keys that must be stored encrypted
ENCRYPTED_KEYS = {
    "gemini_api_key",
    "kling_api_key",
    "telegram_bot_token",
}

# All known settings with Spanish descriptions
SETTING_DEFINITIONS: Dict[str, str] = {
    "gemini_api_key": "Clave API de Gemini (genera guiones y descripciones)",
    "google_cloud_project": "ID del proyecto Google Cloud (para Veo 3)",
    "google_application_credentials": "Ruta al archivo service account JSON (para Veo 3)",
    "kling_api_key": "Clave API de Kling 3.0 (proveedor de video alternativo)",
    "telegram_bot_token": "Token del bot de Telegram (notificaciones opcionales)",
}


def _get_encryptor() -> FieldEncryptor:
    from app.config import settings
    return FieldEncryptor(settings.encryption_key)


def get_setting(db: Session, key: str) -> str:
    """Get a decrypted setting value, falling back to .env."""
    row = db.query(GlobalSetting).filter(GlobalSetting.key == key).first()
    if row and row.value:
        if row.is_encrypted:
            return _get_encryptor().decrypt(row.value)
        return row.value
    # Fallback to .env
    from app.config import settings
    env_val = getattr(settings, key, "")
    if env_val and not env_val.startswith("PEGA-AQUI"):
        return env_val
    return ""


def get_all_settings(db: Session) -> Dict[str, str]:
    """Return all settings as dict with masked values for display."""
    from app.config import settings as env_settings

    result: Dict[str, str] = {}
    for key in SETTING_DEFINITIONS:
        row = db.query(GlobalSetting).filter(GlobalSetting.key == key).first()
        if row and row.value:
            if row.is_encrypted:
                result[key] = "***configurado***"
            else:
                result[key] = row.value
        else:
            env_val = getattr(env_settings, key, "")
            if env_val and not env_val.startswith("PEGA-AQUI"):
                result[key] = "***desde .env***" if key in ENCRYPTED_KEYS else env_val
            else:
                result[key] = ""
    return result


def save_setting(db: Session, key: str, value: str) -> None:
    """Save or update a setting. Encrypts if key is sensitive."""
    if not value:
        return

    is_enc = key in ENCRYPTED_KEYS
    stored_value = _get_encryptor().encrypt(value) if is_enc else value

    row = db.query(GlobalSetting).filter(GlobalSetting.key == key).first()
    if row:
        row.value = stored_value
        row.is_encrypted = is_enc
    else:
        row = GlobalSetting(
            key=key,
            value=stored_value,
            is_encrypted=is_enc,
            description=SETTING_DEFINITIONS.get(key, ""),
        )
        db.add(row)
    db.commit()
    logger.info("Saved global setting: %s", key)

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.bot import Bot
from app.schemas.bot import BotCreate, BotUpdate
from app.utils.encryption import FieldEncryptor
from app.config import settings

TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "bot_templates"


def _get_encryptor() -> FieldEncryptor:
    return FieldEncryptor(settings.encryption_key)


def load_template(template_name: str) -> dict:
    """Load a bot template JSON file by name."""
    path = TEMPLATES_DIR / f"{template_name}.json"
    if not path.exists():
        raise ValueError(f"Template '{template_name}' not found")
    with open(path) as f:
        return json.load(f)


def create_bot(db: Session, data: BotCreate) -> Bot:
    """Create a new bot, optionally from a template."""
    # Load template defaults if specified
    template_data = {}
    if data.template:
        template_data = load_template(data.template)

    slug = Bot.generate_slug(data.name)

    # Check uniqueness
    existing = db.execute(
        select(Bot).where((Bot.slug == slug) | (Bot.name == data.name))
    ).scalar_one_or_none()
    if existing:
        raise ValueError(f"Bot with name '{data.name}' already exists")

    bot = Bot(
        name=data.name,
        slug=slug,
        niche=data.niche or template_data.get("niche", ""),
        niche_description=data.niche_description or template_data.get("niche_description", ""),
        content_style=data.content_style or template_data.get("content_style", ""),
        brand_style=data.brand_style or template_data.get("brand_style", ""),
        language=data.language or template_data.get("language", "es"),
        videos_per_day=data.videos_per_day,
        posting_schedule=data.posting_schedule.model_dump() if data.posting_schedule else template_data.get(
            "posting_schedule", {"times": ["09:00"], "timezone": "Europe/Madrid"}
        ),
        use_trends=data.use_trends,
        custom_prompts=data.custom_prompts or template_data.get("custom_prompts", []),
        video_provider=data.video_provider or template_data.get("video_provider", "veo3"),
        video_duration_seconds=data.video_duration_seconds or template_data.get("video_duration_seconds", 15),
        gemini_model=data.gemini_model or template_data.get("gemini_model", "gemini-2.5-flash"),
        telegram_chat_id=data.telegram_chat_id,
        contact_email=data.contact_email,
        script_system_prompt=data.script_system_prompt or template_data.get("script_system_prompt", ""),
        trend_sources=template_data.get("trend_sources", {}),
        character_face_url=data.character_face_url or template_data.get("character_face_url"),
        character_voice_id=data.character_voice_id or template_data.get("character_voice_id"),
        character_personality=data.character_personality or template_data.get("character_personality"),
        story_arc_enabled=data.story_arc_enabled,
        story_arc_chapters=data.story_arc_chapters,
    )

    # Encrypt API key if provided
    if data.gemini_api_key:
        enc = _get_encryptor()
        bot.gemini_api_key_encrypted = enc.encrypt(data.gemini_api_key)

    db.add(bot)
    db.commit()
    db.refresh(bot)
    return bot


def get_bot_by_slug(db: Session, slug: str) -> Optional[Bot]:
    """Get a bot by its slug."""
    return db.execute(select(Bot).where(Bot.slug == slug)).scalar_one_or_none()


def get_bot_by_id(db: Session, bot_id: int) -> Optional[Bot]:
    """Get a bot by its ID."""
    return db.execute(select(Bot).where(Bot.id == bot_id)).scalar_one_or_none()


def list_bots(db: Session) -> List[Bot]:
    """List all bots ordered by creation date."""
    return list(db.execute(select(Bot).order_by(Bot.created_at.desc())).scalars().all())


def update_bot(db: Session, slug: str, data: BotUpdate) -> Optional[Bot]:
    """Update a bot's configuration. Only updates provided fields."""
    bot = get_bot_by_slug(db, slug)
    if not bot:
        return None

    update_data = data.model_dump(exclude_unset=True)

    # Handle encrypted field separately
    if "gemini_api_key" in update_data:
        api_key = update_data.pop("gemini_api_key")
        if api_key:
            enc = _get_encryptor()
            bot.gemini_api_key_encrypted = enc.encrypt(api_key)

    # Handle posting_schedule (convert Pydantic model to dict if needed)
    if "posting_schedule" in update_data and update_data["posting_schedule"] is not None:
        ps = update_data["posting_schedule"]
        if not isinstance(ps, dict):
            update_data["posting_schedule"] = ps.model_dump()

    for field, value in update_data.items():
        if value is not None and hasattr(bot, field):
            setattr(bot, field, value)

    db.commit()
    db.refresh(bot)
    return bot


def toggle_bot(db: Session, slug: str) -> Optional[Bot]:
    """Toggle a bot's enabled state."""
    bot = get_bot_by_slug(db, slug)
    if not bot:
        return None
    bot.is_enabled = not bot.is_enabled
    db.commit()
    db.refresh(bot)
    return bot


def delete_bot(db: Session, slug: str) -> bool:
    """Delete a bot and all associated data (cascade)."""
    bot = get_bot_by_slug(db, slug)
    if not bot:
        return False
    db.delete(bot)
    db.commit()
    return True

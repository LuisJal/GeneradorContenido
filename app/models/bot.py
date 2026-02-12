from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base

if TYPE_CHECKING:
    from app.models.content import ContentItem
    from app.models.credential import SocialCredential
    from app.models.log_entry import PipelineLog


def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"[-\s]+", "-", text)


class Bot(Base):
    __tablename__ = "bots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    niche: Mapped[str] = mapped_column(String(100), nullable=False)
    niche_description: Mapped[str] = mapped_column(Text, default="")
    content_style: Mapped[str] = mapped_column(Text, default="")
    language: Mapped[str] = mapped_column(String(10), default="es")
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    videos_per_day: Mapped[int] = mapped_column(Integer, default=1)
    posting_schedule: Mapped[Optional[dict]] = mapped_column(
        JSON, default=lambda: {"times": ["09:00"], "timezone": "Europe/Madrid"}
    )
    use_trends: Mapped[bool] = mapped_column(Boolean, default=True)
    custom_prompts: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    video_provider: Mapped[str] = mapped_column(String(20), default="veo3")
    video_duration_seconds: Mapped[int] = mapped_column(Integer, default=15)
    video_aspect_ratio: Mapped[str] = mapped_column(String(10), default="9:16")
    gemini_api_key_encrypted: Mapped[Optional[str]] = mapped_column(
        "gemini_api_key", Text, nullable=True
    )
    gemini_model: Mapped[str] = mapped_column(String(50), default="gemini-2.5-flash")
    telegram_chat_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    contact_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    script_system_prompt: Mapped[str] = mapped_column(Text, default="")
    brand_style: Mapped[str] = mapped_column(Text, default="")
    trend_sources: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)

    # Character (talking-head bots)
    character_face_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    character_voice_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    character_personality: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Story arc
    story_arc_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    story_arc_chapters: Mapped[int] = mapped_column(Integer, default=3)

    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    credentials: Mapped[List["SocialCredential"]] = relationship(
        back_populates="bot", cascade="all, delete-orphan"
    )
    content_items: Mapped[List["ContentItem"]] = relationship(
        back_populates="bot", cascade="all, delete-orphan"
    )
    logs: Mapped[List["PipelineLog"]] = relationship(
        back_populates="bot", cascade="all, delete-orphan"
    )

    @staticmethod
    def generate_slug(name: str) -> str:
        return _slugify(name)

    def __repr__(self) -> str:
        return f"<Bot(id={self.id}, name='{self.name}', niche='{self.niche}')>"

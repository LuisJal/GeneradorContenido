from __future__ import annotations

from datetime import datetime
from enum import Enum as PyEnum
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base

if TYPE_CHECKING:
    from app.models.bot import Bot
    from app.models.log_entry import PipelineLog


class ContentStatus(str, PyEnum):
    TREND_SCRAPING = "trend_scraping"
    SCRIPT_GENERATING = "script_generating"
    SCRIPT_READY = "script_ready"
    VIDEO_GENERATING = "video_generating"
    VIDEO_POLLING = "video_polling"
    VIDEO_READY = "video_ready"
    DESCRIPTIONS_GENERATING = "descriptions_generating"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    PARTIALLY_PUBLISHED = "partially_published"
    FAILED = "failed"


class ContentItem(Base):
    __tablename__ = "content_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id"), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), default=ContentStatus.TREND_SCRAPING.value, nullable=False
    )

    # Topic
    trend_topic: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    custom_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Script
    script: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    script_model: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    video_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Video
    video_provider: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    video_task_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    video_file_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    video_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    video_duration: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Descriptions
    description_instagram: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description_youtube: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description_tiktok: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Telegram approval
    telegram_message_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    approval_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    approved_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Publishing
    publish_instagram_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    publish_youtube_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    publish_tiktok_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    publish_instagram_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    publish_youtube_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    publish_tiktok_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Error handling
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)

    # Timestamps
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now()
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relationships
    bot: Mapped["Bot"] = relationship(back_populates="content_items")
    logs: Mapped[List["PipelineLog"]] = relationship(
        back_populates="content", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<ContentItem(id={self.id}, bot_id={self.bot_id}, status='{self.status}')>"

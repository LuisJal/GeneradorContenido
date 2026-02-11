from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base

if TYPE_CHECKING:
    from app.models.bot import Bot
    from app.models.content import ContentItem


class PipelineLog(Base):
    __tablename__ = "pipeline_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id"), nullable=False)
    content_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("content_items.id"), nullable=True
    )
    level: Mapped[str] = mapped_column(String(10), default="INFO")
    stage: Mapped[str] = mapped_column(String(50), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    extra_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now()
    )

    # Relationships
    bot: Mapped["Bot"] = relationship(back_populates="logs")
    content: Mapped[Optional["ContentItem"]] = relationship(back_populates="logs")

    def __repr__(self) -> str:
        return f"<PipelineLog(id={self.id}, level='{self.level}', stage='{self.stage}')>"

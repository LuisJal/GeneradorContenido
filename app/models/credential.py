from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base

if TYPE_CHECKING:
    from app.models.bot import Bot


class SocialCredential(Base):
    __tablename__ = "social_credentials"
    __table_args__ = (
        UniqueConstraint("bot_id", "platform", name="uq_bot_platform"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id"), nullable=False)
    platform: Mapped[str] = mapped_column(String(20), nullable=False)

    # Tokens (stored encrypted)
    access_token_encrypted: Mapped[Optional[str]] = mapped_column(
        "access_token", Text, nullable=True
    )
    refresh_token_encrypted: Mapped[Optional[str]] = mapped_column(
        "refresh_token", Text, nullable=True
    )
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Platform identifiers
    platform_user_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    platform_username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    extra_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    bot: Mapped["Bot"] = relationship(back_populates="credentials")

    def __repr__(self) -> str:
        return f"<SocialCredential(id={self.id}, bot_id={self.bot_id}, platform='{self.platform}')>"

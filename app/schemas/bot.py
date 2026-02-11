from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class PostingSchedule(BaseModel):
    times: List[str] = Field(default=["09:00"])
    timezone: str = Field(default="Europe/Madrid")


class BotCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    niche: str = Field(..., min_length=1, max_length=100)
    niche_description: str = ""
    content_style: str = ""
    language: str = "es"
    videos_per_day: int = Field(default=1, ge=1, le=10)
    posting_schedule: PostingSchedule = Field(default_factory=PostingSchedule)
    use_trends: bool = True
    custom_prompts: List[str] = Field(default_factory=list)
    video_provider: str = Field(default="veo3", pattern="^(veo3|kling3)$")
    video_duration_seconds: int = Field(default=15, ge=5, le=60)
    gemini_api_key: Optional[str] = None
    gemini_model: str = "gemini-2.5-flash"
    telegram_chat_id: Optional[str] = None
    contact_email: Optional[str] = None
    script_system_prompt: str = ""
    template: Optional[str] = None


class BotUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    niche: Optional[str] = None
    niche_description: Optional[str] = None
    content_style: Optional[str] = None
    language: Optional[str] = None
    is_enabled: Optional[bool] = None
    videos_per_day: Optional[int] = Field(default=None, ge=1, le=10)
    posting_schedule: Optional[PostingSchedule] = None
    use_trends: Optional[bool] = None
    custom_prompts: Optional[List[str]] = None
    video_provider: Optional[str] = Field(default=None, pattern="^(veo3|kling3)$")
    video_duration_seconds: Optional[int] = Field(default=None, ge=5, le=60)
    gemini_api_key: Optional[str] = None
    gemini_model: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    contact_email: Optional[str] = None
    script_system_prompt: Optional[str] = None


class BotResponse(BaseModel):
    id: int
    name: str
    slug: str
    niche: str
    niche_description: str
    content_style: str
    language: str
    is_enabled: bool
    videos_per_day: int
    posting_schedule: dict
    use_trends: bool
    custom_prompts: list
    video_provider: str
    video_duration_seconds: int
    gemini_model: str
    telegram_chat_id: Optional[str]
    contact_email: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

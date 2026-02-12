from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class CharacterSpec(BaseModel):
    """Specification for a character in the production."""

    name: str = ""
    role: str = Field(
        default="protagonist",
        pattern="^(protagonist|antagonist|supporting|narrator)$",
    )
    visual_description: str = ""
    personality: str = ""
    voice_id: Optional[str] = None
    face_url: Optional[str] = None
    clothing: Optional[str] = None
    distinguishing_features: Optional[str] = None


class TechnicalSpecs(BaseModel):
    """Technical specifications for video production."""

    style: str = ""  # "anime", "photorealistic", "3D animation"
    color_palette: str = ""
    camera_style: str = ""


class MusicSpec(BaseModel):
    """Music and audio specifications."""

    style: str = ""
    mood: str = ""
    bpm_range: str = ""


class ProductionConfig(BaseModel):
    """Full production configuration stored as JSON on the Bot."""

    characters: List[CharacterSpec] = Field(default_factory=list)
    setting: str = ""
    technical: TechnicalSpecs = Field(default_factory=TechnicalSpecs)
    music: MusicSpec = Field(default_factory=MusicSpec)
    content_rules: str = ""

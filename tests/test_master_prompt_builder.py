"""Tests for the master prompt builder module."""
from unittest.mock import MagicMock

from app.services.master_prompt_builder import build_master_system_prompt


def _make_bot(**kwargs):
    """Create a mock Bot with defaults for testing."""
    defaults = dict(
        id=1, name="Test", slug="test", niche="test-niche",
        niche_description="Test niche desc", content_style="Fun and casual",
        brand_style="Bright colors", language="es", video_duration_seconds=30,
        video_aspect_ratio="9:16", script_system_prompt="",
        character_personality="", production_mode="standard",
        production_config={}, video_provider="veo3",
    )
    defaults.update(kwargs)
    bot = MagicMock()
    for k, v in defaults.items():
        setattr(bot, k, v)
    return bot


def test_standard_mode_no_output_instructions():
    """Standard mode should not include storyboard/talking_head instructions."""
    bot = _make_bot(production_mode="standard")
    prompt = build_master_system_prompt(bot)
    assert "STORYBOARD" not in prompt
    assert "TALKING HEAD" not in prompt
    assert "test-niche" in prompt


def test_storyboard_mode_includes_output_format():
    """Storyboard mode should include storyboard output instructions."""
    bot = _make_bot(production_mode="storyboard")
    prompt = build_master_system_prompt(bot)
    assert "STORYBOARD PRODUCTION DOCUMENT" in prompt
    assert "timestamp" in prompt


def test_talking_head_mode_includes_output_format():
    """Talking head mode should include dialogue-focused instructions."""
    bot = _make_bot(production_mode="talking_head")
    prompt = build_master_system_prompt(bot)
    assert "TALKING HEAD PRODUCTION DOCUMENT" in prompt
    assert "dialogue_full" in prompt


def test_characters_from_production_config():
    """Characters from production_config should appear in the prompt."""
    config = {
        "characters": [
            {
                "name": "KAIRO",
                "role": "protagonist",
                "visual_description": "Blue-haired anime boy",
                "personality": "Determined and silent",
                "clothing": "Dark armor with neon lines",
                "distinguishing_features": "Glowing blue eyes",
            },
            {
                "name": "NOX",
                "role": "antagonist",
                "visual_description": "Red cosmic entity",
            },
        ],
        "setting": "Destroyed futuristic city",
        "technical": {
            "style": "anime",
            "color_palette": "Neon vibrant with dark contrast",
            "camera_style": "Dynamic anime cinematographic",
        },
        "music": {"style": "Epic orchestral", "mood": "intense", "bpm_range": "130-150"},
        "content_rules": "Never break the fourth wall",
    }
    bot = _make_bot(production_mode="storyboard", production_config=config)
    prompt = build_master_system_prompt(bot)

    assert "KAIRO" in prompt
    assert "NOX" in prompt
    assert "Blue-haired anime boy" in prompt
    assert "Destroyed futuristic city" in prompt
    assert "anime" in prompt
    assert "Epic orchestral" in prompt
    assert "Never break the fourth wall" in prompt


def test_fallback_to_character_personality():
    """When no production_config characters, fall back to character_personality."""
    bot = _make_bot(
        production_mode="talking_head",
        production_config={},
        character_personality="Sassy Madrid girl",
    )
    prompt = build_master_system_prompt(bot)
    assert "Sassy Madrid girl" in prompt


def test_script_system_prompt_takes_precedence():
    """Custom script_system_prompt should be used as identity base."""
    bot = _make_bot(
        production_mode="storyboard",
        script_system_prompt="You are a comedy director.",
        production_config={"characters": [{"name": "Paco"}]},
    )
    prompt = build_master_system_prompt(bot)
    assert "You are a comedy director." in prompt
    assert "Paco" in prompt


def test_technical_constraints_always_present():
    """Duration, language, aspect ratio should always appear."""
    bot = _make_bot(production_mode="storyboard", language="en", video_duration_seconds=15)
    prompt = build_master_system_prompt(bot)
    assert "en" in prompt
    assert "15 seconds" in prompt
    assert "9:16" in prompt


def test_empty_config_produces_generic_prompt():
    """A bot with no production_config should still produce a valid prompt."""
    bot = _make_bot(
        production_mode="storyboard",
        production_config={},
        script_system_prompt="",
        character_personality="",
        brand_style="",
    )
    prompt = build_master_system_prompt(bot)
    assert "production director" in prompt
    assert "STORYBOARD" in prompt

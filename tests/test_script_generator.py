"""Tests for the script_generator service -- mocks GeminiClient entirely."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from cryptography.fernet import Fernet

from app.integrations.gemini_client import GeminiClientError
from app.services.script_generator import (
    _build_system_prompt,
    _resolve_api_key,
    generate_content_descriptions,
    generate_content_script,
    generate_video_prompt,
)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_bot(**overrides) -> MagicMock:
    """Create a fake Bot object with default fields."""
    bot = MagicMock()
    bot.name = overrides.get("name", "TestBot")
    bot.niche = overrides.get("niche", "fitness")
    bot.niche_description = overrides.get("niche_description", "Fitness tips")
    bot.content_style = overrides.get("content_style", "motivational")
    bot.language = overrides.get("language", "es")
    bot.video_duration_seconds = overrides.get("video_duration_seconds", 15)
    bot.gemini_api_key_encrypted = overrides.get("gemini_api_key_encrypted", None)
    bot.gemini_model = overrides.get("gemini_model", "gemini-2.5-flash")
    bot.script_system_prompt = overrides.get("script_system_prompt", "")
    return bot


# ------------------------------------------------------------------
# _resolve_api_key
# ------------------------------------------------------------------


def test_resolve_api_key_uses_global_when_no_bot_key():
    """Falls back to settings.gemini_api_key when bot has no key."""
    bot = _make_bot(gemini_api_key_encrypted=None)

    with patch("app.services.script_generator.settings") as mock_settings:
        mock_settings.gemini_api_key = "global-key"
        mock_settings.encryption_key = Fernet.generate_key().decode()
        result = _resolve_api_key(bot)

    assert result == "global-key"


def test_resolve_api_key_raises_when_no_key():
    """Should raise GeminiClientError if no key is available anywhere."""
    bot = _make_bot(gemini_api_key_encrypted=None)

    with patch("app.services.script_generator.settings") as mock_settings:
        mock_settings.gemini_api_key = ""
        mock_settings.encryption_key = Fernet.generate_key().decode()

        with pytest.raises(GeminiClientError, match="No Gemini API key"):
            _resolve_api_key(bot)


def test_resolve_api_key_decrypts_bot_key():
    """Should decrypt and return the per-bot encrypted key."""
    key = Fernet.generate_key().decode()
    fernet = Fernet(key.encode())
    encrypted = fernet.encrypt(b"bot-specific-key").decode()

    bot = _make_bot(gemini_api_key_encrypted=encrypted)

    with patch("app.services.script_generator.settings") as mock_settings:
        mock_settings.encryption_key = key
        mock_settings.gemini_api_key = "global-key"
        result = _resolve_api_key(bot)

    assert result == "bot-specific-key"


# ------------------------------------------------------------------
# _build_system_prompt
# ------------------------------------------------------------------


def test_build_system_prompt_default():
    """Default prompt includes niche, style, language, duration."""
    bot = _make_bot()
    prompt = _build_system_prompt(bot)

    assert "fitness" in prompt
    assert "motivational" in prompt
    assert "es" in prompt
    assert "15" in prompt


def test_build_system_prompt_custom():
    """Custom script_system_prompt should replace the default base."""
    bot = _make_bot(script_system_prompt="You are a cooking expert.")
    prompt = _build_system_prompt(bot)

    assert "cooking expert" in prompt
    assert "short-form video" not in prompt  # default not present


# ------------------------------------------------------------------
# Async service functions (mock GeminiClient)
# ------------------------------------------------------------------


@pytest.fixture
def mock_client():
    """Patch _get_client in script_generator to return a mock GeminiClient."""
    with patch("app.services.script_generator._get_client") as factory:
        mock = MagicMock()
        factory.return_value = mock
        yield mock


def test_generate_content_script(mock_client):
    """Should call generate_script on the client and return the dict."""
    script_data = {"hook": "H", "body": "B", "cta": "C", "visual_cues": []}
    mock_client.generate_script.return_value = script_data

    bot = _make_bot()
    result = asyncio.get_event_loop().run_until_complete(
        generate_content_script(bot, "fitness topic")
    )

    assert result == script_data
    mock_client.generate_script.assert_called_once()


def test_generate_content_descriptions(mock_client):
    """Should call generate_descriptions on the client and return the dict."""
    desc_data = {
        "instagram": "IG caption",
        "youtube": {"title": "T", "description": "D", "tags": []},
        "tiktok": "TT caption",
    }
    mock_client.generate_descriptions.return_value = desc_data

    bot = _make_bot()
    result = asyncio.get_event_loop().run_until_complete(
        generate_content_descriptions(bot, {"hook": "h"}, "topic")
    )

    assert result == desc_data


def test_generate_video_prompt_service(mock_client):
    """Should call generate_video_prompt on the client and return a string."""
    mock_client.generate_video_prompt.return_value = "A cinematic scene..."

    bot = _make_bot()
    result = asyncio.get_event_loop().run_until_complete(
        generate_video_prompt(bot, {"hook": "h"})
    )

    assert "cinematic" in result

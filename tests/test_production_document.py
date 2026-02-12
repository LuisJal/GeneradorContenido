"""Tests for production document generation and pipeline integration."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.integrations.gemini_client import GeminiClient, GeminiClientError


def _make_bot(**kwargs):
    """Create a mock Bot with defaults for testing."""
    defaults = dict(
        id=1, name="TestBot", slug="test-bot", niche="anime",
        niche_description="Anime content", content_style="Epic",
        brand_style="Neon vibrant", language="es",
        video_duration_seconds=30, video_aspect_ratio="9:16",
        script_system_prompt="", character_personality="",
        character_face_url=None, character_voice_id=None,
        production_mode="storyboard", production_config={
            "characters": [{"name": "KAIRO", "role": "protagonist"}],
        },
        video_provider="veo3", gemini_api_key_encrypted=None,
        gemini_model="gemini-2.5-flash", use_trends=False,
        custom_prompts=["Epic anime battle"],
        is_enabled=True, story_arc_enabled=False, story_arc_chapters=3,
        posting_schedule={"times": ["09:00"], "timezone": "UTC"},
        trend_sources={},
    )
    defaults.update(kwargs)
    bot = MagicMock()
    for k, v in defaults.items():
        setattr(bot, k, v)
    return bot


SAMPLE_STORYBOARD_DOC = {
    "title": "The Awakening",
    "characters": [
        {"name": "KAIRO", "description": "Blue-haired anime protagonist"},
    ],
    "storyboard": [
        {
            "timestamp": "0:00-0:10",
            "visual": "Stormy sky over destroyed city",
            "dialogue": "If this is the end, I will break it.",
            "music_direction": "Epic opening",
            "camera": "Descending shot",
        },
        {
            "timestamp": "0:10-0:20",
            "visual": "Cosmic portal opens",
            "dialogue": "",
            "music_direction": "Intensity builds",
            "camera": "360 rotation",
        },
        {
            "timestamp": "0:20-0:30",
            "visual": "Energy clash explosion",
            "dialogue": "I'm not done yet.",
            "music_direction": "Climax drop",
            "camera": "Slow motion",
        },
    ],
    "music_description": "Epic orchestral, 130 BPM",
    "video_prompt": "30-second vertical video. A blue-haired anime protagonist...",
    "dialogue_full": "If this is the end, I will break it. I'm not done yet.",
    "hook": "If this is the end...",
    "cta": "Follow for Part 2",
}

SAMPLE_TALKING_HEAD_DOC = {
    "title": "Madrid Reaction",
    "storyboard": [
        {
            "timestamp": "0:00-0:10",
            "expression": "Surprised",
            "dialogue": "No os vais a creer lo que ha pasado!",
            "overlay_text": "ULTIMA HORA",
        },
        {
            "timestamp": "0:10-0:20",
            "expression": "Excited",
            "dialogue": "El Madrid acaba de fichar...",
            "overlay_text": "",
        },
    ],
    "video_prompt": "Blonde young woman speaking to camera...",
    "dialogue_full": "No os vais a creer lo que ha pasado! El Madrid acaba de fichar...",
    "hook": "No os vais a creer!",
    "cta": "Dejame en comentarios",
    "music_description": "Upbeat Spanish pop background",
}


class TestGeminiClientProductionDocument:
    """Test GeminiClient.generate_production_document."""

    def test_storyboard_mode_returns_dict(self):
        with patch("google.genai.Client") as MockClient:
            mock_response = MagicMock()
            mock_response.text = json.dumps(SAMPLE_STORYBOARD_DOC)
            MockClient.return_value.models.generate_content.return_value = mock_response

            client = GeminiClient(api_key="test-key")
            result = client.generate_production_document(
                "system prompt", "user prompt", mode="storyboard"
            )

            assert result["title"] == "The Awakening"
            assert len(result["storyboard"]) == 3
            assert result["video_prompt"].startswith("30-second")
            assert "end" in result["dialogue_full"]

    def test_talking_head_mode_returns_dict(self):
        with patch("google.genai.Client") as MockClient:
            mock_response = MagicMock()
            mock_response.text = json.dumps(SAMPLE_TALKING_HEAD_DOC)
            MockClient.return_value.models.generate_content.return_value = mock_response

            client = GeminiClient(api_key="test-key")
            result = client.generate_production_document(
                "system prompt", "user prompt", mode="talking_head"
            )

            assert result["title"] == "Madrid Reaction"
            assert len(result["storyboard"]) == 2
            assert "creer" in result["dialogue_full"]

    def test_empty_response_raises_error(self):
        with patch("google.genai.Client") as MockClient:
            mock_response = MagicMock()
            mock_response.text = ""
            MockClient.return_value.models.generate_content.return_value = mock_response

            client = GeminiClient(api_key="test-key")
            with pytest.raises(GeminiClientError, match="empty response"):
                client.generate_production_document("s", "u")

    def test_invalid_json_raises_error(self):
        with patch("google.genai.Client") as MockClient:
            mock_response = MagicMock()
            mock_response.text = "not json"
            MockClient.return_value.models.generate_content.return_value = mock_response

            client = GeminiClient(api_key="test-key")
            with pytest.raises(GeminiClientError, match="Invalid JSON"):
                client.generate_production_document("s", "u")


class TestScriptGeneratorProductionDocument:
    """Test script_generator.generate_production_document."""

    @pytest.mark.asyncio
    async def test_calls_master_prompt_builder(self):
        bot = _make_bot()

        with patch("app.services.script_generator._resolve_api_key", return_value="key"), \
             patch("app.integrations.gemini_client.GeminiClient.generate_production_document",
                   return_value=SAMPLE_STORYBOARD_DOC) as mock_gen, \
             patch("app.services.master_prompt_builder.build_master_system_prompt",
                   return_value="master prompt") as mock_builder:

            from app.services.script_generator import generate_production_document
            result = await generate_production_document(bot, "epic battle")

            mock_builder.assert_called_once_with(bot)
            assert mock_gen.called
            assert result["title"] == "The Awakening"

    @pytest.mark.asyncio
    async def test_talking_head_mode_passes_mode(self):
        bot = _make_bot(production_mode="talking_head")

        with patch("app.services.script_generator._resolve_api_key", return_value="key"), \
             patch("app.integrations.gemini_client.GeminiClient.generate_production_document",
                   return_value=SAMPLE_TALKING_HEAD_DOC) as mock_gen:

            from app.services.script_generator import generate_production_document
            result = await generate_production_document(bot, "madrid news")

            # Check mode was passed as talking_head
            call_args = mock_gen.call_args
            assert call_args[0][2] == "talking_head" or call_args[1].get("mode") == "talking_head"
            assert result["title"] == "Madrid Reaction"


class TestProductionConfigSync:
    """Test that production_config syncs to legacy fields."""

    def test_sync_first_character_to_legacy(self):
        from app.services.bot_manager import _sync_production_config_to_legacy

        bot = MagicMock()
        bot.character_face_url = None
        bot.character_voice_id = None
        bot.character_personality = None
        bot.production_config = {
            "characters": [
                {
                    "name": "TestChar",
                    "face_url": "https://example.com/face.png",
                    "voice_id": "voice123",
                    "personality": "Bold and brave",
                },
            ],
        }

        _sync_production_config_to_legacy(bot)

        assert bot.character_face_url == "https://example.com/face.png"
        assert bot.character_voice_id == "voice123"
        assert bot.character_personality == "Bold and brave"

    def test_sync_no_characters_is_noop(self):
        from app.services.bot_manager import _sync_production_config_to_legacy

        bot = MagicMock()
        bot.character_face_url = "original"
        bot.character_voice_id = None
        bot.character_personality = None
        bot.production_config = {"characters": []}

        _sync_production_config_to_legacy(bot)

        assert bot.character_face_url == "original"

    def test_sync_empty_config_is_noop(self):
        from app.services.bot_manager import _sync_production_config_to_legacy

        bot = MagicMock()
        bot.character_face_url = None
        bot.character_voice_id = None
        bot.character_personality = None
        bot.production_config = None

        _sync_production_config_to_legacy(bot)
        assert bot.character_face_url is None


class TestProductionConfigSchema:
    """Test the ProductionConfig Pydantic schema."""

    def test_valid_config(self):
        from app.schemas.production import ProductionConfig

        config = ProductionConfig(
            characters=[{"name": "Test", "role": "protagonist"}],
            setting="A dark forest",
            technical={"style": "anime"},
            music={"style": "lo-fi"},
            content_rules="Be kind",
        )
        assert len(config.characters) == 1
        assert config.setting == "A dark forest"

    def test_empty_config(self):
        from app.schemas.production import ProductionConfig

        config = ProductionConfig()
        assert config.characters == []
        assert config.setting == ""

    def test_character_spec_defaults(self):
        from app.schemas.production import CharacterSpec

        char = CharacterSpec(name="Hero")
        assert char.role == "protagonist"
        assert char.face_url is None

"""Tests for GeminiClient -- mock the google-genai SDK to avoid real API calls."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.integrations.gemini_client import GeminiClient, GeminiClientError


@pytest.fixture
def mock_genai():
    """Patch google.genai.Client so no real API call is made."""
    with patch("app.integrations.gemini_client.genai.Client") as mock_cls:
        yield mock_cls


def _make_response(text: str) -> MagicMock:
    """Build a fake genai response object."""
    resp = MagicMock()
    resp.text = text
    return resp


# ------------------------------------------------------------------
# generate_script
# ------------------------------------------------------------------


def test_generate_script_success(mock_genai):
    """Valid JSON from Gemini should be returned as a dict."""
    script_data = {
        "hook": "Did you know?",
        "body": "Some body text",
        "cta": "Follow for more!",
        "visual_cues": ["Close up shot", "Text overlay"],
    }
    mock_genai.return_value.models.generate_content.return_value = _make_response(
        json.dumps(script_data)
    )

    client = GeminiClient(api_key="fake-key", model="gemini-test")
    result = client.generate_script("system prompt", "user prompt")

    assert result == script_data
    mock_genai.return_value.models.generate_content.assert_called_once()


def test_generate_script_empty_response(mock_genai):
    """Empty response text should raise GeminiClientError."""
    mock_genai.return_value.models.generate_content.return_value = _make_response("")

    client = GeminiClient(api_key="fake-key")
    with pytest.raises(GeminiClientError, match="empty response"):
        client.generate_script("sys", "user")


def test_generate_script_invalid_json(mock_genai):
    """Non-JSON response should raise GeminiClientError."""
    mock_genai.return_value.models.generate_content.return_value = _make_response(
        "not valid json {{"
    )

    client = GeminiClient(api_key="fake-key")
    with pytest.raises(GeminiClientError, match="Invalid JSON"):
        client.generate_script("sys", "user")


# ------------------------------------------------------------------
# generate_video_prompt
# ------------------------------------------------------------------


def test_generate_video_prompt_success(mock_genai):
    """Should return the raw text from Gemini."""
    mock_genai.return_value.models.generate_content.return_value = _make_response(
        "A cinematic close-up of a person running at sunset."
    )

    client = GeminiClient(api_key="fake-key")
    prompt = client.generate_video_prompt(
        {"hook": "h", "body": "b", "cta": "c", "visual_cues": []}
    )

    assert "cinematic" in prompt


def test_generate_video_prompt_empty(mock_genai):
    """Empty prompt should raise GeminiClientError."""
    mock_genai.return_value.models.generate_content.return_value = _make_response("")

    client = GeminiClient(api_key="fake-key")
    with pytest.raises(GeminiClientError, match="empty video prompt"):
        client.generate_video_prompt({"hook": "h", "body": "b", "cta": "c", "visual_cues": []})


# ------------------------------------------------------------------
# generate_descriptions
# ------------------------------------------------------------------


def test_generate_descriptions_success(mock_genai):
    """Valid description JSON should be parsed and returned."""
    desc_data = {
        "instagram": "Check this out! #fitness",
        "youtube": {
            "title": "Best Workout Ever",
            "description": "Full description here",
            "tags": ["fitness", "workout"],
        },
        "tiktok": "Quick fit tip! #fyp",
    }
    mock_genai.return_value.models.generate_content.return_value = _make_response(
        json.dumps(desc_data)
    )

    client = GeminiClient(api_key="fake-key")
    result = client.generate_descriptions(
        script={"hook": "h", "body": "b", "cta": "c"},
        topic="fitness tips",
        niche="fitness",
    )

    assert result["instagram"] == desc_data["instagram"]
    assert result["youtube"]["title"] == "Best Workout Ever"
    assert result["tiktok"] == desc_data["tiktok"]


def test_generate_descriptions_truncates_long_captions(mock_genai):
    """Instagram and TikTok captions over 2200 chars should be truncated."""
    long_text = "A" * 3000
    desc_data = {
        "instagram": long_text,
        "youtube": {"title": "T", "description": "D", "tags": []},
        "tiktok": long_text,
    }
    mock_genai.return_value.models.generate_content.return_value = _make_response(
        json.dumps(desc_data)
    )

    client = GeminiClient(api_key="fake-key")
    result = client.generate_descriptions(
        script={"hook": "h", "body": "b", "cta": "c"},
        topic="topic",
        niche="niche",
    )

    assert len(result["instagram"]) == 2200
    assert len(result["tiktok"]) == 2200

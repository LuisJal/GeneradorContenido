"""Tests for video_generator service -- strategy pattern and provider selection."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.integrations.veo_client import (
    Veo3Client,
    _EXTENSION_SECONDS,
    _MAX_SINGLE_DURATION,
)
from app.services.video_generator import (
    _get_client,
    check_video_status,
    download_video,
    submit_video_generation,
)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_bot(provider: str = "veo3") -> MagicMock:
    """Create a fake Bot with video-related fields."""
    bot = MagicMock()
    bot.video_provider = provider
    bot.video_duration_seconds = 15
    bot.video_aspect_ratio = "9:16"
    bot.slug = "testbot"
    bot.gemini_api_key_encrypted = None
    return bot


def _mock_get_setting(values: dict):
    """Return a side_effect function for get_setting that reads from dict."""
    def _side_effect(db, key):
        return values.get(key, "")
    return _side_effect


# ------------------------------------------------------------------
# Strategy pattern: provider selection
# ------------------------------------------------------------------


def test_get_client_veo3_with_api_key():
    """provider='veo3' with gemini_api_key should use api_key mode."""
    bot = _make_bot("veo3")

    with patch("app.services.video_generator._settings_db_session") as mock_db:
        mock_db.return_value = MagicMock()
        with patch("app.services.video_generator.settings") as mock_settings:
            mock_settings.encryption_key = "fake"
            with patch(
                "app.services.settings_manager.get_setting",
                side_effect=_mock_get_setting({"gemini_api_key": "test-gemini-key"}),
            ):
                with patch("app.services.video_generator.Veo3Client") as veo_cls:
                    _get_client(bot)
                    veo_cls.assert_called_once_with(api_key="test-gemini-key")


def test_get_client_veo3_with_project():
    """provider='veo3' without API key should fall back to Vertex AI."""
    bot = _make_bot("veo3")

    with patch("app.services.video_generator._settings_db_session") as mock_db:
        mock_db.return_value = MagicMock()
        with patch("app.services.video_generator.settings") as mock_settings:
            mock_settings.encryption_key = ""
            with patch(
                "app.services.settings_manager.get_setting",
                side_effect=_mock_get_setting({
                    "gemini_api_key": "",
                    "google_cloud_project": "my-project",
                }),
            ):
                with patch("app.services.video_generator.Veo3Client") as veo_cls:
                    _get_client(bot)
                    veo_cls.assert_called_once_with(project_id="my-project")


def test_get_client_kling3():
    """provider='kling3' with access_key+secret_key should use JWT auth."""
    bot = _make_bot("kling3")

    with patch("app.services.video_generator._settings_db_session") as mock_db:
        mock_db.return_value = MagicMock()
        with patch(
            "app.services.settings_manager.get_setting",
            side_effect=_mock_get_setting({
                "kling_access_key": "ak-123",
                "kling_secret_key": "sk-456",
            }),
        ):
            with patch("app.services.video_generator.KlingClient") as kling_cls:
                _get_client(bot)
                kling_cls.assert_called_once_with(access_key="ak-123", secret_key="sk-456")


def test_get_client_kling3_legacy():
    """provider='kling3' without access/secret should fall back to legacy api_key."""
    bot = _make_bot("kling3")

    with patch("app.services.video_generator._settings_db_session") as mock_db:
        mock_db.return_value = MagicMock()
        with patch("app.services.video_generator.settings") as mock_settings:
            mock_settings.kling_api_key = "legacy-key"
            with patch(
                "app.services.settings_manager.get_setting",
                side_effect=_mock_get_setting({}),
            ):
                with patch("app.services.video_generator.KlingClient") as kling_cls:
                    _get_client(bot)
                    kling_cls.assert_called_once_with(api_key="legacy-key")


def test_get_client_unsupported():
    """Unknown provider should raise ValueError."""
    bot = _make_bot("dalle")
    with pytest.raises(ValueError, match="Unsupported video provider"):
        _get_client(bot)


def test_get_client_veo3_no_credentials():
    """Missing both API key and project should raise ValueError."""
    bot = _make_bot("veo3")

    with patch("app.services.video_generator._settings_db_session") as mock_db:
        mock_db.return_value = MagicMock()
        with patch("app.services.video_generator.settings") as mock_settings:
            mock_settings.encryption_key = ""
            with patch(
                "app.services.settings_manager.get_setting",
                return_value="",
            ):
                with pytest.raises(ValueError, match="credentials"):
                    _get_client(bot)


def test_get_client_kling3_no_key():
    """Missing all Kling credentials should raise ValueError."""
    bot = _make_bot("kling3")

    with patch("app.services.video_generator._settings_db_session") as mock_db:
        mock_db.return_value = MagicMock()
        with patch("app.services.video_generator.settings") as mock_settings:
            mock_settings.kling_api_key = ""
            with patch(
                "app.services.settings_manager.get_setting",
                return_value="",
            ):
                with pytest.raises(ValueError, match="Kling"):
                    _get_client(bot)


# ------------------------------------------------------------------
# submit_video_generation
# ------------------------------------------------------------------


def test_submit_video_generation():
    """Should call generate_video on the chosen client and return task_id."""
    bot = _make_bot("kling3")

    mock_client = AsyncMock()
    mock_client.generate_video = AsyncMock(return_value="task-abc")
    mock_client.close = AsyncMock()

    with patch("app.services.video_generator._get_client", return_value=mock_client):
        result = asyncio.get_event_loop().run_until_complete(
            submit_video_generation(bot, "A person running", content_id=1)
        )

    assert result == "task-abc"
    mock_client.generate_video.assert_called_once_with(
        prompt="A person running",
        duration=15,
        aspect_ratio="9:16",
    )
    mock_client.close.assert_called_once()


# ------------------------------------------------------------------
# check_video_status
# ------------------------------------------------------------------


def test_check_video_status():
    """Should call poll_status on the client and return the result dict."""
    bot = _make_bot("kling3")

    mock_client = AsyncMock()
    mock_client.poll_status = AsyncMock(
        return_value={"status": "completed", "video_url": "https://cdn/video.mp4"}
    )
    mock_client.close = AsyncMock()

    with patch("app.services.video_generator._get_client", return_value=mock_client):
        result = asyncio.get_event_loop().run_until_complete(
            check_video_status(bot, "task-abc")
        )

    assert result["status"] == "completed"
    assert "video_url" in result


# ------------------------------------------------------------------
# download_video
# ------------------------------------------------------------------


def test_download_video():
    """Should call download_video on the client and return local path."""
    bot = _make_bot("kling3")

    mock_client = AsyncMock()
    mock_client.download_video = AsyncMock(return_value="/tmp/video.mp4")
    mock_client.close = AsyncMock()

    with patch("app.services.video_generator._get_client", return_value=mock_client):
        with patch("app.services.video_generator.get_video_path", return_value="/tmp/video.mp4"):
            result = asyncio.get_event_loop().run_until_complete(
                download_video(bot, "https://cdn/video.mp4", content_id=1)
            )

    assert result == "/tmp/video.mp4"


# ------------------------------------------------------------------
# Veo3Client: Scene Extension
# ------------------------------------------------------------------


def _make_completed_operation(name: str, video_uri: str = "https://cdn/video.mp4"):
    """Create a fake SDK operation that looks completed with a video."""
    op = MagicMock()
    op.name = name
    op.done = True
    op.error = None
    video_obj = MagicMock()
    video_obj.uri = video_uri
    generated_video = MagicMock()
    generated_video.video = video_obj
    op.response = MagicMock()
    op.response.generated_videos = [generated_video]
    return op


def _make_failed_operation(name: str, error: str = "GPU error"):
    """Create a fake SDK operation that looks failed."""
    op = MagicMock()
    op.name = name
    op.done = True
    op.error = error
    return op


def _make_pending_operation(name: str):
    """Create a fake SDK operation still in progress."""
    op = MagicMock()
    op.name = name
    op.done = False
    return op


class TestVeo3SceneExtension:
    """Tests for Veo3Client._generate_extended_video (Scene Extension)."""

    def _make_client(self) -> Veo3Client:
        """Create a Veo3Client with mocked SDK client."""
        with patch("app.integrations.veo_client.genai.Client"):
            client = Veo3Client(api_key="test-key")
        return client

    def test_short_duration_no_extension(self):
        """Durations <= 8s should use single call, not extension."""
        client = self._make_client()

        submit_op = MagicMock()
        submit_op.name = "op-short"
        client._client.models.generate_videos = MagicMock(return_value=submit_op)

        result = asyncio.get_event_loop().run_until_complete(
            client.generate_video("A scene", duration=6, aspect_ratio="9:16")
        )

        assert result == "op-short"
        # Only 1 call (no extensions)
        assert client._client.models.generate_videos.call_count == 1

    def test_extension_for_30s_video(self):
        """30s video should do 1 initial + 4 extensions (8 + 4*7 = 36s)."""
        client = self._make_client()

        # Initial generation
        init_op = MagicMock()
        init_op.name = "op-init"

        # Extension operations
        ext_ops = [MagicMock(name=f"op-ext-{i}") for i in range(4)]
        for i, op in enumerate(ext_ops):
            op.name = f"op-ext-{i}"

        # generate_videos returns: initial, then 4 extensions
        client._client.models.generate_videos = MagicMock(
            side_effect=[init_op] + ext_ops
        )

        # operations.get returns completed operations
        completed_results = [
            _make_completed_operation("op-init", "https://cdn/v0.mp4"),
            _make_completed_operation("op-ext-0", "https://cdn/v1.mp4"),
            _make_completed_operation("op-ext-1", "https://cdn/v2.mp4"),
            _make_completed_operation("op-ext-2", "https://cdn/v3.mp4"),
            _make_completed_operation("op-ext-3", "https://cdn/v4.mp4"),
        ]
        client._client.operations.get = MagicMock(side_effect=completed_results)

        result = asyncio.get_event_loop().run_until_complete(
            client.generate_video("Epic scene", duration=30, aspect_ratio="9:16")
        )

        # Should return the last extension operation name
        assert result == "op-ext-3"
        # 1 initial + 4 extensions = 5 generate_videos calls
        assert client._client.models.generate_videos.call_count == 5
        # 5 poll calls (1 per operation)
        assert client._client.operations.get.call_count == 5

    def test_extension_for_15s_video(self):
        """15s video should do 1 initial + 1 extension (8 + 7 = 15s)."""
        client = self._make_client()

        init_op = MagicMock()
        init_op.name = "op-init"
        ext_op = MagicMock()
        ext_op.name = "op-ext-0"

        client._client.models.generate_videos = MagicMock(
            side_effect=[init_op, ext_op]
        )
        client._client.operations.get = MagicMock(side_effect=[
            _make_completed_operation("op-init"),
            _make_completed_operation("op-ext-0"),
        ])

        result = asyncio.get_event_loop().run_until_complete(
            client.generate_video("Scene", duration=15, aspect_ratio="9:16")
        )

        assert result == "op-ext-0"
        assert client._client.models.generate_videos.call_count == 2

    def test_extension_passes_video_reference(self):
        """Extension calls should pass the previous video object."""
        client = self._make_client()

        init_op = MagicMock()
        init_op.name = "op-init"
        ext_op = MagicMock()
        ext_op.name = "op-ext-0"

        client._client.models.generate_videos = MagicMock(
            side_effect=[init_op, ext_op]
        )

        # The initial video result has a video object
        init_result = _make_completed_operation("op-init")
        video_ref = init_result.response.generated_videos[0].video
        ext_result = _make_completed_operation("op-ext-0")

        client._client.operations.get = MagicMock(
            side_effect=[init_result, ext_result]
        )

        asyncio.get_event_loop().run_until_complete(
            client.generate_video("Scene", duration=10, aspect_ratio="9:16")
        )

        # Second generate_videos call should include video= parameter
        ext_call = client._client.models.generate_videos.call_args_list[1]
        assert ext_call.kwargs.get("video") is video_ref

    def test_extension_initial_failure_returns_op_name(self):
        """If initial generation fails, return its operation name."""
        client = self._make_client()

        init_op = MagicMock()
        init_op.name = "op-failed"
        client._client.models.generate_videos = MagicMock(return_value=init_op)

        client._client.operations.get = MagicMock(
            return_value=_make_failed_operation("op-failed")
        )

        result = asyncio.get_event_loop().run_until_complete(
            client.generate_video("Scene", duration=30, aspect_ratio="9:16")
        )

        assert result == "op-failed"
        # Only initial call, no extensions attempted
        assert client._client.models.generate_videos.call_count == 1

    def test_extension_partial_failure_returns_last_success(self):
        """If extension 2 fails, should return last successful op name."""
        client = self._make_client()

        init_op = MagicMock()
        init_op.name = "op-init"
        ext_op_1 = MagicMock()
        ext_op_1.name = "op-ext-0"
        ext_op_2 = MagicMock()
        ext_op_2.name = "op-ext-1"

        client._client.models.generate_videos = MagicMock(
            side_effect=[init_op, ext_op_1, ext_op_2]
        )
        client._client.operations.get = MagicMock(side_effect=[
            _make_completed_operation("op-init"),
            _make_completed_operation("op-ext-0"),
            _make_failed_operation("op-ext-1", "Rate limit"),
        ])

        result = asyncio.get_event_loop().run_until_complete(
            client.generate_video("Scene", duration=30, aspect_ratio="9:16")
        )

        # Should return last successful extension, not the failed one
        assert result == "op-ext-0"

    def test_extension_count_calculation(self):
        """Verify correct number of extensions for various durations."""
        import math
        # 9s -> ceil((9-8)/7) = 1 extension
        assert math.ceil((9 - _MAX_SINGLE_DURATION) / _EXTENSION_SECONDS) == 1
        # 15s -> ceil((15-8)/7) = 1 extension
        assert math.ceil((15 - _MAX_SINGLE_DURATION) / _EXTENSION_SECONDS) == 1
        # 16s -> ceil((16-8)/7) = 2 extensions
        assert math.ceil((16 - _MAX_SINGLE_DURATION) / _EXTENSION_SECONDS) == 2
        # 30s -> ceil((30-8)/7) = 4 extensions (8+28=36s)
        assert math.ceil((30 - _MAX_SINGLE_DURATION) / _EXTENSION_SECONDS) == 4
        # 60s -> ceil((60-8)/7) = 8 extensions (8+56=64s)
        assert math.ceil((60 - _MAX_SINGLE_DURATION) / _EXTENSION_SECONDS) == 8

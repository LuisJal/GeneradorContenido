"""Tests for Alembic migrations - verify schema matches models."""
import os
import tempfile

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_alembic_migration_creates_all_tables():
    """Running 'upgrade head' should create all 4 model tables."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        db_url = f"sqlite:///{db_path}"

        alembic_cfg = Config("alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", db_url)

        command.upgrade(alembic_cfg, "head")

        engine = create_engine(db_url)
        tables = inspect(engine).get_table_names()

        assert "bots" in tables
        assert "content_items" in tables
        assert "social_credentials" in tables
        assert "pipeline_logs" in tables
        assert "alembic_version" in tables


def test_alembic_migration_bot_columns():
    """Bots table should have all expected columns after migration."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        db_url = f"sqlite:///{db_path}"

        alembic_cfg = Config("alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", db_url)

        command.upgrade(alembic_cfg, "head")

        engine = create_engine(db_url)
        columns = {c["name"] for c in inspect(engine).get_columns("bots")}

        expected = {
            "id", "name", "slug", "niche", "niche_description",
            "content_style", "language", "is_enabled", "videos_per_day",
            "posting_schedule", "use_trends", "custom_prompts",
            "video_provider", "video_duration_seconds", "video_aspect_ratio",
            "gemini_api_key", "gemini_model", "telegram_chat_id",
            "contact_email", "script_system_prompt", "trend_sources",
            "created_at", "updated_at",
        }
        assert expected.issubset(columns), f"Missing columns: {expected - columns}"

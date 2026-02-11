"""End-to-end test: generate 1 video with the full pipeline.

Usage:
    source .venv/bin/activate
    python scripts/test_e2e.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Ensure project root is in path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.orm import Session

from app.config import settings
from app.database import sync_engine
from app.models import Base
from app.models.bot import Bot
from app.services import pipeline_orchestrator


def _create_test_bot(db: Session) -> Bot:
    """Create (or reuse) a minimal test bot."""
    existing = db.query(Bot).filter_by(slug="test-e2e").first()
    if existing:
        print(f"  Reusing existing bot: {existing.name} (id={existing.id})")
        return existing

    bot = Bot(
        name="Test E2E",
        slug="test-e2e",
        niche="tecnologia",
        niche_description="Tecnologia, gadgets, innovacion",
        content_style="Informativo y entretenido",
        language="es",
        is_enabled=False,  # No scheduler, manual run only
        videos_per_day=1,
        use_trends=False,  # Use custom prompt instead of scraping
        custom_prompts=[
            "Los 3 gadgets mas innovadores de 2025 que nadie conoce"
        ],
        video_provider="veo3",
        video_duration_seconds=8,  # Minimum for Gemini API
        video_aspect_ratio="9:16",
        gemini_model="gemini-2.5-flash",
        telegram_chat_id=settings.telegram_bot_token and "1301656251" or "",
    )
    db.add(bot)
    db.commit()
    db.refresh(bot)
    print(f"  Created test bot: {bot.name} (id={bot.id})")
    return bot


async def main() -> None:
    print("=" * 60)
    print("  GENERADOR CONTENIDO - End-to-End Test")
    print("=" * 60)

    # Verify required settings
    print("\n[1/5] Checking configuration...")
    if not settings.gemini_api_key:
        print("  ERROR: GEMINI_API_KEY not set in .env")
        sys.exit(1)
    print(f"  Gemini API key: ...{settings.gemini_api_key[-8:]}")
    print(f"  Telegram token: {'set' if settings.telegram_bot_token else 'NOT SET'}")
    print(f"  Video storage: {settings.videos_dir}")

    # Initialize DB
    print("\n[2/5] Initializing database...")
    Base.metadata.create_all(sync_engine)
    print("  Database ready")

    # Create test bot
    print("\n[3/5] Creating test bot...")
    with Session(sync_engine) as db:
        bot = _create_test_bot(db)
        bot_id = bot.id

    # Run Phase 1: Topic -> Script -> Video submission
    print("\n[4/5] Running Phase 1: Script + Video generation...")
    print("  This will:")
    print("    - Generate a script with Gemini")
    print("    - Create a video prompt")
    print("    - Submit video generation to Veo 3")
    print("  (This may take a few minutes)\n")

    with Session(sync_engine) as db:
        bot = db.query(Bot).get(bot_id)
        try:
            content = await pipeline_orchestrator.run_pipeline(bot, db)
            print(f"\n  Phase 1 complete!")
            print(f"  Content ID: {content.id}")
            print(f"  Topic: {content.trend_topic}")
            print(f"  Status: {content.status}")
            print(f"  Video task ID: {content.video_task_id}")
            content_id = content.id
        except Exception as exc:
            print(f"\n  ERROR in Phase 1: {exc}")
            import traceback
            traceback.print_exc()
            sys.exit(1)

    # Run Phase 2: Poll video -> Descriptions -> Telegram approval
    print("\n[5/5] Running Phase 2: Waiting for video + sending to Telegram...")
    print("  Polling video generation status (this can take up to 6 minutes)...\n")

    with Session(sync_engine) as db:
        bot = db.query(Bot).get(bot_id)
        content = db.query(
            __import__("app.models.content", fromlist=["ContentItem"]).ContentItem
        ).get(content_id)

        try:
            content = await pipeline_orchestrator.resume_after_video(content, bot, db)
            print(f"\n  Phase 2 complete!")
            print(f"  Status: {content.status}")
            print(f"  Video path: {content.video_file_path}")
            print(f"  IG description: {(content.description_instagram or '')[:100]}...")
            if content.status == "pending_approval":
                print(f"\n  Video sent to Telegram for approval!")
                print(f"  Check your Telegram chat to approve/reject.")
        except Exception as exc:
            print(f"\n  ERROR in Phase 2: {exc}")
            import traceback
            traceback.print_exc()
            sys.exit(1)

    print("\n" + "=" * 60)
    print("  Test complete!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

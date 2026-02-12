from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.routers.dashboard import router as dashboard_router
from app.routers.webhooks import router as webhooks_router
from app.utils.logging_config import setup_logging, get_logger

logger = get_logger("main")

APP_DIR = Path(__file__).resolve().parent


_DEFAULT_BOTS = [
    ("MadridGirl", "madridgirl"),
]


def _ensure_default_bots(db) -> None:
    """Create default bots from templates if they don't already exist."""
    from app.schemas.bot import BotCreate, PostingSchedule
    from app.services.bot_manager import create_bot, get_bot_by_slug, load_template

    for bot_name, template_name in _DEFAULT_BOTS:
        slug = "madridgirl"
        if get_bot_by_slug(db, slug):
            logger.debug("Default bot '%s' already exists, skipping", slug)
            continue

        try:
            tmpl = load_template(template_name)
        except ValueError:
            logger.warning("Template '%s' not found, skipping", template_name)
            continue

        sched = tmpl.get("posting_schedule", {})
        data = BotCreate(
            name=bot_name,
            niche=tmpl.get("niche", ""),
            niche_description=tmpl.get("niche_description", ""),
            content_style=tmpl.get("content_style", ""),
            brand_style=tmpl.get("brand_style", ""),
            language=tmpl.get("language", "es"),
            videos_per_day=tmpl.get("videos_per_day", 1),
            posting_schedule=PostingSchedule(
                times=sched.get("times", ["09:00"]),
                timezone=sched.get("timezone", "Europe/Madrid"),
            ),
            use_trends=tmpl.get("use_trends", True),
            custom_prompts=tmpl.get("custom_prompts", []),
            video_provider=tmpl.get("video_provider", "talking_head"),
            video_duration_seconds=tmpl.get("video_duration_seconds", 30),
            gemini_model=tmpl.get("gemini_model", "gemini-2.5-flash"),
            script_system_prompt=tmpl.get("script_system_prompt", ""),
            character_face_url=tmpl.get("character_face_url"),
            character_voice_id=tmpl.get("character_voice_id"),
            character_personality=tmpl.get("character_personality"),
            template=template_name,
        )
        bot = create_bot(db, data)
        logger.info("Created default bot '%s' (id=%d)", bot.name, bot.id)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info("GeneradorContenido starting up (env=%s)", settings.app_env)

    # Initialize APScheduler
    from app.services.scheduler_service import (
        init_scheduler,
        schedule_all_bots,
        schedule_video_polling,
    )
    from app.database import get_db

    sched = init_scheduler()
    schedule_video_polling()

    db_gen = get_db()
    db = next(db_gen)
    try:
        _ensure_default_bots(db)
        schedule_all_bots(db)
    finally:
        try:
            next(db_gen, None)
        except StopIteration:
            pass

    sched.start()
    logger.info("Scheduler started")

    yield

    sched.shutdown(wait=False)
    logger.info("GeneradorContenido shutting down")


app = FastAPI(
    title="GeneradorContenido",
    version="0.1.0",
    lifespan=lifespan,
)

# Static files -- videos must be mounted first (more specific path)
app.mount("/static/videos", StaticFiles(directory=str(settings.videos_dir)), name="videos")
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")

# Routers
app.include_router(dashboard_router)
app.include_router(webhooks_router)


# --- Health endpoint ---

@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}

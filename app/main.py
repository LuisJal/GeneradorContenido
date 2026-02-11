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

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
    yield
    logger.info("GeneradorContenido shutting down")


app = FastAPI(
    title="GeneradorContenido",
    version="0.1.0",
    lifespan=lifespan,
)

# Static files
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")

# Routers
app.include_router(dashboard_router)
app.include_router(webhooks_router)


# --- Health endpoint ---

@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}

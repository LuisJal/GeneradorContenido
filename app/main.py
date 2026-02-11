from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
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

# Templates
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))


# --- Health endpoint ---

@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


# --- Dashboard home ---

@app.get("/", response_class=HTMLResponse)
async def dashboard_home(request: Request):
    return templates.TemplateResponse(request, "dashboard.html", {
        "bots": [],
    })

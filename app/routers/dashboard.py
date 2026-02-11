"""Dashboard routes: HTML pages for bot management via Jinja2 + HTMX."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.bot import BotCreate, BotUpdate, PostingSchedule
from app.services import bot_manager

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _available_templates():
    """List available bot template names."""
    templates_dir = Path(__file__).resolve().parent.parent.parent / "bot_templates"
    return [p.stem for p in templates_dir.glob("*.json")]


@router.get("/", response_class=HTMLResponse)
async def dashboard_home(request: Request, db: Session = Depends(get_db)):
    bots = bot_manager.list_bots(db)
    return templates.TemplateResponse(request, "dashboard.html", {
        "bots": bots,
    })


@router.get("/bots/new", response_class=HTMLResponse)
async def bot_create_form(request: Request):
    return templates.TemplateResponse(request, "bot_create.html", {
        "templates": _available_templates(),
        "errors": {},
    })


@router.post("/bots/new")
async def bot_create_submit(
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
    niche: str = Form(...),
    niche_description: str = Form(""),
    content_style: str = Form(""),
    language: str = Form("es"),
    videos_per_day: int = Form(1),
    schedule_times: str = Form("09:00"),
    schedule_timezone: str = Form("Europe/Madrid"),
    use_trends: Optional[str] = Form(None),
    video_provider: str = Form("veo3"),
    video_duration_seconds: int = Form(15),
    gemini_api_key: str = Form(""),
    telegram_chat_id: str = Form(""),
    contact_email: str = Form(""),
    template: str = Form(""),
):
    try:
        data = BotCreate(
            name=name,
            niche=niche,
            niche_description=niche_description,
            content_style=content_style,
            language=language,
            videos_per_day=videos_per_day,
            posting_schedule=PostingSchedule(
                times=[t.strip() for t in schedule_times.split(",")],
                timezone=schedule_timezone,
            ),
            use_trends=use_trends is not None,
            video_provider=video_provider,
            video_duration_seconds=video_duration_seconds,
            gemini_api_key=gemini_api_key or None,
            telegram_chat_id=telegram_chat_id or None,
            contact_email=contact_email or None,
            template=template or None,
        )
        bot = bot_manager.create_bot(db, data)
        return RedirectResponse(url=f"/bots/{bot.slug}", status_code=303)
    except (ValueError, Exception) as e:
        return templates.TemplateResponse(request, "bot_create.html", {
            "templates": _available_templates(),
            "errors": {"general": str(e)},
        }, status_code=400)


@router.get("/bots/{slug}", response_class=HTMLResponse)
async def bot_detail(request: Request, slug: str, db: Session = Depends(get_db)):
    bot = bot_manager.get_bot_by_slug(db, slug)
    if not bot:
        return templates.TemplateResponse(request, "404.html", {}, status_code=404)
    return templates.TemplateResponse(request, "bot_detail.html", {
        "bot": bot,
    })


@router.get("/bots/{slug}/edit", response_class=HTMLResponse)
async def bot_edit_form(request: Request, slug: str, db: Session = Depends(get_db)):
    bot = bot_manager.get_bot_by_slug(db, slug)
    if not bot:
        return templates.TemplateResponse(request, "404.html", {}, status_code=404)
    return templates.TemplateResponse(request, "bot_edit.html", {
        "bot": bot,
        "errors": {},
    })


@router.post("/bots/{slug}/edit")
async def bot_edit_submit(
    request: Request,
    slug: str,
    db: Session = Depends(get_db),
    niche_description: str = Form(""),
    content_style: str = Form(""),
    language: str = Form("es"),
    videos_per_day: int = Form(1),
    schedule_times: str = Form("09:00"),
    schedule_timezone: str = Form("Europe/Madrid"),
    use_trends: Optional[str] = Form(None),
    video_provider: str = Form("veo3"),
    video_duration_seconds: int = Form(15),
    gemini_api_key: str = Form(""),
    telegram_chat_id: str = Form(""),
    contact_email: str = Form(""),
    script_system_prompt: str = Form(""),
):
    try:
        data = BotUpdate(
            niche_description=niche_description or None,
            content_style=content_style or None,
            language=language,
            videos_per_day=videos_per_day,
            posting_schedule=PostingSchedule(
                times=[t.strip() for t in schedule_times.split(",")],
                timezone=schedule_timezone,
            ),
            use_trends=use_trends is not None,
            video_provider=video_provider,
            video_duration_seconds=video_duration_seconds,
            gemini_api_key=gemini_api_key or None,
            telegram_chat_id=telegram_chat_id or None,
            contact_email=contact_email or None,
            script_system_prompt=script_system_prompt or None,
        )
        bot_manager.update_bot(db, slug, data)
        return RedirectResponse(url=f"/bots/{slug}", status_code=303)
    except (ValueError, Exception) as e:
        bot = bot_manager.get_bot_by_slug(db, slug)
        return templates.TemplateResponse(request, "bot_edit.html", {
            "bot": bot,
            "errors": {"general": str(e)},
        }, status_code=400)


@router.post("/bots/{slug}/toggle")
async def bot_toggle(request: Request, slug: str, db: Session = Depends(get_db)):
    bot = bot_manager.toggle_bot(db, slug)
    if not bot:
        return HTMLResponse("Bot not found", status_code=404)
    return templates.TemplateResponse(request, "partials/bot_card.html", {
        "bot": bot,
    })


@router.post("/bots/{slug}/delete")
async def bot_delete(slug: str, db: Session = Depends(get_db)):
    bot_manager.delete_bot(db, slug)
    return RedirectResponse(url="/", status_code=303)

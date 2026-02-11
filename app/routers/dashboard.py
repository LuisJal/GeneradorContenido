"""Dashboard routes: HTML pages for bot management via Jinja2 + HTMX."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from sqlalchemy import desc

from app.database import get_db
from app.models.content import ContentItem, ContentStatus
from app.models.credential import SocialCredential
from app.models.log_entry import PipelineLog
from app.schemas.bot import BotCreate, BotUpdate, PostingSchedule
from app.services import bot_manager
from app.services.settings_manager import get_all_settings, save_setting, SETTING_DEFINITIONS
from app.utils.encryption import FieldEncryptor

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))

# Register custom Jinja2 filter for extracting basename from paths
import os
templates.env.filters["basename"] = lambda path: os.path.basename(path) if path else ""


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


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, db: Session = Depends(get_db)):
    current = get_all_settings(db)
    return templates.TemplateResponse(request, "settings.html", {
        "current": current,
        "message": None,
    })


@router.post("/settings")
async def settings_save(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    for key in SETTING_DEFINITIONS:
        value = form.get(key, "")
        if value:
            save_setting(db, key, value)
    current = get_all_settings(db)
    return templates.TemplateResponse(request, "settings.html", {
        "current": current,
        "message": "Configuracion guardada correctamente.",
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
    pending_count = db.query(ContentItem).filter(
        ContentItem.bot_id == bot.id,
        ContentItem.status == ContentStatus.PENDING_APPROVAL.value,
    ).count()
    return templates.TemplateResponse(request, "bot_detail.html", {
        "bot": bot,
        "pending_count": pending_count,
    })


@router.get("/bots/{slug}/edit", response_class=HTMLResponse)
async def bot_edit_form(request: Request, slug: str, db: Session = Depends(get_db)):
    bot = bot_manager.get_bot_by_slug(db, slug)
    if not bot:
        return templates.TemplateResponse(request, "404.html", {}, status_code=404)
    credentials = db.query(SocialCredential).filter(
        SocialCredential.bot_id == bot.id
    ).all()
    return templates.TemplateResponse(request, "bot_edit.html", {
        "bot": bot,
        "credentials": credentials,
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
            contact_email=contact_email or None,
            script_system_prompt=script_system_prompt or None,
        )
        bot_manager.update_bot(db, slug, data)
        return RedirectResponse(url=f"/bots/{slug}", status_code=303)
    except (ValueError, Exception) as e:
        bot = bot_manager.get_bot_by_slug(db, slug)
        credentials = db.query(SocialCredential).filter(
            SocialCredential.bot_id == bot.id
        ).all() if bot else []
        return templates.TemplateResponse(request, "bot_edit.html", {
            "bot": bot,
            "credentials": credentials,
            "errors": {"general": str(e)},
        }, status_code=400)


@router.post("/bots/{slug}/toggle")
async def bot_toggle(request: Request, slug: str, db: Session = Depends(get_db)):
    bot = bot_manager.toggle_bot(db, slug)
    if not bot:
        return HTMLResponse("Bot not found", status_code=404)

    # Update scheduler
    try:
        from app.services.scheduler_service import schedule_bot, unschedule_bot
        if bot.is_enabled:
            schedule_bot(bot)
        else:
            unschedule_bot(bot.id)
    except RuntimeError:
        pass  # Scheduler not initialized (e.g. in tests)

    return templates.TemplateResponse(request, "partials/bot_card.html", {
        "bot": bot,
    })


@router.post("/bots/{slug}/run")
async def bot_run_now(request: Request, slug: str, db: Session = Depends(get_db)):
    bot = bot_manager.get_bot_by_slug(db, slug)
    if not bot:
        return HTMLResponse("Bot not found", status_code=404)
    try:
        from app.services.scheduler_service import trigger_now
        content = await trigger_now(bot, db)
        return templates.TemplateResponse(request, "partials/bot_card.html", {
            "bot": bot,
            "message": f"Pipeline iniciado (contenido #{content.id})",
        })
    except Exception as e:
        return templates.TemplateResponse(request, "partials/bot_card.html", {
            "bot": bot,
            "error": str(e),
        })


@router.get("/bots/{slug}/content", response_class=HTMLResponse)
async def bot_content_list(
    request: Request, slug: str, db: Session = Depends(get_db),
    filter: Optional[str] = None,
):
    bot = bot_manager.get_bot_by_slug(db, slug)
    if not bot:
        return templates.TemplateResponse(request, "404.html", {}, status_code=404)
    query = db.query(ContentItem).filter(ContentItem.bot_id == bot.id)
    if filter:
        query = query.filter(ContentItem.status == filter)
    items = query.order_by(desc(ContentItem.created_at)).limit(50).all()
    return templates.TemplateResponse(request, "content_list.html", {
        "bot": bot,
        "items": items,
        "current_filter": filter,
    })


@router.get("/bots/{slug}/content/{content_id}", response_class=HTMLResponse)
async def bot_content_detail(
    request: Request, slug: str, content_id: int, db: Session = Depends(get_db)
):
    bot = bot_manager.get_bot_by_slug(db, slug)
    if not bot:
        return templates.TemplateResponse(request, "404.html", {}, status_code=404)
    item = db.query(ContentItem).filter(
        ContentItem.id == content_id, ContentItem.bot_id == bot.id
    ).first()
    if not item:
        return templates.TemplateResponse(request, "404.html", {}, status_code=404)
    return templates.TemplateResponse(request, "content_detail.html", {
        "bot": bot,
        "item": item,
    })


@router.get("/bots/{slug}/logs", response_class=HTMLResponse)
async def bot_logs(request: Request, slug: str, db: Session = Depends(get_db)):
    bot = bot_manager.get_bot_by_slug(db, slug)
    if not bot:
        return templates.TemplateResponse(request, "404.html", {}, status_code=404)
    logs = (
        db.query(PipelineLog)
        .filter(PipelineLog.bot_id == bot.id)
        .order_by(desc(PipelineLog.created_at))
        .limit(100)
        .all()
    )
    return templates.TemplateResponse(request, "logs.html", {
        "bot": bot,
        "logs": logs,
    })


@router.get("/bots/{slug}/credentials")
async def bot_credentials(slug: str):
    """Redirect to bot edit page where credentials are now managed."""
    return RedirectResponse(url=f"/bots/{slug}/edit", status_code=302)


@router.post("/bots/{slug}/credentials")
async def bot_add_credential(
    request: Request,
    slug: str,
    db: Session = Depends(get_db),
    platform: str = Form(...),
    access_token: str = Form(...),
    refresh_token: str = Form(""),
    platform_user_id: str = Form(""),
):
    bot = bot_manager.get_bot_by_slug(db, slug)
    if not bot:
        return templates.TemplateResponse(request, "404.html", {}, status_code=404)

    from app.config import settings
    encryptor = FieldEncryptor(settings.encryption_key)

    cred = SocialCredential(
        bot_id=bot.id,
        platform=platform,
        access_token_encrypted=encryptor.encrypt(access_token),
        refresh_token_encrypted=encryptor.encrypt(refresh_token) if refresh_token else None,
        platform_user_id=platform_user_id or None,
    )
    db.add(cred)
    db.commit()

    return RedirectResponse(url=f"/bots/{slug}/edit", status_code=303)


@router.post("/bots/{slug}/credentials/{cred_id}/toggle")
async def bot_toggle_credential(
    request: Request, slug: str, cred_id: int, db: Session = Depends(get_db),
):
    """Toggle a credential's active state via HTMX."""
    bot = bot_manager.get_bot_by_slug(db, slug)
    if not bot:
        return HTMLResponse("Bot not found", status_code=404)
    cred = db.query(SocialCredential).filter(
        SocialCredential.id == cred_id, SocialCredential.bot_id == bot.id
    ).first()
    if not cred:
        return HTMLResponse("Credential not found", status_code=404)

    cred.is_active = not cred.is_active
    db.commit()

    # Return updated table row for HTMX swap
    status_html = (
        '<span class="badge-active"><span class="pulse-dot"></span> Activa</span>'
        if cred.is_active
        else '<span class="badge-inactive">Inactiva</span>'
    )
    toggle_label = "Desactivar" if cred.is_active else "Activar"
    return HTMLResponse(f"""<tr>
        <td>{cred.platform.capitalize()}</td>
        <td>{cred.platform_user_id or "-"}</td>
        <td>{status_html}</td>
        <td>
            <button hx-post="/bots/{slug}/credentials/{cred.id}/toggle"
                    hx-swap="outerHTML" hx-target="closest tr"
                    class="btn-action" style="padding:0.3rem 0.8rem;font-size:0.8rem;">
                {toggle_label}
            </button>
            <button hx-post="/bots/{slug}/credentials/{cred.id}/delete"
                    hx-swap="outerHTML" hx-target="closest tr"
                    hx-confirm="Eliminar credencial de {cred.platform}?"
                    class="btn-action danger" style="padding:0.3rem 0.8rem;font-size:0.8rem;">
                Eliminar
            </button>
        </td>
    </tr>""")


@router.post("/bots/{slug}/credentials/{cred_id}/delete")
async def bot_delete_credential(
    slug: str, cred_id: int, db: Session = Depends(get_db),
):
    """Delete a credential via HTMX."""
    bot = bot_manager.get_bot_by_slug(db, slug)
    if not bot:
        return HTMLResponse("Bot not found", status_code=404)
    cred = db.query(SocialCredential).filter(
        SocialCredential.id == cred_id, SocialCredential.bot_id == bot.id
    ).first()
    if not cred:
        return HTMLResponse("Credential not found", status_code=404)

    db.delete(cred)
    db.commit()
    # Return empty string to remove the row
    return HTMLResponse("")


@router.post("/bots/{slug}/content/{content_id}/approve")
async def content_approve(
    request: Request, slug: str, content_id: int, db: Session = Depends(get_db),
):
    """Approve content and trigger publishing."""
    bot = bot_manager.get_bot_by_slug(db, slug)
    if not bot:
        return HTMLResponse("Bot not found", status_code=404)
    item = db.query(ContentItem).filter(
        ContentItem.id == content_id, ContentItem.bot_id == bot.id
    ).first()
    if not item:
        return HTMLResponse("Content not found", status_code=404)

    # Update descriptions from form
    form = await request.form()
    item.description_instagram = form.get("description_instagram", item.description_instagram)
    item.description_youtube = form.get("description_youtube", item.description_youtube)
    item.description_tiktok = form.get("description_tiktok", item.description_tiktok)

    # Mark approved
    item.approval_status = "approved"
    item.status = ContentStatus.APPROVED.value
    db.commit()

    # Trigger publishing asynchronously
    try:
        from app.services.pipeline_orchestrator import resume_after_approval
        await resume_after_approval(item, bot, db)
    except Exception as exc:
        return HTMLResponse(
            f'<div class="flash-error">Error al publicar: {exc}</div>',
        )

    db.refresh(item)
    return HTMLResponse(
        f'<div class="flash-success">Contenido aprobado y publicado. Estado: {item.status}</div>',
    )


@router.post("/bots/{slug}/content/{content_id}/reject")
async def content_reject(
    slug: str, content_id: int, db: Session = Depends(get_db),
):
    """Reject content."""
    bot = bot_manager.get_bot_by_slug(db, slug)
    if not bot:
        return HTMLResponse("Bot not found", status_code=404)
    item = db.query(ContentItem).filter(
        ContentItem.id == content_id, ContentItem.bot_id == bot.id
    ).first()
    if not item:
        return HTMLResponse("Content not found", status_code=404)

    item.approval_status = "rejected"
    item.status = ContentStatus.REJECTED.value
    db.commit()

    return HTMLResponse(
        '<div class="flash-error">Contenido rechazado.</div>',
    )


@router.post("/bots/{slug}/delete")
async def bot_delete(request: Request, slug: str, db: Session = Depends(get_db)):
    bot_manager.delete_bot(db, slug)
    # HTMX requests need HX-Redirect header for full page navigation
    if request.headers.get("HX-Request"):
        return HTMLResponse("", headers={"HX-Redirect": "/"})
    return RedirectResponse(url="/", status_code=303)

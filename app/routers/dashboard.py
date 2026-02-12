"""Dashboard routes: HTML pages for bot management via Jinja2 + HTMX."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

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
from app.services.settings_manager import (
    get_all_settings, save_setting, SETTING_DEFINITIONS,
)
from app.utils.encryption import FieldEncryptor

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))

# Register custom Jinja2 filters
import os
from app.config import settings as app_settings
templates.env.filters["basename"] = lambda path: os.path.basename(path) if path else ""


def _video_url(path: str) -> str:
    """Convert an absolute video file path to a URL relative to /static/videos/."""
    if not path:
        return ""
    try:
        return "/static/videos/" + str(Path(path).relative_to(app_settings.videos_dir))
    except ValueError:
        return "/static/videos/" + os.path.basename(path)


templates.env.filters["video_url"] = _video_url


def _available_templates():
    """List available bot template names."""
    templates_dir = Path(__file__).resolve().parent.parent.parent / "bot_templates"
    return [p.stem for p in templates_dir.glob("*.json")]


@router.get("/legal/terms", response_class=HTMLResponse)
async def legal_terms(request: Request):
    return templates.TemplateResponse(request, "legal_terms.html")


@router.get("/legal/privacy", response_class=HTMLResponse)
async def legal_privacy(request: Request):
    return templates.TemplateResponse(request, "legal_privacy.html")


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
    brand_style: str = Form(""),
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
            brand_style=brand_style,
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
    brand_style: str = Form(""),
    language: str = Form("es"),
    videos_per_day: int = Form(1),
    schedule_times: str = Form("09:00"),
    schedule_timezone: str = Form("Europe/Madrid"),
    use_trends: Optional[str] = Form(None),
    video_provider: str = Form("veo3"),
    video_duration_seconds: int = Form(15),
    contact_email: str = Form(""),
    script_system_prompt: str = Form(""),
    story_arc_enabled: Optional[str] = Form(None),
    story_arc_chapters: int = Form(3),
):
    try:
        data = BotUpdate(
            niche_description=niche_description or None,
            content_style=content_style or None,
            brand_style=brand_style or None,
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
            story_arc_enabled=story_arc_enabled is not None,
            story_arc_chapters=story_arc_chapters,
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

    # If called from bot detail page (HTMX), auto-generate videos on enable
    if request.headers.get("HX-Request"):
        if bot.is_enabled:
            # Auto-generate videos
            generated = []
            errors = []
            try:
                from app.services.scheduler_service import trigger_now
                result = await trigger_now(bot, db)
                if isinstance(result, list):
                    generated.extend(c.id for c in result)
                else:
                    generated.append(result.id)
            except Exception as e:
                errors.append(str(e))

            if generated:
                ids = ", ".join(f"#{cid}" for cid in generated)
                msg = f'<div class="flash-success">Bot activado. Generando {len(generated)} video(s): {ids}. El video polling los procesara automaticamente.</div>'
            else:
                msg = f'<div class="flash-error">Bot activado pero fallo al generar: {errors[0] if errors else "error desconocido"}</div>'
            return HTMLResponse(msg)
        else:
            return HTMLResponse('<div class="flash-success">Bot desactivado.</div>')

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
        result = await trigger_now(bot, db)

        if isinstance(result, list):
            links = ", ".join(
                f'<a href="/bots/{slug}/content/{c.id}">#{c.id} (Cap {c.story_arc_chapter})</a>'
                for c in result
            )
            return HTMLResponse(
                f'<div class="flash-success">Arco narrativo iniciado: '
                f'{len(result)} capitulos ({links}). '
                f'Los videos se procesaran automaticamente.</div>'
            )
        else:
            content = result
            return HTMLResponse(
                f'<div class="flash-success">Pipeline iniciado: contenido <a href="/bots/{slug}/content/{content.id}">#{content.id}</a> en estado {content.status}. El video se procesara automaticamente.</div>'
            )
    except Exception as e:
        return HTMLResponse(
            f'<div class="flash-error">Error al ejecutar: {e}</div>'
        )


@router.post("/bots/{slug}/run-arc")
async def bot_run_story_arc(request: Request, slug: str, db: Session = Depends(get_db)):
    """Generate a full story arc (multiple chapters)."""
    bot = bot_manager.get_bot_by_slug(db, slug)
    if not bot:
        return HTMLResponse("Bot not found", status_code=404)
    try:
        from app.services.pipeline_orchestrator import run_story_arc_pipeline
        items = await run_story_arc_pipeline(bot, db)
        links = ", ".join(
            f'<a href="/bots/{slug}/content/{c.id}">#{c.id} (Cap {c.story_arc_chapter})</a>'
            for c in items
        )
        return HTMLResponse(
            f'<div class="flash-success">Arco narrativo iniciado: '
            f'{len(items)} capitulos ({links}). '
            f'Los videos se procesaran automaticamente.</div>'
        )
    except Exception as e:
        return HTMLResponse(
            f'<div class="flash-error">Error al generar arco narrativo: {e}</div>'
        )


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

    # Group arc items for display
    arc_groups = {}
    for item in items:
        if item.story_arc_id:
            arc_groups.setdefault(item.story_arc_id, []).append(item)

    return templates.TemplateResponse(request, "content_list.html", {
        "bot": bot,
        "items": items,
        "current_filter": filter,
        "arc_groups": arc_groups,
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

    # Get sibling chapters if this is part of a story arc
    arc_siblings = []
    if item.story_arc_id:
        arc_siblings = (
            db.query(ContentItem)
            .filter(ContentItem.story_arc_id == item.story_arc_id)
            .order_by(ContentItem.story_arc_chapter)
            .all()
        )

    return templates.TemplateResponse(request, "content_detail.html", {
        "bot": bot,
        "item": item,
        "arc_siblings": arc_siblings,
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
    access_token: str = Form(""),
    refresh_token: str = Form(""),
    platform_user_id: str = Form(""),
    tiktok_client_key: str = Form(""),
    tiktok_client_secret: str = Form(""),
):
    bot = bot_manager.get_bot_by_slug(db, slug)
    if not bot:
        return templates.TemplateResponse(request, "404.html", {}, status_code=404)

    from app.config import settings
    encryptor = FieldEncryptor(settings.encryption_key)

    # Build extra_data for platform-specific fields
    extra = {}
    if platform == "tiktok" and tiktok_client_key:
        extra["client_key"] = encryptor.encrypt(tiktok_client_key)
        extra["client_secret"] = encryptor.encrypt(tiktok_client_secret) if tiktok_client_secret else ""

    cred = SocialCredential(
        bot_id=bot.id,
        platform=platform,
        access_token_encrypted=encryptor.encrypt(access_token) if access_token else None,
        refresh_token_encrypted=encryptor.encrypt(refresh_token) if refresh_token else None,
        platform_user_id=platform_user_id or None,
        extra_data=extra if extra else None,
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

    # Delete video file from disk to free storage
    if item.video_file_path:
        video_path = Path(item.video_file_path)
        if video_path.exists():
            video_path.unlink()

    # Delete the content item entirely from DB
    db.delete(item)
    db.commit()

    return HTMLResponse(
        '<div class="flash-success">Contenido rechazado y eliminado.</div>',
    )


@router.post("/bots/{slug}/delete")
async def bot_delete(request: Request, slug: str, db: Session = Depends(get_db)):
    bot_manager.delete_bot(db, slug)
    # HTMX requests need HX-Redirect header for full page navigation
    if request.headers.get("HX-Request"):
        return HTMLResponse("", headers={"HX-Redirect": "/"})
    return RedirectResponse(url="/", status_code=303)


# ------------------------------------------------------------------
# YouTube OAuth 2.0 flow (per-bot credentials)
# ------------------------------------------------------------------

_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_YOUTUBE_SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"

# In-memory state store for CSRF protection (state_token -> bot_slug)
_oauth_states: dict = {}


def _get_yt_oauth_keys(credential: SocialCredential) -> tuple:
    """Extract and decrypt YouTube client_id/client_secret from extra_data."""
    extra = credential.extra_data or {}
    encryptor = FieldEncryptor(app_settings.encryption_key)
    client_id = ""
    client_secret = ""
    if extra.get("client_id"):
        try:
            client_id = encryptor.decrypt(extra["client_id"])
        except Exception:
            client_id = extra["client_id"]
    if extra.get("client_secret"):
        try:
            client_secret = encryptor.decrypt(extra["client_secret"])
        except Exception:
            client_secret = extra["client_secret"]
    return client_id, client_secret


@router.post("/bots/{slug}/credentials/youtube")
async def bot_youtube_setup(
    request: Request,
    slug: str,
    db: Session = Depends(get_db),
    youtube_client_id: str = Form(...),
    youtube_client_secret: str = Form(...),
):
    """Save YouTube OAuth keys and redirect to Google consent screen."""
    bot = bot_manager.get_bot_by_slug(db, slug)
    if not bot:
        return templates.TemplateResponse(request, "404.html", {}, status_code=404)

    encryptor = FieldEncryptor(app_settings.encryption_key)

    # Create or update the YouTube credential with client keys in extra_data
    existing = db.query(SocialCredential).filter(
        SocialCredential.bot_id == bot.id,
        SocialCredential.platform == "youtube",
    ).first()

    extra = {
        "client_id": encryptor.encrypt(youtube_client_id.strip()),
        "client_secret": encryptor.encrypt(youtube_client_secret.strip()),
    }

    if existing:
        existing.extra_data = {**(existing.extra_data or {}), **extra}
    else:
        cred = SocialCredential(
            bot_id=bot.id,
            platform="youtube",
            extra_data=extra,
            is_active=False,  # Will activate after OAuth completes
        )
        db.add(cred)
    db.commit()

    # Now redirect to Google OAuth
    return RedirectResponse(
        url=f"/auth/youtube/start?bot_slug={slug}", status_code=303
    )


@router.get("/auth/youtube/start")
async def youtube_oauth_start(
    request: Request,
    bot_slug: str,
    db: Session = Depends(get_db),
):
    """Redirect the user to Google's consent screen to authorize YouTube."""
    bot = bot_manager.get_bot_by_slug(db, bot_slug)
    if not bot:
        return HTMLResponse("Bot not found", status_code=404)

    # Read client_id from the bot's YouTube credential
    yt_cred = db.query(SocialCredential).filter(
        SocialCredential.bot_id == bot.id,
        SocialCredential.platform == "youtube",
    ).first()

    if not yt_cred or not yt_cred.extra_data:
        return HTMLResponse(
            '<div class="flash-error">Primero configura YouTube Client ID y Secret '
            f'en <a href="/bots/{bot_slug}/edit">la edicion del bot</a>.</div>',
            status_code=400,
        )

    client_id, _ = _get_yt_oauth_keys(yt_cred)
    if not client_id:
        return HTMLResponse(
            '<div class="flash-error">YouTube Client ID no encontrado.</div>',
            status_code=400,
        )

    # Generate CSRF state token
    state = f"{bot_slug}:{secrets.token_urlsafe(32)}"
    _oauth_states[state] = bot_slug

    base_url = app_settings.app_base_url.rstrip("/")
    redirect_uri = f"{base_url}/auth/youtube/callback"

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": _YOUTUBE_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }

    return RedirectResponse(url=f"{_GOOGLE_AUTH_URL}?{urlencode(params)}")


@router.get("/auth/youtube/callback")
async def youtube_oauth_callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    db: Session = Depends(get_db),
):
    """Handle the OAuth callback from Google after user consent."""
    if error:
        return templates.TemplateResponse(request, "oauth_result.html", {
            "success": False,
            "message": f"YouTube rechazo la autorizacion: {error}",
        })

    # Validate CSRF state
    bot_slug = _oauth_states.pop(state, None)
    if not bot_slug:
        return templates.TemplateResponse(request, "oauth_result.html", {
            "success": False,
            "message": "Estado de OAuth invalido. Intenta de nuevo.",
        })

    bot = bot_manager.get_bot_by_slug(db, bot_slug)
    if not bot:
        return templates.TemplateResponse(request, "oauth_result.html", {
            "success": False,
            "message": f"Bot '{bot_slug}' no encontrado.",
        })

    # Get client keys from the bot's credential
    yt_cred = db.query(SocialCredential).filter(
        SocialCredential.bot_id == bot.id,
        SocialCredential.platform == "youtube",
    ).first()

    if not yt_cred:
        return templates.TemplateResponse(request, "oauth_result.html", {
            "success": False,
            "message": "Credencial YouTube no encontrada para este bot.",
        })

    client_id, client_secret = _get_yt_oauth_keys(yt_cred)
    base_url = app_settings.app_base_url.rstrip("/")
    redirect_uri = f"{base_url}/auth/youtube/callback"

    # Exchange authorization code for tokens
    import httpx
    async with httpx.AsyncClient(timeout=15.0) as http:
        resp = await http.post(_GOOGLE_TOKEN_URL, data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        })

    if resp.status_code != 200:
        return templates.TemplateResponse(request, "oauth_result.html", {
            "success": False,
            "message": f"Error al intercambiar codigo: {resp.text}",
        })

    token_data = resp.json()
    access_token = token_data.get("access_token", "")
    refresh_token_val = token_data.get("refresh_token", "")
    expires_in = token_data.get("expires_in", 3600)

    # Get the channel info
    channel_name = ""
    channel_id = ""
    async with httpx.AsyncClient(timeout=10.0) as http:
        ch_resp = await http.get(
            "https://www.googleapis.com/youtube/v3/channels",
            params={"part": "snippet", "mine": "true"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if ch_resp.status_code == 200:
            items = ch_resp.json().get("items", [])
            if items:
                channel_id = items[0]["id"]
                channel_name = items[0]["snippet"]["title"]

    # Update the credential with tokens
    encryptor = FieldEncryptor(app_settings.encryption_key)
    expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

    yt_cred.access_token_encrypted = encryptor.encrypt(access_token)
    if refresh_token_val:
        yt_cred.refresh_token_encrypted = encryptor.encrypt(refresh_token_val)
    yt_cred.token_expires_at = expires_at
    yt_cred.platform_user_id = channel_id or yt_cred.platform_user_id
    yt_cred.platform_username = channel_name or yt_cred.platform_username
    yt_cred.is_active = True

    db.commit()

    return templates.TemplateResponse(request, "oauth_result.html", {
        "success": True,
        "message": f"YouTube conectado: {channel_name or channel_id or 'canal autorizado'}",
        "bot_slug": bot_slug,
    })

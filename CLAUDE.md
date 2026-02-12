# GeneradorContenido

Multi-bot autonomous content generation system for social media (Instagram Reels, YouTube Shorts, TikTok). Each bot independently generates scripts via Gemini, produces videos via Veo3/Kling, gets human approval in the dashboard, then publishes.

## Tech Stack

- **Backend**: Python 3.9, FastAPI 0.115+
- **Frontend**: Jinja2 templates + HTMX 2.0.4 + Pico CSS 2.x (no React/Vue)
- **Database**: SQLite + SQLAlchemy 2.0 (sync sessions)
- **Migrations**: Alembic
- **Scheduling**: APScheduler (AsyncIOScheduler)
- **Encryption**: cryptography.fernet for API keys/tokens at rest
- **Testing**: pytest + starlette.testclient, in-memory SQLite with StaticPool

## Conventions

- **UI language**: Spanish (templates, labels, messages)
- **Code language**: English (variables, comments, docstrings)
- **Python 3.9**: use `from __future__ import annotations`, `Optional[X]` not `X | None`
- **Pydantic v2**: `model_config`, `.model_dump()` (not `.dict()`)
- **DB sessions**: sync SQLAlchemy (`db.commit()`, not `await db.commit()`)
- **Ruff**: line-length=100, target py39

## Key Directories

```
app/
  config.py              # Pydantic Settings (.env)
  database.py            # sync_engine + get_db() dependency
  main.py                # FastAPI app, lifespan, static mounts
  models/                # SQLAlchemy ORM: Bot, ContentItem, SocialCredential, PipelineLog, GlobalSetting
  schemas/               # Pydantic validation schemas
  routers/dashboard.py   # All HTML routes (settings, bots, content, approval)
  routers/webhooks.py    # Telegram webhook (kept but calls commented out)
  services/              # bot_manager, pipeline_orchestrator, publisher, scheduler_service,
                         # script_generator, video_generator, trend_scraper, settings_manager,
                         # telegram_approver (kept intact, calls commented out in orchestrator)
  integrations/          # HTTP clients: gemini, veo, kling, telegram, instagram, youtube, tiktok
  templates/             # Jinja2 HTML (base, dashboard, bot_*, content_*, settings, logs)
  static/css/style.css   # Custom styles on top of Pico CSS
  static/js/app.js       # Minimal JS (HTMX handles interactivity)
  utils/                 # encryption, file_storage, logging_config
tests/                   # pytest (conftest.py has in-memory DB + dependency overrides)
bot_templates/           # JSON templates per niche (fitness, tech, finance)
storage/videos/          # Generated videos (gitignored)
```

## Pipeline Architecture

Three-phase resumable pipeline in `pipeline_orchestrator.py`:

1. **Phase 1** `run_pipeline(bot, db)`: Topic selection (trends/custom) -> Script (Gemini) -> Video submission (Veo3/Kling)
2. **Phase 2** `resume_after_video(content, bot, db)`: Video download -> Descriptions (Gemini) -> Status: `pending_approval`
3. **Phase 3** `resume_after_approval(content, bot, db)`: Publish to all active platforms

Approval happens in the dashboard (content detail page). Telegram approval is available but commented out.

## Testing

```bash
.venv/bin/python -m pytest tests/ -v
```

- All tests use in-memory SQLite via `tests/conftest.py`
- External services mocked with `unittest.mock.AsyncMock` + `patch`
- `starlette.testclient.TestClient` for route tests (sync)

## Running

```bash
.venv/bin/uvicorn app.main:app --reload
# Open http://localhost:8000
```

## Global Settings

API keys (Gemini, Veo3, Kling, Telegram) are stored in the `global_settings` table and managed from `/settings`. Per-bot publishing credentials (IG/YT/TT tokens) are managed within each bot's edit page.

## Features

- **Story Arcs**: Multi-chapter sequential content (shared narrative across N videos). Enabled per bot. Each chapter is an independent ContentItem linked by `story_arc_id`.
- **Scene Extension**: Veo3 videos longer than 8s via iterative scene extension API (8s initial + N×7s extensions, up to 148s).

## Proyecto Principal: Personaje IA Consistente (MadridGirl)

**Objetivo**: Crear una influencer virtual IA -- una rubia madridista que comenta noticias del Real Madrid con humor. Es el motor principal y esqueleto para futuros bots de personaje consistente.

**Concepto del personaje**:
- Mujer rubia, fan del Real Madrid
- Siempre la misma cara/cuerpo/estilo visual (consistencia total entre videos)
- Comenta noticias, partidos, fichajes del Real Madrid
- Tono humoristico y cercano
- Contenido basado en trending topics + noticias deportivas

**Requisitos tecnicos clave**:
- Consistencia facial: misma persona en TODOS los videos (requiere face reference o talking head API)
- Medidas faciales/corporales definidas para replicabilidad
- Voz IA consistente
- Scraping de noticias del Real Madrid en tiempo real
- Script generation con personalidad definida
- Auto-mejora de prompts: sistema que analiza rendimiento (views, likes, engagement) y ajusta automaticamente los prompts de generacion para mejorar con el tiempo

**Stack tecnico decidido**:
- Cara: Flux 2 (BFL API) -- fotorrealista, multi-referencia para consistencia
- Voz: ElevenLabs (Multilingual v2) -- mejor calidad espanol, clonacion de voz
- Talking Head: Hedra Character-3 -- foto+audio→video con lip sync ($0.38-0.75/min, 720p, suficiente para Reels/Shorts)
- Script: Gemini (ya integrado) con personalidad y contexto de noticias
- Noticias: RSS (Marca/AS), Reddit (r/realmadrid), Football-Data.org (gratis, La Liga incluida, team_id=86), GNews, Pytrends
- Partidos: Football-Data.org gratis o API-Football ($19/mo, team_id=541)
- Fichajes: transfermarkt-api self-hosted (club_id=418)
- Auto-mejora: feedback loop con metricas de engagement → Gemini analiza top performers → ajusta prompts

**Pipeline del personaje**:
1. News scraper obtiene noticias/trending del Madrid
2. Gemini genera script humoristico con personalidad del personaje
3. ElevenLabs genera audio con voz consistente
4. Hedra genera video (foto referencia + audio → talking head con lip sync)
5. Post-procesamiento (subtitulos, overlays)
6. Dashboard approval → Publicacion (IG/YT/TT)

**Fases de implementacion**:
- Fase 1: Character sheet (cara Flux 2 + voz ElevenLabs + personality prompt)
- Fase 2: Integrar ElevenLabs + Hedra en pipeline (nuevo video_provider "talking_head")
- Fase 3: News feed del Madrid (RSS + Reddit + Football-Data.org + GNews)
- Fase 4: Auto-mejora de prompts (engagement tracking + Gemini feedback loop)
- Fase 5: Pulir y escalar (mas personajes, A/B testing)

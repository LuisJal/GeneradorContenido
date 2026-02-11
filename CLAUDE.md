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

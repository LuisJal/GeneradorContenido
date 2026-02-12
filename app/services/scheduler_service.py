"""APScheduler service -- schedules content generation jobs for active bots.

Responsibilities:
- On startup: schedule a job for each enabled bot based on its posting_schedule.
- On bot toggle/update: reschedule or remove the job.
- Video polling job: periodically check in-progress video tasks.
- Manual trigger: ``trigger_now(bot_id)`` for the "Run Now" dashboard button.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import List, Optional, Union

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import Session

from app.models.bot import Bot
from app.models.content import ContentItem, ContentStatus
from app.services import pipeline_orchestrator
from app.utils.logging_config import get_logger

logger = get_logger("scheduler")

# Module-level scheduler instance -- initialized in lifespan
scheduler: Optional[AsyncIOScheduler] = None


def init_scheduler() -> AsyncIOScheduler:
    """Create and return the AsyncIOScheduler instance."""
    global scheduler
    scheduler = AsyncIOScheduler()
    return scheduler


def get_scheduler() -> AsyncIOScheduler:
    """Return the current scheduler instance."""
    if scheduler is None:
        raise RuntimeError("Scheduler not initialized. Call init_scheduler() first.")
    return scheduler


# ------------------------------------------------------------------
# Job functions
# ------------------------------------------------------------------


async def _run_bot_pipeline(bot_id: int) -> None:
    """Job callback: run Phase 1 of the pipeline for a bot.

    Creates its own DB session since APScheduler jobs run outside
    the FastAPI request lifecycle.
    """
    from app.database import get_db

    logger.info("Scheduler triggered pipeline for bot_id=%d", bot_id)

    db_gen = get_db()
    db = next(db_gen)
    try:
        bot = db.query(Bot).filter(Bot.id == bot_id).first()
        if bot is None:
            logger.warning("Bot %d not found, skipping scheduled run", bot_id)
            return
        if not bot.is_enabled:
            logger.info("Bot %d is disabled, skipping scheduled run", bot_id)
            return

        if bot.story_arc_enabled:
            await pipeline_orchestrator.run_story_arc_pipeline(bot, db)
            logger.info("Story arc pipeline completed for bot_id=%d", bot_id)
        else:
            await pipeline_orchestrator.run_pipeline(bot, db)
            logger.info("Pipeline Phase 1 completed for bot_id=%d", bot_id)
    except Exception:
        logger.exception("Scheduled pipeline failed for bot_id=%d", bot_id)
    finally:
        try:
            next(db_gen, None)
        except StopIteration:
            pass


async def _poll_pending_videos() -> None:
    """Job callback: check all content items waiting for video generation.

    Runs Phase 2 (resume_after_video) for each item still in VIDEO_POLLING.
    """
    from app.database import get_db

    db_gen = get_db()
    db = next(db_gen)
    try:
        items = (
            db.query(ContentItem)
            .filter(ContentItem.status == ContentStatus.VIDEO_POLLING.value)
            .all()
        )

        if not items:
            return

        logger.info("Polling %d pending video(s)", len(items))

        for item in items:
            bot = db.query(Bot).filter(Bot.id == item.bot_id).first()
            if bot is None:
                continue
            try:
                await pipeline_orchestrator.resume_after_video(item, bot, db)
            except Exception:
                logger.exception(
                    "Video polling failed for content_id=%d", item.id
                )
    finally:
        try:
            next(db_gen, None)
        except StopIteration:
            pass


# ------------------------------------------------------------------
# Scheduling management
# ------------------------------------------------------------------


def _job_id_for_bot(bot_id: int) -> str:
    """Consistent job ID for a bot's scheduled pipeline."""
    return f"bot_pipeline_{bot_id}"


def schedule_bot(bot: Bot) -> None:
    """Add or update a scheduled job for a bot.

    Reads ``bot.posting_schedule`` which has format:
    ``{"times": ["09:00", "18:00"], "timezone": "Europe/Madrid"}``
    """
    sched = get_scheduler()
    job_id = _job_id_for_bot(bot.id)

    # Remove existing job if any
    existing = sched.get_job(job_id)
    if existing:
        sched.remove_job(job_id)

    if not bot.is_enabled:
        logger.info("Bot %d is disabled, not scheduling", bot.id)
        return

    schedule = bot.posting_schedule or {}
    times = schedule.get("times", ["09:00"])
    timezone = schedule.get("timezone", "Europe/Madrid")

    # Schedule one job per configured time
    for i, time_str in enumerate(times):
        parts = time_str.split(":")
        hour = int(parts[0]) if len(parts) >= 1 else 9
        minute = int(parts[1]) if len(parts) >= 2 else 0

        this_job_id = f"{job_id}_{i}" if i > 0 else job_id

        sched.add_job(
            _run_bot_pipeline,
            trigger=CronTrigger(hour=hour, minute=minute, timezone=timezone),
            args=[bot.id],
            id=this_job_id,
            replace_existing=True,
            name=f"Pipeline {bot.name} @ {time_str}",
        )
        logger.info(
            "Scheduled bot '%s' (id=%d) at %s %s [job=%s]",
            bot.name, bot.id, time_str, timezone, this_job_id,
        )


def unschedule_bot(bot_id: int) -> None:
    """Remove all scheduled jobs for a bot."""
    sched = get_scheduler()
    job_id = _job_id_for_bot(bot_id)

    # Remove main job and any additional time slots
    for suffix in ["", "_1", "_2", "_3", "_4", "_5"]:
        jid = f"{job_id}{suffix}"
        if sched.get_job(jid):
            sched.remove_job(jid)
            logger.info("Unscheduled job %s", jid)


def schedule_video_polling() -> None:
    """Add the periodic video polling job (runs every 30 seconds)."""
    sched = get_scheduler()
    sched.add_job(
        _poll_pending_videos,
        trigger=IntervalTrigger(seconds=30),
        id="video_polling",
        replace_existing=True,
        name="Video polling (every 30s)",
    )
    logger.info("Video polling job scheduled (every 30s)")


def schedule_all_bots(db: Session) -> None:
    """Schedule jobs for all enabled bots. Called at startup."""
    bots = db.query(Bot).filter(Bot.is_enabled == True).all()
    for bot in bots:
        schedule_bot(bot)
    logger.info("Scheduled %d enabled bot(s)", len(bots))


# ------------------------------------------------------------------
# Manual trigger
# ------------------------------------------------------------------


async def trigger_now(
    bot: Bot, db: Session
) -> Union[ContentItem, List[ContentItem]]:
    """Immediately run the pipeline for a bot (the "Run Now" button).

    If the bot has story arcs enabled, generates all chapters sequentially.
    Returns the created ContentItem(s).
    """
    logger.info("Manual trigger: running pipeline for bot '%s'", bot.name)
    if bot.story_arc_enabled:
        return await pipeline_orchestrator.run_story_arc_pipeline(bot, db)
    return await pipeline_orchestrator.run_pipeline(bot, db)

"""Pipeline orchestrator -- connects all steps of content generation.

The pipeline runs in three resumable phases:

1. ``run_pipeline(bot_id)`` -- topic selection, script generation, video
   submission.  Pauses after submitting the video (async generation).
2. ``resume_after_video(content_id)`` -- checks video status, downloads it,
   generates descriptions, sends to Telegram for approval.
3. ``resume_after_approval(content_id)`` -- publishes to all connected social
   platforms (Instagram Reels, YouTube Shorts, TikTok).
"""
from __future__ import annotations

import json
import traceback
from typing import Optional

from sqlalchemy.orm import Session

from app.models.bot import Bot
from app.models.content import ContentItem, ContentStatus
from app.models.log_entry import PipelineLog
from app.services import script_generator, video_generator, telegram_approver, publisher
from app.services.trend_scraper import get_trending_topics, select_unused_topic
from app.utils.logging_config import get_logger

logger = get_logger("pipeline")


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _log(
    db: Session,
    bot_id: int,
    content_id: Optional[int],
    stage: str,
    message: str,
    level: str = "INFO",
    extra: Optional[dict] = None,
) -> None:
    """Write a structured log entry to the pipeline_logs table."""
    entry = PipelineLog(
        bot_id=bot_id,
        content_id=content_id,
        level=level,
        stage=stage,
        message=message,
        extra_data=extra,
    )
    db.add(entry)
    db.commit()
    logger.log(
        {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}.get(level, 20),
        "[%s] content=%s stage=%s: %s",
        level,
        content_id,
        stage,
        message,
    )


def _set_status(
    db: Session,
    content: ContentItem,
    status: ContentStatus,
) -> None:
    """Update content status and commit."""
    content.status = status.value
    db.commit()


def _set_error(
    db: Session,
    content: ContentItem,
    error_message: str,
) -> None:
    """Mark content as failed with an error message."""
    content.status = ContentStatus.FAILED.value
    content.error_message = error_message
    content.retry_count = (content.retry_count or 0) + 1
    db.commit()


def _select_topic(bot: Bot, db: Session) -> str:
    """Select the next topic for content generation.

    If ``bot.use_trends`` is True, scrapes Google Trends and Reddit to find
    a fresh topic.  Otherwise cycles through ``bot.custom_prompts``.
    """
    if bot.use_trends:
        try:
            topics = get_trending_topics(bot)
            if topics:
                topic = select_unused_topic(bot, db, topics)
                if topic:
                    return topic
        except Exception as exc:
            logger.warning("Trend scraping failed, falling back: %s", exc)

    if bot.custom_prompts:
        prompts = bot.custom_prompts
        if isinstance(prompts, list) and prompts:
            return prompts[0]

    return f"Contenido sobre {bot.niche}"


# ------------------------------------------------------------------
# Phase 1: Topic -> Script -> Video submission
# ------------------------------------------------------------------


async def run_pipeline(bot: Bot, db: Session) -> ContentItem:
    """Execute Phase 1 of the pipeline for the given bot.

    Steps:
    1. Select topic (trends or custom prompts)
    2. Generate script via Gemini
    3. Generate video prompt from script
    4. Submit video generation request

    Returns the created ``ContentItem`` in ``video_polling`` status.
    """
    # 1. Create content item
    content = ContentItem(bot_id=bot.id)
    db.add(content)
    db.commit()

    content_id = content.id
    _log(db, bot.id, content_id, "pipeline_start", f"Pipeline started for bot '{bot.name}'")

    try:
        # 2. Topic selection
        _set_status(db, content, ContentStatus.TREND_SCRAPING)
        topic = _select_topic(bot, db)
        content.trend_topic = topic
        db.commit()
        _log(db, bot.id, content_id, "topic_selected", f"Topic: {topic}")

        # 3. Script generation
        _set_status(db, content, ContentStatus.SCRIPT_GENERATING)
        script = await script_generator.generate_content_script(bot, topic)
        content.script = json.dumps(script, ensure_ascii=False)
        _set_status(db, content, ContentStatus.SCRIPT_READY)
        _log(db, bot.id, content_id, "script_generated", "Script generated successfully")

        # 4. Video prompt generation
        video_prompt = await script_generator.generate_video_prompt(bot, script)
        content.video_prompt = video_prompt
        db.commit()
        _log(db, bot.id, content_id, "video_prompt_generated", "Video prompt ready")

        # 5. Submit video generation
        _set_status(db, content, ContentStatus.VIDEO_GENERATING)
        task_id = await video_generator.submit_video_generation(
            bot, video_prompt, content_id
        )
        content.video_task_id = task_id
        content.video_provider = bot.video_provider
        _set_status(db, content, ContentStatus.VIDEO_POLLING)
        _log(db, bot.id, content_id, "video_submitted", f"Video task: {task_id}")

        return content

    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        _set_error(db, content, error_msg)
        _log(db, bot.id, content_id, "pipeline_error", error_msg, level="ERROR")
        # Notify via Telegram if possible
        try:
            await telegram_approver.notify_error(bot, content, error_msg)
        except Exception:
            pass
        raise


# ------------------------------------------------------------------
# Phase 2: Video ready -> Descriptions -> Telegram approval
# ------------------------------------------------------------------


async def resume_after_video(content: ContentItem, bot: Bot, db: Session) -> ContentItem:
    """Execute Phase 2 after the video has been generated.

    Steps:
    1. Check video status / download
    2. Generate platform descriptions
    3. Send to Telegram for approval

    Returns the ``ContentItem`` in ``pending_approval`` status.
    """
    content_id = content.id
    _log(db, bot.id, content_id, "phase2_start", "Resuming after video generation")

    try:
        # 1. Check video and download
        result = await video_generator.check_video_status(bot, content.video_task_id)

        if result["status"] == "failed":
            error_msg = result.get("error", "Video generation failed")
            _set_error(db, content, error_msg)
            _log(db, bot.id, content_id, "video_failed", error_msg, level="ERROR")
            await telegram_approver.notify_error(bot, content, error_msg)
            return content

        if result["status"] != "completed":
            _log(db, bot.id, content_id, "video_still_processing", "Video not ready yet")
            return content

        # Download the video
        video_url = result["video_url"]
        local_path = await video_generator.download_video(bot, video_url, content_id)
        content.video_file_path = local_path
        content.video_url = video_url
        _set_status(db, content, ContentStatus.VIDEO_READY)
        _log(db, bot.id, content_id, "video_downloaded", f"Video at: {local_path}")

        # 2. Generate descriptions
        _set_status(db, content, ContentStatus.DESCRIPTIONS_GENERATING)
        script = json.loads(content.script) if content.script else {}
        topic = content.trend_topic or ""

        descriptions = await script_generator.generate_content_descriptions(
            bot, script, topic
        )

        content.description_instagram = descriptions.get("instagram", "")
        youtube = descriptions.get("youtube", {})
        if isinstance(youtube, dict):
            yt_parts = []
            if youtube.get("title"):
                yt_parts.append(youtube["title"])
            if youtube.get("description"):
                yt_parts.append(youtube["description"])
            if youtube.get("tags"):
                yt_parts.append("Tags: " + ", ".join(youtube["tags"]))
            content.description_youtube = "\n\n".join(yt_parts)
        else:
            content.description_youtube = str(youtube)
        content.description_tiktok = descriptions.get("tiktok", "")
        db.commit()
        _log(db, bot.id, content_id, "descriptions_generated", "Descriptions ready")

        # 3. Send for approval
        _set_status(db, content, ContentStatus.PENDING_APPROVAL)
        content.approval_status = "pending"
        message_id = await telegram_approver.send_content_for_approval(bot, content)
        content.telegram_message_id = message_id
        db.commit()
        _log(db, bot.id, content_id, "sent_for_approval", f"Telegram message: {message_id}")

        return content

    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        _set_error(db, content, error_msg)
        _log(db, bot.id, content_id, "phase2_error", error_msg, level="ERROR")
        try:
            await telegram_approver.notify_error(bot, content, error_msg)
        except Exception:
            pass
        raise


# ------------------------------------------------------------------
# Phase 3: Approved -> Publish
# ------------------------------------------------------------------


async def resume_after_approval(content: ContentItem, bot: Bot, db: Session) -> ContentItem:
    """Execute Phase 3 after human approval via Telegram.

    Steps:
    1. Publish to each connected platform
    2. Notify operator with publish links

    Returns the ``ContentItem`` in ``published`` or ``partially_published`` status.
    """
    content_id = content.id
    _log(db, bot.id, content_id, "phase3_start", "Publishing approved content")

    if content.approval_status != "approved":
        _log(db, bot.id, content_id, "not_approved",
             f"Skipping publish: approval_status={content.approval_status}", level="WARNING")
        return content

    _set_status(db, content, ContentStatus.PUBLISHING)

    results = await publisher.publish_to_all(bot, content, db)

    total_active = sum(1 for c in bot.credentials if c.is_active)
    published_count = len(results)

    # Final status
    if total_active == 0:
        _set_status(db, content, ContentStatus.PUBLISHED)
        _log(db, bot.id, content_id, "published",
             "No active platform credentials; marked as published")
    elif published_count == total_active:
        _set_status(db, content, ContentStatus.PUBLISHED)
        _log(db, bot.id, content_id, "published",
             f"Published to all {total_active} platforms: {results}")
    elif published_count > 0:
        _set_status(db, content, ContentStatus.PARTIALLY_PUBLISHED)
        _log(db, bot.id, content_id, "partially_published",
             f"Published to {published_count}/{total_active} platforms: {results}",
             level="WARNING")
    else:
        _set_status(db, content, ContentStatus.FAILED)
        _log(db, bot.id, content_id, "publish_failed",
             "Failed to publish to any platform", level="ERROR")

    # Notify via Telegram
    try:
        from datetime import datetime
        content.completed_at = datetime.utcnow()
        db.commit()
        await telegram_approver.notify_published(bot, content)
    except Exception:
        logger.exception("Failed to send publish notification")

    return content

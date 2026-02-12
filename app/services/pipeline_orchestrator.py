"""Pipeline orchestrator -- connects all steps of content generation.

The pipeline runs in three resumable phases:

1. ``run_pipeline(bot_id)`` -- topic selection, script generation, video
   submission.  Pauses after submitting the video (async generation).
2. ``resume_after_video(content_id)`` -- checks video status, downloads it,
   generates descriptions, marks as pending dashboard approval.
3. ``resume_after_approval(content_id)`` -- publishes to all connected social
   platforms (Instagram Reels, YouTube Shorts, TikTok).
"""
from __future__ import annotations

import asyncio
import json
import traceback
import uuid
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.bot import Bot
from app.models.content import ContentItem, ContentStatus
from app.models.log_entry import PipelineLog
# --- TELEGRAM COMMENTED OUT --- (approval now via dashboard)
# from app.services import script_generator, video_generator, telegram_approver, publisher
from app.services import script_generator, video_generator, publisher
from app.services.trend_scraper import get_trending_topics, select_unused_topic
from app.utils.file_storage import get_audio_path
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


def _settings_session():
    """Create a short-lived sync Session for reading global settings."""
    from sqlalchemy.orm import Session as OrmSession
    from app.database import sync_engine
    return OrmSession(sync_engine)


async def _generate_tts_audio(
    bot: Bot, content: ContentItem, script: dict, db: Session
) -> str:
    """Generate TTS audio from script text via ElevenLabs.

    Returns the local file path where the audio was saved.
    """
    from app.integrations.elevenlabs_client import ElevenLabsClient
    from app.services.settings_manager import get_setting

    sess = _settings_session()
    try:
        api_key = get_setting(sess, "elevenlabs_api_key")
    finally:
        sess.close()

    if not api_key:
        raise ValueError("ElevenLabs API key not configured. Set it in Settings.")

    voice_id = bot.character_voice_id
    if not voice_id:
        raise ValueError("Bot has no character_voice_id for TTS.")

    # Build speech text from script parts
    parts = []
    for key in ("hook", "body", "cta"):
        if script.get(key):
            parts.append(script[key])
    text = " ".join(parts).strip()
    if not text:
        raise ValueError("Script has no text to synthesise.")

    output_path = str(get_audio_path(bot.slug, content.id))

    client = ElevenLabsClient(api_key=api_key)
    saved = await client.text_to_speech(
        text=text,
        voice_id=voice_id,
        output_path=output_path,
        language_code=bot.language or "es",
    )
    content.audio_file_path = saved
    db.commit()
    return saved


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

        # 5. TTS audio generation (talking_head provider only)
        audio_path = None
        if bot.video_provider == "talking_head":
            _log(db, bot.id, content_id, "tts_generating", "Generating TTS audio")
            audio_path = await _generate_tts_audio(bot, content, script, db)
            _log(db, bot.id, content_id, "tts_generated", f"Audio at: {audio_path}")

        # 6. Submit video generation
        _set_status(db, content, ContentStatus.VIDEO_GENERATING)
        task_id = await video_generator.submit_video_generation(
            bot, video_prompt, content_id, audio_path=audio_path
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
        # --- TELEGRAM COMMENTED OUT ---
        # try:
        #     await telegram_approver.notify_error(bot, content, error_msg)
        # except Exception:
        #     pass
        logger.error("Pipeline error for bot %s: %s", bot.name, error_msg)
        raise


# ------------------------------------------------------------------
# Story Arc: sequential multi-chapter generation
# ------------------------------------------------------------------


async def run_story_arc_pipeline(bot: Bot, db: Session) -> List[ContentItem]:
    """Generate all chapters of a story arc sequentially.

    Each chapter goes through Phase 1 (script + video submission).
    Later chapters receive previous scripts/prompts for continuity.
    The existing video polling job handles Phase 2 for each item.

    Returns a list of ContentItem objects (one per chapter).
    """
    total = bot.story_arc_chapters or 3
    arc_id = uuid.uuid4().hex[:8]

    # 1. Select topic (shared across all chapters)
    topic = _select_topic(bot, db)

    _log(db, bot.id, None, "story_arc_start",
         f"Starting story arc '{arc_id}' ({total} chapters): {topic}")

    # 2. Generate the story arc premise
    premise = await script_generator.generate_story_arc_premise(bot, topic, total)

    _log(db, bot.id, None, "arc_premise_generated",
         f"Arc premise generated (length={len(premise)})")

    items: List[ContentItem] = []
    previous_scripts: List[dict] = []
    previous_video_prompts: List[str] = []

    for chapter in range(1, total + 1):
        content = ContentItem(
            bot_id=bot.id,
            story_arc_id=arc_id,
            story_arc_chapter=chapter,
            story_arc_total=total,
            story_arc_premise=premise,
            trend_topic=topic,
        )
        db.add(content)
        db.commit()

        content_id = content.id
        _log(db, bot.id, content_id, "arc_chapter_start",
             f"Generating chapter {chapter}/{total} of arc '{arc_id}'")

        try:
            # Script generation with arc context
            _set_status(db, content, ContentStatus.SCRIPT_GENERATING)
            script = await script_generator.generate_content_script(
                bot, topic,
                arc_premise=premise,
                arc_chapter=chapter,
                arc_total=total,
                previous_scripts=list(previous_scripts),
            )
            content.script = json.dumps(script, ensure_ascii=False)
            _set_status(db, content, ContentStatus.SCRIPT_READY)
            _log(db, bot.id, content_id, "script_generated",
                 f"Chapter {chapter} script ready")

            # Video prompt with arc context
            video_prompt = await script_generator.generate_video_prompt(
                bot, script,
                arc_premise=premise,
                arc_chapter=chapter,
                arc_total=total,
                previous_video_prompts=list(previous_video_prompts),
            )
            content.video_prompt = video_prompt
            db.commit()
            _log(db, bot.id, content_id, "video_prompt_generated",
                 f"Chapter {chapter} video prompt ready")

            # TTS audio generation (talking_head provider only)
            audio_path = None
            if bot.video_provider == "talking_head":
                audio_path = await _generate_tts_audio(bot, content, script, db)
                _log(db, bot.id, content_id, "tts_generated",
                     f"Chapter {chapter} audio ready")

            # Submit video generation
            _set_status(db, content, ContentStatus.VIDEO_GENERATING)
            task_id = await video_generator.submit_video_generation(
                bot, video_prompt, content_id, audio_path=audio_path
            )
            content.video_task_id = task_id
            content.video_provider = bot.video_provider
            _set_status(db, content, ContentStatus.VIDEO_POLLING)
            _log(db, bot.id, content_id, "video_submitted",
                 f"Chapter {chapter}/{total} task={task_id}")

            # Track for next chapter's context
            previous_scripts.append(script)
            previous_video_prompts.append(video_prompt)
            items.append(content)

        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {exc}"
            _set_error(db, content, error_msg)
            _log(db, bot.id, content_id, "arc_chapter_error",
                 error_msg, level="ERROR")
            items.append(content)
            break  # Stop generating further chapters if one fails

        # Brief pause between chapters to avoid Gemini rate limits
        if chapter < total:
            await asyncio.sleep(2)

    _log(db, bot.id, None, "story_arc_submitted",
         f"Arc '{arc_id}': {len([i for i in items if i.status == ContentStatus.VIDEO_POLLING.value])}/{total} chapters submitted")

    return items


# ------------------------------------------------------------------
# Phase 2: Video ready -> Descriptions -> Dashboard approval
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
            # --- TELEGRAM COMMENTED OUT ---
            # await telegram_approver.notify_error(bot, content, error_msg)
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
            bot, script, topic,
            arc_chapter=content.story_arc_chapter,
            arc_total=content.story_arc_total,
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

        # 3. Mark as pending approval (approval now via dashboard)
        _set_status(db, content, ContentStatus.PENDING_APPROVAL)
        content.approval_status = "pending"
        db.commit()
        _log(db, bot.id, content_id, "pending_approval",
             "Content ready for dashboard approval")
        # --- TELEGRAM COMMENTED OUT ---
        # message_id = await telegram_approver.send_content_for_approval(bot, content)
        # content.telegram_message_id = message_id
        # db.commit()
        # _log(db, bot.id, content_id, "sent_for_approval", f"Telegram message: {message_id}")

        return content

    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        _set_error(db, content, error_msg)
        _log(db, bot.id, content_id, "phase2_error", error_msg, level="ERROR")
        # --- TELEGRAM COMMENTED OUT ---
        # try:
        #     await telegram_approver.notify_error(bot, content, error_msg)
        # except Exception:
        #     pass
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

    # Mark completion
    from datetime import datetime
    content.completed_at = datetime.utcnow()
    db.commit()
    # --- TELEGRAM COMMENTED OUT ---
    # try:
    #     await telegram_approver.notify_published(bot, content)
    # except Exception:
    #     logger.exception("Failed to send publish notification")

    return content

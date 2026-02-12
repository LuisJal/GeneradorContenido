from __future__ import annotations

import asyncio
from typing import List, Optional

from app.config import settings
from app.integrations.gemini_client import GeminiClient, GeminiClientError
from app.models.bot import Bot
from app.utils.encryption import FieldEncryptor
from app.utils.logging_config import get_logger

logger = get_logger("script_generator")


def _resolve_api_key(bot: Bot) -> str:
    """Return the decrypted per-bot Gemini API key, falling back to the global one."""
    if bot.gemini_api_key_encrypted:
        encryptor = FieldEncryptor(settings.encryption_key)
        key = encryptor.decrypt(bot.gemini_api_key_encrypted)
        if key:
            return key
    if settings.gemini_api_key:
        return settings.gemini_api_key
    raise GeminiClientError(
        f"No Gemini API key configured for bot '{bot.name}' and no global key set."
    )


def _build_system_prompt(bot: Bot) -> str:
    """Assemble the system prompt from the bot's configuration fields.

    If the bot has a custom ``script_system_prompt`` it is used as the base.
    Additional context about the niche, style, and language is appended
    automatically so the model always has enough guidance.
    """
    parts: list[str] = []

    if bot.script_system_prompt:
        parts.append(bot.script_system_prompt)
    else:
        parts.append(
            "You are an expert short-form video scriptwriter for social media. "
            "Generate engaging scripts for vertical (9:16) videos."
        )

    # Enrich with bot-level metadata
    if bot.niche:
        parts.append(f"Content niche: {bot.niche}.")
    if bot.niche_description:
        parts.append(f"Niche details: {bot.niche_description}")
    if bot.content_style:
        parts.append(f"Content style: {bot.content_style}")
    if bot.language:
        parts.append(f"Output language: {bot.language}.")
    if bot.video_duration_seconds:
        parts.append(
            f"Target video duration: {bot.video_duration_seconds} seconds."
        )

    return "\n".join(parts)


def _get_client(bot: Bot) -> GeminiClient:
    """Instantiate a :class:`GeminiClient` configured for the given bot."""
    api_key = _resolve_api_key(bot)
    model = bot.gemini_model or "gemini-2.5-flash"
    return GeminiClient(api_key=api_key, model=model)


# ------------------------------------------------------------------
# Public async interface
# ------------------------------------------------------------------


async def generate_story_arc_premise(
    bot: Bot, topic: str, total_chapters: int
) -> str:
    """Generate a high-level story premise for a multi-part arc.

    Returns a 2-3 paragraph synopsis covering all chapters: characters,
    setting, conflict, and how it resolves across the parts.
    """
    logger.info(
        "Generating arc premise for bot='%s' topic='%s' chapters=%d",
        bot.name, topic, total_chapters,
    )
    client = _get_client(bot)
    system_prompt = _build_system_prompt(bot)

    user_prompt = (
        f"Create a story premise for a {total_chapters}-part short-form video series "
        f"about: {topic}\n\n"
        f"Each part is {bot.video_duration_seconds} seconds long.\n\n"
        f"The premise must include:\n"
        f"1. Main character(s) with specific visual descriptions "
        f"(appearance, clothing, age, distinguishing features)\n"
        f"2. Setting/location (specific and consistent across all parts)\n"
        f"3. The overall conflict or narrative question\n"
        f"4. How the story arc progresses across all {total_chapters} parts "
        f"(Part 1: setup, Part 2: complication, Part 3: resolution)\n\n"
        f"Write 2-3 paragraphs. Be specific about visual details so video "
        f"prompts can maintain consistency across all parts."
    )

    try:
        premise = await asyncio.to_thread(
            client.generate_text, system_prompt, user_prompt
        )
        logger.info("Arc premise generated for bot='%s' (length=%d)", bot.name, len(premise))
        return premise
    except GeminiClientError:
        raise
    except Exception as exc:
        logger.error("Unexpected error generating arc premise: %s", exc)
        raise GeminiClientError(
            f"Arc premise generation failed for bot '{bot.name}': {exc}"
        ) from exc


async def generate_content_script(
    bot: Bot,
    topic: str,
    *,
    arc_premise: Optional[str] = None,
    arc_chapter: Optional[int] = None,
    arc_total: Optional[int] = None,
    previous_scripts: Optional[List[dict]] = None,
) -> dict:
    """Generate a structured video script for *topic* using the bot's config.

    Returns a dict with keys: ``hook``, ``body``, ``cta``, ``visual_cues``.
    """
    logger.info("Generating script for bot='%s' topic='%s'", bot.name, topic)

    client = _get_client(bot)
    system_prompt = _build_system_prompt(bot)

    user_prompt = (
        f"Create a short-form video script about the following topic:\n\n"
        f"{topic}\n\n"
    )

    if arc_premise and arc_chapter and arc_total:
        user_prompt += (
            f"--- STORY ARC CONTEXT ---\n"
            f"This is Part {arc_chapter} of {arc_total} in a multi-part story.\n"
            f"Overall story premise:\n{arc_premise}\n\n"
        )
        if previous_scripts:
            for i, prev in enumerate(previous_scripts, 1):
                user_prompt += (
                    f"Part {i} script (already generated):\n"
                    f"  Hook: {prev.get('hook', '')}\n"
                    f"  Body: {prev.get('body', '')}\n"
                    f"  CTA: {prev.get('cta', '')}\n\n"
                )
        if arc_chapter < arc_total:
            user_prompt += (
                f"END this part with a cliffhanger or unresolved moment that "
                f"makes viewers want to watch Part {arc_chapter + 1}.\n"
                f"The CTA should tell viewers to watch the next part.\n\n"
            )
        else:
            user_prompt += (
                f"This is the FINAL part. Resolve the story satisfyingly.\n"
                f"The CTA should tell viewers to watch from Part 1 if they "
                f"haven't, or follow for more stories.\n\n"
            )

    user_prompt += (
        f"The script must contain:\n"
        f"1. A powerful hook for the first 2 seconds that grabs attention.\n"
        f"2. A concise body that delivers value.\n"
        f"3. A clear call-to-action (CTA).\n"
        f"4. Visual cues describing what should appear on screen for each section."
    )

    # The SDK calls are synchronous; run them in a thread so we don't block
    # the async event loop.
    try:
        script = await asyncio.to_thread(
            client.generate_script, system_prompt, user_prompt
        )
        logger.info("Script generation complete for bot='%s'", bot.name)
        return script
    except GeminiClientError:
        raise
    except Exception as exc:
        logger.error("Unexpected error generating script: %s", exc)
        raise GeminiClientError(
            f"Script generation failed for bot '{bot.name}': {exc}"
        ) from exc


async def generate_production_document(
    bot: Bot,
    topic: str,
    *,
    arc_premise: Optional[str] = None,
    arc_chapter: Optional[int] = None,
    arc_total: Optional[int] = None,
    previous_scripts: Optional[List[dict]] = None,
) -> dict:
    """Generate a full production document using the master prompt builder.

    Returns a dict matching the storyboard or talking_head schema depending
    on ``bot.production_mode``.
    """
    from app.services.master_prompt_builder import build_master_system_prompt

    logger.info(
        "Generating production document for bot='%s' topic='%s' mode='%s'",
        bot.name, topic, bot.production_mode,
    )

    client = _get_client(bot)
    system_prompt = build_master_system_prompt(bot)

    user_prompt = f"Create a production document for this topic:\n\n{topic}\n\n"

    if arc_premise and arc_chapter and arc_total:
        user_prompt += (
            f"--- STORY ARC CONTEXT ---\n"
            f"This is Part {arc_chapter} of {arc_total} in a multi-part story.\n"
            f"Overall story premise:\n{arc_premise}\n\n"
        )
        if previous_scripts:
            for i, prev in enumerate(previous_scripts, 1):
                user_prompt += (
                    f"Part {i} title: {prev.get('title', '')}\n"
                    f"Part {i} hook: {prev.get('hook', '')}\n\n"
                )
        if arc_chapter < arc_total:
            user_prompt += (
                f"END this part with a cliffhanger. "
                f"The CTA should tell viewers to watch Part {arc_chapter + 1}.\n\n"
            )
        else:
            user_prompt += (
                "This is the FINAL part. Resolve the story satisfyingly.\n\n"
            )

    user_prompt += (
        "Generate the full production document following the output format "
        "specified in your instructions."
    )

    mode = bot.production_mode or "storyboard"
    try:
        doc = await asyncio.to_thread(
            client.generate_production_document, system_prompt, user_prompt, mode
        )
        logger.info(
            "Production document generated for bot='%s' (scenes=%d)",
            bot.name, len(doc.get("storyboard", [])),
        )
        return doc
    except GeminiClientError:
        raise
    except Exception as exc:
        logger.error("Unexpected error generating production document: %s", exc)
        raise GeminiClientError(
            f"Production document generation failed for bot '{bot.name}': {exc}"
        ) from exc


async def generate_content_descriptions(
    bot: Bot,
    script: dict,
    topic: str,
    *,
    arc_chapter: Optional[int] = None,
    arc_total: Optional[int] = None,
) -> dict:
    """Generate platform-specific descriptions (Instagram, YouTube, TikTok).

    Returns a dict with keys: ``instagram``, ``youtube``, ``tiktok``.
    """
    logger.info("Generating descriptions for bot='%s' topic='%s'", bot.name, topic)

    client = _get_client(bot)
    niche = bot.niche or "general"

    try:
        descriptions = await asyncio.to_thread(
            client.generate_descriptions, script, topic, niche,
            arc_chapter=arc_chapter, arc_total=arc_total,
        )
        logger.info("Descriptions generated for bot='%s'", bot.name)
        return descriptions
    except GeminiClientError:
        raise
    except Exception as exc:
        logger.error("Unexpected error generating descriptions: %s", exc)
        raise GeminiClientError(
            f"Description generation failed for bot '{bot.name}': {exc}"
        ) from exc


def _build_bot_context(bot: Bot) -> dict:
    """Build a context dict from bot fields for prompt generation."""
    return {
        "niche": bot.niche or "",
        "niche_description": bot.niche_description or "",
        "content_style": bot.content_style or "",
        "brand_style": bot.brand_style or "",
        "video_duration_seconds": bot.video_duration_seconds,
        "video_aspect_ratio": bot.video_aspect_ratio or "9:16",
        "language": bot.language or "es",
    }


async def generate_video_prompt(
    bot: Bot,
    script: dict,
    *,
    arc_premise: Optional[str] = None,
    arc_chapter: Optional[int] = None,
    arc_total: Optional[int] = None,
    previous_video_prompts: Optional[List[str]] = None,
) -> str:
    """Convert a script dict into a visual prompt for AI video generation.

    Returns a single string prompt optimised for video-generation models.
    """
    logger.info("Generating video prompt for bot='%s'", bot.name)

    client = _get_client(bot)
    bot_context = _build_bot_context(bot)

    arc_context = None
    if arc_premise and arc_chapter and arc_total:
        arc_context = {
            "premise": arc_premise,
            "chapter": arc_chapter,
            "total": arc_total,
            "previous_prompts": previous_video_prompts or [],
        }

    try:
        prompt = await asyncio.to_thread(
            client.generate_video_prompt, script, bot_context, arc_context
        )
        logger.info("Video prompt generated for bot='%s'", bot.name)
        return prompt
    except GeminiClientError:
        raise
    except Exception as exc:
        logger.error("Unexpected error generating video prompt: %s", exc)
        raise GeminiClientError(
            f"Video prompt generation failed for bot '{bot.name}': {exc}"
        ) from exc

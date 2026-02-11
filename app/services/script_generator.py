from __future__ import annotations

import asyncio
from typing import Optional

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


async def generate_content_script(bot: Bot, topic: str) -> dict:
    """Generate a structured video script for *topic* using the bot's config.

    Returns a dict with keys: ``hook``, ``body``, ``cta``, ``visual_cues``.
    """
    logger.info("Generating script for bot='%s' topic='%s'", bot.name, topic)

    client = _get_client(bot)
    system_prompt = _build_system_prompt(bot)

    user_prompt = (
        f"Create a short-form video script about the following topic:\n\n"
        f"{topic}\n\n"
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


async def generate_content_descriptions(
    bot: Bot,
    script: dict,
    topic: str,
) -> dict:
    """Generate platform-specific descriptions (Instagram, YouTube, TikTok).

    Returns a dict with keys: ``instagram``, ``youtube``, ``tiktok``.
    """
    logger.info("Generating descriptions for bot='%s' topic='%s'", bot.name, topic)

    client = _get_client(bot)
    niche = bot.niche or "general"

    try:
        descriptions = await asyncio.to_thread(
            client.generate_descriptions, script, topic, niche
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


async def generate_video_prompt(bot: Bot, script: dict) -> str:
    """Convert a script dict into a visual prompt for AI video generation.

    Returns a single string prompt optimised for video-generation models.
    """
    logger.info("Generating video prompt for bot='%s'", bot.name)

    client = _get_client(bot)

    try:
        prompt = await asyncio.to_thread(client.generate_video_prompt, script)
        logger.info("Video prompt generated for bot='%s'", bot.name)
        return prompt
    except GeminiClientError:
        raise
    except Exception as exc:
        logger.error("Unexpected error generating video prompt: %s", exc)
        raise GeminiClientError(
            f"Video prompt generation failed for bot '{bot.name}': {exc}"
        ) from exc

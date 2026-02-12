"""Compile all bot configuration into a comprehensive production system prompt.

This module reads from ``production_config`` (structured) and falls back to
legacy fields (``script_system_prompt``, ``character_personality``, etc.) when
the structured config is empty.
"""
from __future__ import annotations

from typing import List

from app.models.bot import Bot


def _format_character(char: dict, idx: int) -> str:
    """Format a single character specification into a prompt section."""
    parts: List[str] = []
    name = char.get("name") or f"Personaje {idx + 1}"
    role = char.get("role", "protagonist")
    parts.append(f"  {name} ({role})")

    if char.get("visual_description"):
        parts.append(f"    Apariencia: {char['visual_description']}")
    if char.get("clothing"):
        parts.append(f"    Vestimenta: {char['clothing']}")
    if char.get("distinguishing_features"):
        parts.append(f"    Rasgos distintivos: {char['distinguishing_features']}")
    if char.get("personality"):
        parts.append(f"    Personalidad: {char['personality']}")

    return "\n".join(parts)


def build_master_system_prompt(bot: Bot) -> str:
    """Compile ALL bot config into a comprehensive Gemini system prompt.

    Sections assembled:
    1. Identity / base system prompt
    2. Characters (from production_config or legacy fields)
    3. Visual style (brand_style + technical specs)
    4. Setting
    5. Music direction
    6. Content rules
    7. Technical constraints
    8. Output instructions (based on production_mode)
    """
    sections: List[str] = []
    config = bot.production_config or {}
    mode = bot.production_mode or "standard"
    characters = config.get("characters", [])
    technical = config.get("technical", {})
    music = config.get("music", {})

    # ── 1. Identity ──────────────────────────────────────────────
    if bot.script_system_prompt:
        sections.append(bot.script_system_prompt)
    elif characters:
        main = characters[0]
        name = main.get("name", "el personaje")
        sections.append(
            f"You are an expert production director creating content "
            f"for a character called '{name}'. Generate detailed production "
            f"documents for short-form vertical videos."
        )
    else:
        sections.append(
            "You are an expert production director for short-form social media "
            "videos. Generate detailed production documents for vertical (9:16) "
            "videos."
        )

    # ── 2. Characters ────────────────────────────────────────────
    if characters:
        char_lines = ["", "CHARACTERS:"]
        for i, char in enumerate(characters):
            char_lines.append(_format_character(char, i))
        sections.append("\n".join(char_lines))
    elif bot.character_personality:
        sections.append(f"\nCHARACTER PERSONALITY: {bot.character_personality}")

    # ── 3. Visual style ──────────────────────────────────────────
    style_parts: List[str] = []
    if bot.brand_style:
        style_parts.append(bot.brand_style)
    if technical.get("style"):
        style_parts.append(f"Visual style: {technical['style']}")
    if technical.get("color_palette"):
        style_parts.append(f"Color palette: {technical['color_palette']}")
    if technical.get("camera_style"):
        style_parts.append(f"Camera: {technical['camera_style']}")
    if style_parts:
        sections.append("\nVISUAL STYLE:\n" + "\n".join(f"  {p}" for p in style_parts))

    # ── 4. Setting ───────────────────────────────────────────────
    setting = config.get("setting", "")
    if setting:
        sections.append(f"\nSETTING: {setting}")

    # ── 5. Music ─────────────────────────────────────────────────
    music_parts: List[str] = []
    if music.get("style"):
        music_parts.append(f"Style: {music['style']}")
    if music.get("mood"):
        music_parts.append(f"Mood: {music['mood']}")
    if music.get("bpm_range"):
        music_parts.append(f"BPM: {music['bpm_range']}")
    if music_parts:
        sections.append("\nMUSIC DIRECTION:\n" + "\n".join(f"  {p}" for p in music_parts))

    # ── 6. Content rules ─────────────────────────────────────────
    rules_parts: List[str] = []
    if bot.niche:
        rules_parts.append(f"Content niche: {bot.niche}.")
    if bot.niche_description:
        rules_parts.append(f"Niche details: {bot.niche_description}")
    if bot.content_style:
        rules_parts.append(f"Content style: {bot.content_style}")
    if config.get("content_rules"):
        rules_parts.append(f"Rules: {config['content_rules']}")
    if rules_parts:
        sections.append("\nCONTENT CONTEXT:\n" + "\n".join(f"  {p}" for p in rules_parts))

    # ── 7. Technical constraints ─────────────────────────────────
    tech_parts: List[str] = []
    if bot.language:
        tech_parts.append(f"Output language: {bot.language}")
    if bot.video_duration_seconds:
        tech_parts.append(f"Target duration: {bot.video_duration_seconds} seconds")
    aspect = bot.video_aspect_ratio or "9:16"
    tech_parts.append(f"Aspect ratio: {aspect}")
    sections.append("\nTECHNICAL:\n" + "\n".join(f"  {p}" for p in tech_parts))

    # ── 8. Output instructions (mode-specific) ───────────────────
    sections.append(_output_instructions(mode, bot.video_duration_seconds or 15))

    return "\n".join(sections)


def _output_instructions(mode: str, duration: int) -> str:
    """Return mode-specific instructions telling Gemini what JSON to produce."""
    if mode == "storyboard":
        return _storyboard_instructions(duration)
    elif mode == "talking_head":
        return _talking_head_instructions(duration)
    return ""  # standard mode uses legacy system prompt only


def _storyboard_instructions(duration: int) -> str:
    scene_count = max(2, duration // 4)
    return f"""
OUTPUT FORMAT — STORYBOARD PRODUCTION DOCUMENT:
You MUST return a JSON object with these fields:

- "title": Short title for this content piece.
- "characters": Array of characters appearing in this video. Each has "name" and "description" (visual description as it should appear in this specific video).
- "storyboard": Array of {scene_count}-{scene_count + 2} scenes. Each scene has:
    - "timestamp": Time range (e.g. "0:00-0:04")
    - "visual": What the viewer sees on screen (detailed, cinematic)
    - "dialogue": Spoken words. Empty string if no speech.
    - "music_direction": Music/sound notes for this scene
    - "camera": Camera movement/angle notes
  Scenes must cover the full {duration}-second duration.
- "music_description": Overall music style, instruments, BPM, mood.
- "video_prompt": A single 600-1200 character cinematic narrative prompt ready to copy-paste into a video AI. Must describe the full visual story as continuous prose.
- "dialogue_full": Complete dialogue concatenated from all scenes, natural spoken text only (no stage directions).
- "hook": The attention-grabbing opening line or moment.
- "cta": Call-to-action for the end.

The storyboard must tell a compelling visual story with a clear arc: attention-grabbing opening → development → climax/resolution.
Include specific character actions, emotions, lighting, colors, and camera movements.
"""


def _talking_head_instructions(duration: int) -> str:
    scene_count = max(2, duration // 5)
    return f"""
OUTPUT FORMAT — TALKING HEAD PRODUCTION DOCUMENT:
You MUST return a JSON object with these fields:

- "title": Short title for this content piece.
- "storyboard": Array of {scene_count}-{scene_count + 2} segments. Each has:
    - "timestamp": Time range (e.g. "0:00-0:05")
    - "expression": Facial expression/emotion for this moment
    - "dialogue": What the character says in this segment
    - "overlay_text": On-screen text/graphic to show (empty if none)
  Segments must cover the full {duration}-second duration.
- "video_prompt": A prompt describing the character's appearance, clothing, and setting for the video AI (200-500 chars).
- "dialogue_full": The COMPLETE monologue the character delivers to camera, natural spoken text, all segments concatenated. This text will be sent to a text-to-speech AI, so write it as natural speech without stage directions.
- "hook": The opening hook that grabs attention.
- "cta": Call-to-action for the end.
- "music_description": Background music style, mood.

The dialogue must sound natural and engaging — as if the character is speaking directly to their followers. Match the character's personality and speaking style.
"""

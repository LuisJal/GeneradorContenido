from __future__ import annotations

import json
from typing import Optional

from google import genai
from google.genai import types
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.utils.logging_config import get_logger

logger = get_logger("gemini_client")

# Exceptions from the SDK that warrant a retry (transient / rate-limit).
_RETRYABLE = (
    Exception,  # broad fallback; narrowed below when possible
)


class GeminiClientError(Exception):
    """Raised when a Gemini API call fails after exhausting retries."""


class GeminiClient:
    """Thin wrapper around the ``google-genai`` SDK for content generation."""

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash") -> None:
        self._api_key = api_key
        self._model = model
        self._client = genai.Client(api_key=api_key)
        logger.info("GeminiClient initialised (model=%s)", self._model)

    # ------------------------------------------------------------------
    # Script generation
    # ------------------------------------------------------------------

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type(_RETRYABLE),
        reraise=True,
    )
    def generate_script(self, system_prompt: str, user_prompt: str) -> dict:
        """Generate a structured video script via Gemini.

        Returns a dict with keys: ``hook``, ``body``, ``cta``, ``visual_cues``.
        """
        response_schema = {
            "type": "object",
            "properties": {
                "hook": {
                    "type": "string",
                    "description": "A powerful opening hook (first 2 seconds of video).",
                },
                "body": {
                    "type": "string",
                    "description": "The main body content of the script.",
                },
                "cta": {
                    "type": "string",
                    "description": "A clear call-to-action for the end of the video.",
                },
                "visual_cues": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Visual directions / scene descriptions for each section.",
                },
            },
            "required": ["hook", "body", "cta", "visual_cues"],
        }

        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    response_mime_type="application/json",
                    response_schema=response_schema,
                    temperature=0.9,
                ),
            )

            raw_text = response.text
            if not raw_text:
                raise GeminiClientError("Gemini returned an empty response for script generation.")

            script: dict = json.loads(raw_text)
            logger.info("Script generated successfully (hook length=%d)", len(script.get("hook", "")))
            return script

        except json.JSONDecodeError as exc:
            logger.error("Failed to parse Gemini JSON response: %s", exc)
            raise GeminiClientError(f"Invalid JSON in Gemini response: {exc}") from exc
        except GeminiClientError:
            raise
        except Exception as exc:
            logger.error("Gemini generate_script failed: %s", exc)
            raise

    # ------------------------------------------------------------------
    # Plain text generation (for story arc premises, etc.)
    # ------------------------------------------------------------------

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type(_RETRYABLE),
        reraise=True,
    )
    def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        """Generate plain text via Gemini (no JSON schema)."""
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.8,
                    max_output_tokens=2048,
                ),
            )
            text = (response.text or "").strip()
            if not text:
                raise GeminiClientError("Gemini returned empty text response.")
            logger.info("Text generated successfully (length=%d)", len(text))
            return text
        except GeminiClientError:
            raise
        except Exception as exc:
            logger.error("Gemini generate_text failed: %s", exc)
            raise

    # ------------------------------------------------------------------
    # Video prompt generation
    # ------------------------------------------------------------------

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type(_RETRYABLE),
        reraise=True,
    )
    def generate_video_prompt(
        self,
        script: dict,
        bot_context: Optional[dict] = None,
        arc_context: Optional[dict] = None,
    ) -> str:
        """Convert a structured script dict into a narrative video prompt.

        Parameters
        ----------
        script:
            Dict with keys ``hook``, ``body``, ``cta``, ``visual_cues``.
        bot_context:
            Optional dict with bot metadata: ``niche``, ``niche_description``,
            ``content_style``, ``brand_style``, ``video_duration_seconds``,
            ``video_aspect_ratio``, ``language``.
        """
        ctx = bot_context or {}
        duration = ctx.get("video_duration_seconds", 10)
        aspect = ctx.get("video_aspect_ratio", "9:16")
        orientation = "vertical (9:16)" if "9:16" in aspect else f"({aspect})"

        # Calculate scene structure based on duration
        if duration <= 5:
            scenes = 1
            scene_guide = "One single continuous scene with a clear beginning and ending moment."
        elif duration <= 10:
            scenes = 2
            scene_guide = "2 scenes (~5s each). Scene 1 sets up the situation, Scene 2 delivers the payoff/resolution."
        else:
            scenes = max(3, duration // 5)
            scene_guide = f"{scenes} scenes (~{duration // scenes}s each). Build a mini-story: setup -> tension/development -> climax/resolution."

        system_instruction = f"""You are a cinematic video storyteller. Transform the script below into a {duration}-second {orientation} video prompt that tells a COMPELLING VISUAL STORY.

FORMAT: {duration}-second {orientation} video.
SCENES: {scene_guide}

STORYTELLING RULES:
1. START with: "{duration}-second {orientation} video."
2. Write the prompt as a CONTINUOUS NARRATIVE that describes what happens on screen moment by moment.
3. Use CHRONOLOGICAL storytelling: "A character does X... then Y happens... finally Z."
4. Include specific character actions, emotions, and reactions - make the viewer FEEL the story.
5. Describe camera movements AS PART of the narrative (e.g., "the camera slowly pulls back to reveal...").
6. Use vivid, cinematic language: lighting, atmosphere, mood, colors, textures.
7. Each scene transition should feel natural: "Cut to...", "The scene shifts to...", "We see..."
8. The story must have a clear ARC: attention-grabbing opening -> development -> satisfying conclusion.
9. Keep between 600-1200 characters. Dense but clear.
10. Output ONLY the prompt text.

WHAT MAKES A GOOD VIDEO PROMPT:
- BAD: "A person standing in a gym. Weights on the floor. Motivational atmosphere."
- GOOD: "A determined athlete steps into a dimly lit gym at dawn, chalk dust floating in golden light beams. She grips the barbell, eyes locked forward with fierce concentration. In one explosive motion she lifts, every muscle engaged, the camera tracking upward with the movement as sweat catches the light. She holds the weight overhead, a triumphant smile breaking across her face as the camera pulls back to reveal the empty gym around her."

The GOOD example tells a story with character, emotion, action, and a satisfying arc."""

        if ctx.get("brand_style"):
            system_instruction += f"\n\nVISUAL STYLE (apply consistently): {ctx['brand_style']}"
        if ctx.get("niche"):
            system_instruction += f"\nContent niche: {ctx['niche']}."
        if ctx.get("niche_description"):
            system_instruction += f"\nNiche details: {ctx['niche_description']}"
        if ctx.get("content_style"):
            system_instruction += f"\nTone/style: {ctx['content_style']}"

        if arc_context:
            system_instruction += (
                f"\n\n--- MULTI-PART STORY ARC ---\n"
                f"This video is Part {arc_context['chapter']} of {arc_context['total']}.\n"
                f"Story premise: {arc_context['premise']}\n"
                f"CRITICAL: Maintain EXACT visual consistency with the previous parts. "
                f"Same characters (appearance, clothing), same locations, same visual style. "
                f"The viewer must recognize this as the same story.\n"
            )
            for i, prev in enumerate(arc_context.get("previous_prompts", []), 1):
                system_instruction += f"\nPart {i} video prompt (reference): {prev}\n"

        user_content = (
            f"Create a {duration}-second video prompt based on this script:\n\n"
            f"HOOK (opening moment): {script.get('hook', '')}\n"
            f"STORY (main content): {script.get('body', '')}\n"
            f"ENDING (call to action): {script.get('cta', '')}\n"
            f"VISUAL IDEAS: {json.dumps(script.get('visual_cues', []), ensure_ascii=False)}"
        )

        if arc_context and arc_context.get("chapter", 1) > 1:
            user_content += (
                f"\n\nIMPORTANT: Reuse the EXACT character descriptions, "
                f"setting details, and visual style from the previous part(s). "
                f"Only the story events change."
            )

        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=user_content,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.8,
                    max_output_tokens=1024,
                ),
            )

            prompt_text = (response.text or "").strip()
            if not prompt_text:
                raise GeminiClientError("Gemini returned an empty video prompt.")

            logger.info("Video prompt generated (length=%d)", len(prompt_text))
            return prompt_text

        except GeminiClientError:
            raise
        except Exception as exc:
            logger.error("Gemini generate_video_prompt failed: %s", exc)
            raise

    # ------------------------------------------------------------------
    # Production document generation
    # ------------------------------------------------------------------

    # Storyboard mode schema
    _STORYBOARD_SCHEMA = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "characters": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                    },
                    "required": ["name", "description"],
                },
            },
            "storyboard": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "timestamp": {"type": "string"},
                        "visual": {"type": "string"},
                        "dialogue": {"type": "string"},
                        "music_direction": {"type": "string"},
                        "camera": {"type": "string"},
                    },
                    "required": ["timestamp", "visual", "dialogue"],
                },
            },
            "music_description": {"type": "string"},
            "video_prompt": {"type": "string"},
            "dialogue_full": {"type": "string"},
            "hook": {"type": "string"},
            "cta": {"type": "string"},
        },
        "required": ["title", "storyboard", "video_prompt", "dialogue_full", "hook", "cta"],
    }

    # Talking head mode schema
    _TALKING_HEAD_SCHEMA = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "storyboard": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "timestamp": {"type": "string"},
                        "expression": {"type": "string"},
                        "dialogue": {"type": "string"},
                        "overlay_text": {"type": "string"},
                    },
                    "required": ["timestamp", "dialogue"],
                },
            },
            "video_prompt": {"type": "string"},
            "dialogue_full": {"type": "string"},
            "hook": {"type": "string"},
            "cta": {"type": "string"},
            "music_description": {"type": "string"},
        },
        "required": ["title", "storyboard", "video_prompt", "dialogue_full", "hook", "cta"],
    }

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type(_RETRYABLE),
        reraise=True,
    )
    def generate_production_document(
        self, system_prompt: str, user_prompt: str, mode: str = "storyboard"
    ) -> dict:
        """Generate a full production document with structured JSON output.

        *mode* selects the response schema: ``"storyboard"`` for cinematic
        narratives or ``"talking_head"`` for dialogue-focused content.
        """
        schema = (
            self._TALKING_HEAD_SCHEMA if mode == "talking_head"
            else self._STORYBOARD_SCHEMA
        )

        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    response_mime_type="application/json",
                    response_schema=schema,
                    temperature=0.9,
                    max_output_tokens=4096,
                ),
            )

            raw_text = response.text
            if not raw_text:
                raise GeminiClientError(
                    "Gemini returned an empty response for production document."
                )

            doc: dict = json.loads(raw_text)
            logger.info(
                "Production document generated (mode=%s, scenes=%d)",
                mode,
                len(doc.get("storyboard", [])),
            )
            return doc

        except json.JSONDecodeError as exc:
            logger.error("Failed to parse production document JSON: %s", exc)
            raise GeminiClientError(
                f"Invalid JSON in production document response: {exc}"
            ) from exc
        except GeminiClientError:
            raise
        except Exception as exc:
            logger.error("Gemini generate_production_document failed: %s", exc)
            raise

    # ------------------------------------------------------------------
    # Platform descriptions generation
    # ------------------------------------------------------------------

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type(_RETRYABLE),
        reraise=True,
    )
    def generate_descriptions(
        self,
        script: dict,
        topic: str,
        niche: str,
        arc_chapter: Optional[int] = None,
        arc_total: Optional[int] = None,
    ) -> dict:
        """Generate platform-specific descriptions for a video.

        Returns a dict with keys:
        - ``instagram``: str (max 2200 chars, includes hashtags)
        - ``youtube``: dict with ``title``, ``description``, ``tags``
        - ``tiktok``: str (max 2200 chars, includes hashtags)
        """
        system_instruction = (
            "You are a social-media copywriter. Given a video script, its topic, "
            "and its niche, generate optimised descriptions for three platforms.\n\n"
            "Rules:\n"
            "- Instagram: engaging caption up to 2200 characters with relevant hashtags.\n"
            "- YouTube: an SEO-friendly title (max 100 chars), a description (up to 5000 chars) "
            "with keywords, and a list of tags (strings).\n"
            "- TikTok: short, punchy caption up to 2200 characters with trending hashtags.\n"
            "- All text must be in the SAME language as the script.\n"
            "- Return ONLY valid JSON matching the schema."
        )

        if arc_chapter and arc_total:
            system_instruction += (
                f"\n\nThis is Part {arc_chapter} of {arc_total} in a story series.\n"
                f"- ALL descriptions must mention this is part of a series.\n"
                f"- YouTube title MUST end with ' (Parte {arc_chapter}/{arc_total})'.\n"
                f"- Instagram and TikTok captions should mention this is part of a series.\n"
            )
            if arc_chapter > 1:
                system_instruction += (
                    f"- Include a mention to watch from Part 1 / Mira desde la Parte 1.\n"
                )

        response_schema = {
            "type": "object",
            "properties": {
                "instagram": {
                    "type": "string",
                    "description": "Instagram caption with hashtags (max 2200 chars).",
                },
                "youtube": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "YouTube video title (max 100 chars).",
                        },
                        "description": {
                            "type": "string",
                            "description": "YouTube video description.",
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "YouTube tags for SEO.",
                        },
                    },
                    "required": ["title", "description", "tags"],
                },
                "tiktok": {
                    "type": "string",
                    "description": "TikTok caption with hashtags (max 2200 chars).",
                },
            },
            "required": ["instagram", "youtube", "tiktok"],
        }

        user_content = (
            f"Topic: {topic}\n"
            f"Niche: {niche}\n"
            f"Script hook: {script.get('hook', '')}\n"
            f"Script body: {script.get('body', '')}\n"
            f"Script CTA: {script.get('cta', '')}"
        )

        if arc_chapter and arc_total:
            user_content += f"\nThis is Part {arc_chapter} of {arc_total} in a story series."

        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=user_content,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    response_schema=response_schema,
                    temperature=0.7,
                ),
            )

            raw_text = response.text
            if not raw_text:
                raise GeminiClientError(
                    "Gemini returned an empty response for descriptions."
                )

            descriptions: dict = json.loads(raw_text)

            # Enforce character limits
            if len(descriptions.get("instagram", "")) > 2200:
                descriptions["instagram"] = descriptions["instagram"][:2200]
            if len(descriptions.get("tiktok", "")) > 2200:
                descriptions["tiktok"] = descriptions["tiktok"][:2200]

            logger.info("Platform descriptions generated successfully")
            return descriptions

        except json.JSONDecodeError as exc:
            logger.error("Failed to parse Gemini descriptions JSON: %s", exc)
            raise GeminiClientError(
                f"Invalid JSON in Gemini descriptions response: {exc}"
            ) from exc
        except GeminiClientError:
            raise
        except Exception as exc:
            logger.error("Gemini generate_descriptions failed: %s", exc)
            raise

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
    # Video prompt generation
    # ------------------------------------------------------------------

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type(_RETRYABLE),
        reraise=True,
    )
    def generate_video_prompt(self, script: dict) -> str:
        """Convert a structured script dict into a single visual video-generation prompt.

        The returned string is optimised for AI video generators (e.g. Veo, Kling).
        """
        system_instruction = (
            "You are an expert at writing prompts for AI video generation models. "
            "Given a video script with hook, body, cta, and visual_cues, produce a "
            "single, detailed, cinematic prompt that a video-generation AI can use to "
            "create a short vertical (9:16) video.\n\n"
            "Guidelines:\n"
            "- Describe the visual scenes in vivid detail: camera angles, lighting, "
            "colours, motion, transitions.\n"
            "- Incorporate the visual_cues provided in the script.\n"
            "- Keep the prompt under 1500 characters.\n"
            "- Do NOT include dialogue or narration text; focus purely on visuals.\n"
            "- Output ONLY the prompt text, nothing else."
        )

        user_content = (
            f"Hook: {script.get('hook', '')}\n"
            f"Body: {script.get('body', '')}\n"
            f"CTA: {script.get('cta', '')}\n"
            f"Visual cues: {json.dumps(script.get('visual_cues', []), ensure_ascii=False)}"
        )

        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=user_content,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.7,
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

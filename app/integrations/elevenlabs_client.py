"""ElevenLabs Text-to-Speech client."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from app.utils.logging_config import get_logger

logger = get_logger("integrations.elevenlabs")

_BASE_URL = "https://api.elevenlabs.io"
_DEFAULT_MODEL = "eleven_multilingual_v2"
_DEFAULT_OUTPUT_FORMAT = "mp3_44100_128"


class ElevenLabsClient:
    """Client for ElevenLabs Text-to-Speech API.

    Generates natural-sounding speech from text.  Used in the
    talking-head pipeline to produce audio that Hedra lip-syncs.
    """

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._headers = {
            "xi-api-key": api_key,
            "Content-Type": "application/json",
        }
        logger.info("ElevenLabsClient initialised")

    # ------------------------------------------------------------------
    # Text-to-Speech
    # ------------------------------------------------------------------

    async def text_to_speech(
        self,
        text: str,
        voice_id: str,
        output_path: str,
        *,
        model_id: str = _DEFAULT_MODEL,
        language_code: str = "es",
        stability: float = 0.50,
        similarity_boost: float = 0.75,
        speed: float = 1.0,
    ) -> str:
        """Convert *text* to speech and save to *output_path*.

        Parameters
        ----------
        text:
            The text to synthesise.
        voice_id:
            ElevenLabs voice ID.
        output_path:
            Local file path where the MP3 will be saved.
        model_id:
            TTS model.  Default ``eleven_multilingual_v2`` (29 languages).
        language_code:
            ISO 639-1 code.  ``"es"`` for Spanish.
        stability:
            0.0 (expressive) – 1.0 (monotone).  0.5 is balanced.
        similarity_boost:
            0.0 – 1.0.  How closely to match the original voice.
        speed:
            0.7 – 1.2.  Speech rate multiplier.

        Returns
        -------
        str
            The *output_path* where the audio was saved.
        """
        url = f"{_BASE_URL}/v1/text-to-speech/{voice_id}"
        payload: Dict[str, Any] = {
            "text": text,
            "model_id": model_id,
            "language_code": language_code,
            "voice_settings": {
                "stability": stability,
                "similarity_boost": similarity_boost,
                "style": 0.0,
                "use_speaker_boost": True,
                "speed": speed,
            },
        }

        logger.info(
            "Generating speech: voice=%s, model=%s, lang=%s, text_len=%d",
            voice_id, model_id, language_code, len(text),
        )

        dest = Path(output_path)
        dest.parent.mkdir(parents=True, exist_ok=True)

        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            resp = await client.post(
                url,
                headers=self._headers,
                params={"output_format": _DEFAULT_OUTPUT_FORMAT},
                json=payload,
            )
            resp.raise_for_status()
            dest.write_bytes(resp.content)

        file_size_kb = dest.stat().st_size / 1024
        logger.info(
            "Speech audio saved: %s (%.1f KB)", output_path, file_size_kb,
        )
        return str(dest)

    # ------------------------------------------------------------------
    # Voices
    # ------------------------------------------------------------------

    async def list_voices(
        self,
        search: Optional[str] = None,
        category: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List available voices, optionally filtered.

        Parameters
        ----------
        search:
            Free-text search across name, description, labels.
        category:
            ``"premade"``, ``"cloned"``, ``"generated"``, etc.

        Returns
        -------
        list[dict]
            List of voice objects with ``voice_id``, ``name``, etc.
        """
        params: Dict[str, Any] = {"page_size": 100}
        if search:
            params["search"] = search
        if category:
            params["category"] = category

        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            resp = await client.get(
                f"{_BASE_URL}/v2/voices",
                headers={"xi-api-key": self._api_key},
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()

        voices = data.get("voices", [])
        logger.info("Listed %d voices (search=%s)", len(voices), search)
        return voices

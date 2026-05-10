"""
ElevenLabs streaming TTS engine.

Dual-track model selection:
  eleven_v3           — 300ms TTFB, supports inline audio tags (emotion/sound)
  eleven_flash_v2_5   — 170ms TTFB, no audio tags, best for combat/quick reactions

Per-avatar voice parameters:
  {stability, similarity_boost, style, use_speaker_boost}
  stored as JSON on the Avatar model and passed through at synthesis time.

Degrades gracefully when API key or elevenlabs SDK is absent.
"""

from __future__ import annotations

import io
import struct
import wave
import asyncio
import structlog
from dataclasses import dataclass
from typing import AsyncIterator

log = structlog.get_logger()

# Default voice parameters (moderate expressiveness)
DEFAULT_VOICE_PARAMS = {
    "stability": 0.7,
    "similarity_boost": 0.8,
    "style": 0.4,
    "use_speaker_boost": True,
}

# Emotion tag → parameter delta applied on top of base params
EMOTION_DELTAS: dict[str, dict[str, float]] = {
    "urgently":  {"style": +0.3, "stability": -0.2},
    "tense":     {"style": +0.2, "stability": -0.1},
    "quietly":   {"style": -0.2, "stability": +0.2},
    "whispering":{"style": -0.3, "stability": +0.3},
    "laughing":  {"style": +0.4, "stability": -0.15},
    "excited":   {"style": +0.35, "stability": -0.2},
    "somber":    {"style": -0.1, "stability": +0.1},
    "default":   {},
}


def _silent_wav(duration_s: float = 0.5, sample_rate: int = 24000) -> bytes:
    n = int(sample_rate * duration_s)
    samples = struct.pack(f"<{n}h", *([0] * n))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(samples)
    return buf.getvalue()


def _apply_emotion(base_params: dict, emotion: str) -> dict:
    """Apply emotion deltas to base voice params, clamped to [0, 1]."""
    params = dict(base_params)
    deltas = EMOTION_DELTAS.get(emotion, {})
    for key, delta in deltas.items():
        if key in params:
            params[key] = max(0.0, min(1.0, params[key] + delta))
    return params


@dataclass
class SynthesisResult:
    audio_bytes: bytes
    sample_rate: int = 24000
    duration_s: float = 0.0
    emotion: str = "default"
    text: str = ""


class ElevenLabsTTSEngine:
    """
    Per-process ElevenLabs TTS engine.

    Maintains a client instance and per-avatar voice configuration.
    Thread-safe for batch synthesis calls.
    """

    SAMPLE_RATE = 24000  # pcm_24000 format

    def __init__(self):
        self._client = None
        self._voice_configs: dict[int, dict] = {}   # avatar_id → {voice_id, params, model}

    def _get_client(self):
        if self._client is not None:
            return self._client
        from app.config import get_settings
        settings = get_settings()
        if not settings.elevenlabs_api_key:
            return None
        try:
            from elevenlabs import ElevenLabs
            self._client = ElevenLabs(api_key=settings.elevenlabs_api_key)
            return self._client
        except ImportError:
            log.warning("elevenlabs_tts.sdk_not_installed", hint="pip install elevenlabs")
            return None

    def register_avatar(
        self,
        avatar_id: int,
        voice_id: str,
        voice_params: dict | None = None,
        model_preference: str = "eleven_v3",
    ) -> None:
        """Store per-avatar voice config for later synthesis calls."""
        self._voice_configs[avatar_id] = {
            "voice_id": voice_id,
            "params": voice_params or dict(DEFAULT_VOICE_PARAMS),
            "model": model_preference,
        }

    def synthesize(
        self,
        text: str,
        avatar_id: int,
        emotion: str = "default",
    ) -> SynthesisResult:
        """
        Batch synthesis — blocks until full audio is ready.
        Returns SynthesisResult with WAV bytes. Falls back to silence on error.
        Designed to run in asyncio thread pool executor.
        """
        config = self._voice_configs.get(avatar_id)
        if not config:
            log.warning("elevenlabs_tts.no_config", avatar_id=avatar_id)
            return SynthesisResult(
                audio_bytes=_silent_wav(0.5), sample_rate=self.SAMPLE_RATE,
                emotion=emotion, text=text,
            )

        client = self._get_client()
        if client is None:
            return SynthesisResult(
                audio_bytes=_silent_wav(0.5), sample_rate=self.SAMPLE_RATE,
                emotion=emotion, text=text,
            )

        voice_id = config["voice_id"]
        base_params = config["params"]
        model = config["model"]
        final_params = _apply_emotion(base_params, emotion)

        try:
            from elevenlabs import VoiceSettings

            audio_iter = client.text_to_speech.convert(
                voice_id=voice_id,
                output_format="pcm_24000",
                text=text,
                model_id=model,
                voice_settings=VoiceSettings(
                    stability=final_params.get("stability", 0.7),
                    similarity_boost=final_params.get("similarity_boost", 0.8),
                    style=final_params.get("style", 0.4),
                    use_speaker_boost=final_params.get("use_speaker_boost", True),
                ),
            )

            # Collect raw PCM chunks, then wrap in WAV container
            pcm_chunks = list(audio_iter)
            raw_pcm = b"".join(pcm_chunks)

            # Wrap PCM in WAV so the existing output_manager can play it
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(self.SAMPLE_RATE)
                wf.writeframes(raw_pcm)
            wav_bytes = buf.getvalue()

            duration = len(raw_pcm) / 2 / self.SAMPLE_RATE
            log.info(
                "elevenlabs_tts.synthesized",
                avatar_id=avatar_id,
                model=model,
                emotion=emotion,
                duration_s=round(duration, 2),
                bytes=len(wav_bytes),
            )
            return SynthesisResult(
                audio_bytes=wav_bytes,
                sample_rate=self.SAMPLE_RATE,
                duration_s=duration,
                emotion=emotion,
                text=text,
            )

        except Exception as e:
            log.error("elevenlabs_tts.synthesis_failed", avatar_id=avatar_id, error=str(e))
            return SynthesisResult(
                audio_bytes=_silent_wav(0.5), sample_rate=self.SAMPLE_RATE,
                emotion=emotion, text=text,
            )

    async def synthesize_stream(
        self,
        text: str,
        voice_id: str,
        voice_params: dict | None = None,
        model: str = "eleven_flash_v2_5",
        emotion: str = "default",
    ) -> AsyncIterator[bytes]:
        """
        Async streaming synthesis — yields raw PCM bytes as they arrive.
        Use this path for lowest latency (first audio in ~170–300ms).
        """
        client = self._get_client()
        if client is None:
            yield _silent_wav(0.5)
            return

        base = voice_params or dict(DEFAULT_VOICE_PARAMS)
        final_params = _apply_emotion(base, emotion)

        try:
            from elevenlabs import VoiceSettings

            loop = asyncio.get_running_loop()
            chunks = await loop.run_in_executor(
                None,
                lambda: list(client.text_to_speech.convert(
                    voice_id=voice_id,
                    output_format="pcm_24000",
                    text=text,
                    model_id=model,
                    voice_settings=VoiceSettings(
                        stability=final_params.get("stability", 0.7),
                        similarity_boost=final_params.get("similarity_boost", 0.8),
                        style=final_params.get("style", 0.4),
                        use_speaker_boost=final_params.get("use_speaker_boost", True),
                    ),
                )),
            )
            for chunk in chunks:
                if chunk:
                    yield chunk

        except Exception as e:
            log.error("elevenlabs_tts.stream_failed", error=str(e))
            yield b""


# Module-level singleton
elevenlabs_tts_engine = ElevenLabsTTSEngine()

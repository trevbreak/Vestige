"""
Edge-TTS wrapper — Microsoft Azure Neural TTS (free, no API key required).

Uses the `edge-tts` Python package which calls the Edge browser's TTS endpoint.
Provides authentic English accents (British RP, Irish, Welsh) suitable for a
medieval/fantasy D&D atmosphere.

Runs synchronous synthesis by wrapping an asyncio event loop.
Designed to run in a thread pool executor (blocking I/O).

Requires: edge-tts>=6.1, pydub>=0.25, ffmpeg (system)
"""

from __future__ import annotations

import asyncio
import io
import threading
import structlog
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.audio.tts import SynthesisResult

log = structlog.get_logger()

# Emotion tag → SSML rate modifier for Edge-TTS
_EMOTION_RATES: dict[str, str] = {
    "quietly":    "-10%",
    "whispering": "-15%",
    "urgently":   "+15%",
    "tense":      "+8%",
    "laughing":   "+12%",
    "default":    "+0%",
}


class EdgeTTSEngine:
    """
    Thread-safe Edge-TTS synthesizer.

    The module-level singleton `edge_tts_engine` is the intended entry point.
    """

    SAMPLE_RATE = 24000

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._available: bool | None = None
        # Each thread needs its own event loop
        self._thread_local = threading.local()

    @property
    def available(self) -> bool:
        if self._available is None:
            try:
                import edge_tts  # noqa: F401
                import pydub      # noqa: F401
                self._available = True
            except ImportError:
                self._available = False
        return self._available

    def synthesize(
        self,
        text: str,
        voice_id: str,
        emotion: str = "default",
        volume: float = 1.0,
    ) -> "SynthesisResult":
        from app.audio.tts import SynthesisResult, _silent_wav

        if not self.available:
            log.warning(
                "edge_tts.not_available",
                note="Install edge-tts and pydub: pip install edge-tts pydub",
            )
            return SynthesisResult(
                audio_bytes=_silent_wav(0.5),
                sample_rate=self.SAMPLE_RATE,
                duration_s=0.5,
                emotion=emotion,
                text=text,
            )

        with self._lock:
            try:
                return self._synthesize_blocking(text, voice_id, emotion, volume)
            except Exception as exc:
                log.error("edge_tts.synthesis_failed", voice=voice_id, error=str(exc))
                return SynthesisResult(
                    audio_bytes=_silent_wav(0.5),
                    sample_rate=self.SAMPLE_RATE,
                    duration_s=0.5,
                    emotion=emotion,
                    text=text,
                )

    def _synthesize_blocking(
        self,
        text: str,
        voice_id: str,
        emotion: str,
        volume: float,
    ) -> "SynthesisResult":
        """Run async synthesis in a dedicated event loop (one per thread)."""
        # Get or create an event loop for this thread
        loop = getattr(self._thread_local, "loop", None)
        if loop is None or loop.is_closed():
            loop = asyncio.new_event_loop()
            self._thread_local.loop = loop

        return loop.run_until_complete(
            self._synthesize_async(text, voice_id, emotion, volume)
        )

    async def _synthesize_async(
        self,
        text: str,
        voice_id: str,
        emotion: str,
        volume: float,
    ) -> "SynthesisResult":
        import edge_tts
        from app.audio.tts import SynthesisResult

        rate = _EMOTION_RATES.get(emotion, "+0%")

        communicate = edge_tts.Communicate(text, voice_id, rate=rate)
        mp3_chunks: list[bytes] = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                mp3_chunks.append(chunk["data"])

        if not mp3_chunks:
            from app.audio.tts import _silent_wav
            return SynthesisResult(
                audio_bytes=_silent_wav(0.5),
                sample_rate=self.SAMPLE_RATE,
                duration_s=0.5,
                emotion=emotion,
                text=text,
            )

        mp3_bytes = b"".join(mp3_chunks)

        # Decode MP3 → 24kHz mono WAV via pydub
        from pydub import AudioSegment
        audio = AudioSegment.from_mp3(io.BytesIO(mp3_bytes))
        audio = audio.set_frame_rate(self.SAMPLE_RATE).set_channels(1)

        if volume != 1.0:
            # pydub adjusts in dB: +6 ≈ 2x, -6 ≈ 0.5x
            import math
            db_adj = 20 * math.log10(max(volume, 0.01))
            audio = audio + db_adj

        wav_buf = io.BytesIO()
        audio.export(wav_buf, format="wav")
        wav_bytes = wav_buf.getvalue()
        duration_s = len(audio) / 1000.0

        log.debug("edge_tts.synthesized", voice=voice_id, duration_s=round(duration_s, 2))
        return SynthesisResult(
            audio_bytes=wav_bytes,
            sample_rate=self.SAMPLE_RATE,
            duration_s=duration_s,
            emotion=emotion,
            text=text,
        )


# Module-level singleton
edge_tts_engine = EdgeTTSEngine()

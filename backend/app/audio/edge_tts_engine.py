"""
Edge-TTS wrapper — Microsoft Azure Neural TTS (free, no API key required).

Uses the `edge-tts` Python package which calls the Edge browser's TTS endpoint.
Provides authentic English accents (British RP, Irish, Welsh) suitable for a
medieval/fantasy tabletop atmosphere.

MP3 → WAV decoding uses the ffmpeg binary bundled with imageio-ffmpeg, so no
system-level ffmpeg installation is required.

Requires: edge-tts>=6.1, imageio-ffmpeg>=0.4
"""

from __future__ import annotations

import asyncio
import io
import struct
import subprocess
import threading
import wave
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


def _get_ffmpeg() -> str | None:
    """Return path to the imageio-bundled ffmpeg binary, or None if unavailable."""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def _mp3_to_wav(mp3_bytes: bytes, sample_rate: int = 24000) -> bytes:
    """
    Decode MP3 bytes → WAV bytes using the imageio-bundled ffmpeg.
    Outputs 24 kHz, 16-bit, mono WAV.
    Raises RuntimeError if ffmpeg is unavailable or decoding fails.
    """
    ffmpeg = _get_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("imageio-ffmpeg not installed: pip install imageio-ffmpeg")

    result = subprocess.run(
        [
            ffmpeg, "-y",
            "-i", "pipe:0",          # MP3 from stdin
            "-f", "s16le",           # raw signed 16-bit little-endian PCM
            "-ar", str(sample_rate), # resample to target rate
            "-ac", "1",              # mono
            "pipe:1",                # PCM to stdout
        ],
        input=mp3_bytes,
        capture_output=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg decode failed (exit {result.returncode}): "
            f"{result.stderr[-200:].decode(errors='replace')}"
        )

    pcm = result.stdout
    if not pcm:
        raise RuntimeError("ffmpeg produced no output")

    # Wrap raw PCM in a proper WAV container
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)        # 16-bit = 2 bytes/sample
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def _apply_volume(wav_bytes: bytes, volume: float) -> bytes:
    """Scale a WAV file's samples by volume in-place (returns new WAV bytes)."""
    if volume == 1.0:
        return wav_bytes
    buf = io.BytesIO(wav_bytes)
    with wave.open(buf, "rb") as wf:
        params = wf.getparams()
        raw = wf.readframes(wf.getnframes())
    n = len(raw) // 2
    samples = struct.unpack(f"<{n}h", raw)
    scaled = struct.pack(
        f"<{n}h",
        *(max(-32768, min(32767, int(s * volume))) for s in samples),
    )
    out = io.BytesIO()
    with wave.open(out, "wb") as wf:
        wf.setparams(params)
        wf.writeframes(scaled)
    return out.getvalue()


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
                import edge_tts      # noqa: F401
                import imageio_ffmpeg  # noqa: F401
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
                note="Install: pip install edge-tts imageio-ffmpeg",
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
        from app.audio.tts import SynthesisResult, _silent_wav

        rate = _EMOTION_RATES.get(emotion, "+0%")

        communicate = edge_tts.Communicate(text, voice_id, rate=rate)
        mp3_chunks: list[bytes] = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                mp3_chunks.append(chunk["data"])

        if not mp3_chunks:
            log.warning("edge_tts.no_audio_returned", voice=voice_id, text=text[:60])
            return SynthesisResult(
                audio_bytes=_silent_wav(0.5),
                sample_rate=self.SAMPLE_RATE,
                duration_s=0.5,
                emotion=emotion,
                text=text,
            )

        mp3_bytes = b"".join(mp3_chunks)
        wav_bytes = _mp3_to_wav(mp3_bytes, self.SAMPLE_RATE)

        if volume != 1.0:
            wav_bytes = _apply_volume(wav_bytes, volume)

        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            duration_s = wf.getnframes() / wf.getframerate()

        log.info("edge_tts.synthesized", voice=voice_id, duration_s=round(duration_s, 2))
        return SynthesisResult(
            audio_bytes=wav_bytes,
            sample_rate=self.SAMPLE_RATE,
            duration_s=duration_s,
            emotion=emotion,
            text=text,
        )


# Module-level singleton
edge_tts_engine = EdgeTTSEngine()

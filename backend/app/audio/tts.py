"""
Coqui XTTS-v2 TTS wrapper.

Exposes a module-level singleton `tts_engine` that is loaded once at startup
(via startup_checks.py) and reused by every session's LLMDispatcher.

Loading XTTS-v2 multiple times in the same process corrupts the CUDA context
and causes device-side asserts in subsequently loaded models (Whisper).
"""

from __future__ import annotations

import io
import threading
import wave
import struct
import numpy as np
import structlog
from dataclasses import dataclass

log = structlog.get_logger()

# Emotion tag → speaking-rate and energy hints for XTTS conditioning
EMOTION_SPEEDS: dict[str, float] = {
    "quietly":    0.85,
    "whispering": 0.80,
    "urgently":   1.15,
    "tense":      1.05,
    "laughing":   1.10,
    "default":    1.00,
}

# Silence WAV used as stub when XTTS unavailable
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


@dataclass
class SynthesisResult:
    audio_bytes: bytes
    sample_rate: int = 24000
    duration_s: float = 0.0
    emotion: str = "default"
    text: str = ""


class TTSEngine:
    """
    Module-level singleton TTS engine.

    Dispatches to either:
      • XTTS-v2 (Coqui) — high-quality voice cloning from speaker embeddings
      • Edge-TTS (Microsoft) — free neural voices with accent variety

    The choice is determined per-avatar by engine_preference + embedding availability.
    Do not instantiate directly after startup — use the module-level
    `tts_engine` instance and call `tts_engine.load()` once at startup
    (done by startup_checks.py).
    """

    SAMPLE_RATE = 24000

    def __init__(self):
        self.device: str = "cuda"
        self._model = None
        self._speakers: dict[int, dict] = {}
        self._lock = threading.Lock()
        # Phase 8: per-avatar voice preferences
        self._engine_preferences: dict[int, str] = {}  # avatar_id → "auto"|"xtts"|"edge"
        self._voice_ids: dict[int, str] = {}            # avatar_id → edge-tts voice_id

    def load(self, device: str = "cuda") -> bool:
        """
        Load XTTS-v2.  No-op if already loaded.  Returns True on success.
        """
        if self._model is not None:
            log.info("tts.already_loaded")
            return True

        self.device = device
        try:
            from TTS.api import TTS
            log.info("tts.loading_xtts2", device=device)
            self._model = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)
            log.info("tts.ready")
            return True
        except ImportError:
            log.warning("tts.coqui_not_installed", note="TTS running in silent stub mode")
            return False
        except Exception as e:
            log.error("tts.load_failed", error=str(e))
            return False

    @property
    def available(self) -> bool:
        return self._model is not None

    # ── Speaker management ────────────────────────────────────────────────

    def load_speaker_embedding(self, avatar_id: int, embedding_path: str) -> bool:
        try:
            data = np.load(embedding_path, allow_pickle=True)
            self._speakers[avatar_id] = {
                "gpt_cond_latent": data["gpt_cond_latent"],
                "speaker_embedding": data["speaker_embedding"],
            }
            log.info("tts.speaker_loaded", avatar_id=avatar_id, path=embedding_path)
            return True
        except Exception as e:
            log.error("tts.speaker_load_failed", avatar_id=avatar_id, error=str(e))
            return False

    def has_speaker(self, avatar_id: int) -> bool:
        return avatar_id in self._speakers

    def register_avatar_voice(
        self,
        avatar_id: int,
        voice_id: str | None = None,
        engine_preference: str = "auto",
    ) -> None:
        """Register per-avatar TTS engine preference and Edge-TTS voice_id."""
        self._engine_preferences[avatar_id] = engine_preference or "auto"
        if voice_id:
            self._voice_ids[avatar_id] = voice_id

    # ── Synthesis ─────────────────────────────────────────────────────────

    def synthesize(
        self,
        text: str,
        avatar_id: int,
        emotion: str = "default",
        language: str = "en",
        volume: float = 1.0,
    ) -> SynthesisResult:
        # Phase 8: dispatch to Edge-TTS if configured
        pref = self._engine_preferences.get(avatar_id, "auto")
        voice_id = self._voice_ids.get(avatar_id)

        use_edge = (
            pref == "edge"
            or (pref == "auto" and not self.has_speaker(avatar_id) and bool(voice_id))
        )

        if use_edge and voice_id:
            from app.audio.edge_tts_engine import edge_tts_engine
            return edge_tts_engine.synthesize(text, voice_id, emotion, volume)

        # Fall through to XTTS-v2
        return self._synthesize_xtts(text, avatar_id, emotion, language, volume)

    def _synthesize_xtts(
        self,
        text: str,
        avatar_id: int,
        emotion: str = "default",
        language: str = "en",
        volume: float = 1.0,
    ) -> SynthesisResult:
        if not self.available:
            return SynthesisResult(
                audio_bytes=_silent_wav(0.5),
                sample_rate=self.SAMPLE_RATE,
                duration_s=0.5,
                emotion=emotion,
                text=text,
            )

        speaker = self._speakers.get(avatar_id)

        with self._lock:
            try:
                import torch
                buf = io.BytesIO()

                if speaker:
                    audio_array = self._model.tts(
                        text=text,
                        language=language,
                        gpt_cond_latent=torch.tensor(speaker["gpt_cond_latent"]).to(self.device),
                        speaker_embedding=torch.tensor(speaker["speaker_embedding"]).to(self.device),
                        speed=EMOTION_SPEEDS.get(emotion, 1.0),
                    )
                else:
                    audio_array = self._model.tts(
                        text=text,
                        language=language,
                        speaker="Claribel Dervla",
                        speed=EMOTION_SPEEDS.get(emotion, 1.0),
                    )

                samples = np.array(audio_array, dtype=np.float32)
                if volume != 1.0:
                    samples = samples * volume
                samples_i16 = np.clip(samples * 32767, -32768, 32767).astype(np.int16)
                duration_s = len(samples_i16) / self.SAMPLE_RATE

                with wave.open(buf, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(self.SAMPLE_RATE)
                    wf.writeframes(samples_i16.tobytes())

                return SynthesisResult(
                    audio_bytes=buf.getvalue(),
                    sample_rate=self.SAMPLE_RATE,
                    duration_s=duration_s,
                    emotion=emotion,
                    text=text,
                )

            except Exception as e:
                err_str = str(e)
                log.error("tts.synthesis_failed", error=err_str, text=text[:60])
                # CUDA context corruption — mark engine unavailable so future calls
                # return silent stubs instead of looping into more CUDA errors.
                if "CUDA error" in err_str or "device-side assert" in err_str:
                    log.warning("tts.cuda_context_corrupted", action="disabling_gpu_tts")
                    self._model = None
                return SynthesisResult(
                    audio_bytes=_silent_wav(0.5),
                    sample_rate=self.SAMPLE_RATE,
                    duration_s=0.5,
                    emotion=emotion,
                    text=text,
                )


# Module-level singleton — loaded once at startup, shared across all sessions
tts_engine = TTSEngine()

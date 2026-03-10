"""
faster-whisper transcription wrapper.

Loads the model once on startup and exposes a synchronous
`transcribe()` method. The pipeline orchestrator calls this
from a thread pool to avoid blocking the asyncio event loop.

Falls back gracefully if faster-whisper is not installed.
"""

from __future__ import annotations

import numpy as np
import structlog
from dataclasses import dataclass

log = structlog.get_logger()


@dataclass
class TranscriptSegment:
    text: str
    start_ms: int
    end_ms: int
    confidence: float          # avg log-prob mapped to 0–1
    language: str = "en"
    is_inaudible: bool = False


class Transcriber:
    """
    Singleton-style faster-whisper wrapper.

    The model is loaded once and reused across all transcription calls.
    Thread-safe for concurrent calls from asyncio's thread pool.
    """

    def __init__(
        self,
        model_size: str = "large-v3",
        device: str = "cuda",
        compute_type: str = "float16",
    ):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self._model = None
        self._load()

    def _load(self) -> None:
        try:
            from faster_whisper import WhisperModel
            log.info("transcriber.loading", model=self.model_size, device=self.device)
            self._model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
            )
            log.info("transcriber.ready")
        except ImportError:
            log.warning(
                "transcriber.faster_whisper_not_installed",
                note="Transcription running in stub mode",
            )
        except Exception as e:
            log.error("transcriber.load_failed", error=str(e))

    @property
    def available(self) -> bool:
        return self._model is not None

    def transcribe(
        self,
        audio: np.ndarray,
        sample_rate: int = 16000,
        language: str = "en",
    ) -> list[TranscriptSegment]:
        """
        Transcribe a PCM int16 numpy array.

        Parameters
        ----------
        audio       : int16 PCM mono audio
        sample_rate : must be 16000 for faster-whisper
        language    : ISO-639-1 language hint (e.g. 'en')

        Returns
        -------
        List of TranscriptSegment, one per whisper segment.
        Empty list on failure.
        """
        if not self.available:
            # Stub: return placeholder so tests and dev can proceed without GPU
            return [TranscriptSegment(
                text="[transcription unavailable — faster-whisper not installed]",
                start_ms=0,
                end_ms=int(len(audio) / sample_rate * 1000),
                confidence=0.0,
                is_inaudible=True,
            )]

        # faster-whisper expects float32 normalised [-1, 1]
        float_audio = audio.astype(np.float32) / 32768.0

        try:
            segments_iter, info = self._model.transcribe(
                float_audio,
                language=language,
                beam_size=5,
                vad_filter=False,   # We do our own VAD upstream
                word_timestamps=False,
            )
        except Exception as e:
            log.error("transcriber.transcribe_failed", error=str(e))
            return []

        results: list[TranscriptSegment] = []
        for seg in segments_iter:
            text = seg.text.strip()
            avg_logprob = getattr(seg, "avg_logprob", -0.5)
            # Map log-prob to a rough 0–1 confidence: -0.0 → 1.0, -1.0 → ~0.37
            confidence = float(min(1.0, max(0.0, 1.0 + avg_logprob)))

            from app.audio.backchannel_classifier import is_inaudible
            results.append(TranscriptSegment(
                text=text,
                start_ms=int(seg.start * 1000),
                end_ms=int(seg.end * 1000),
                confidence=confidence,
                language=info.language,
                is_inaudible=is_inaudible(text),
            ))

        return results

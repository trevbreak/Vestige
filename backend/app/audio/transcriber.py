"""
faster-whisper transcription wrapper.

Exposes a module-level singleton `transcriber` that is loaded once at startup
(via startup_checks.py) and reused by every AudioPipeline session.

Loading twice in the same process with CUDA triggers a device-side assert in
some CTranslate2/driver combinations, so we intentionally never call
WhisperModel(...) more than once per process.
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
    Module-level singleton faster-whisper wrapper.

    Do not call __init__ directly after startup — use the module-level
    `transcriber` instance.  Call `transcriber.load(...)` once at startup
    (done by startup_checks.py) to prime the model.
    """

    def __init__(self):
        self._model = None
        self.model_size: str = "large-v3"
        self.device: str = "cuda"
        self.compute_type: str = "float16"

    def load(
        self,
        model_size: str = "large-v3",
        device: str = "cuda",
        compute_type: str = "float16",
    ) -> bool:
        """
        Load (or reload) the WhisperModel.  Returns True on success.
        Safe to call only once — subsequent calls are no-ops if already loaded.
        """
        if self._model is not None:
            log.info("transcriber.already_loaded", model=self.model_size)
            return True

        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type

        try:
            from faster_whisper import WhisperModel
            log.info("transcriber.loading", model=model_size, device=device,
                     compute_type=compute_type)
            self._model = WhisperModel(model_size, device=device, compute_type=compute_type)
            log.info("transcriber.ready", model=model_size, device=device,
                     compute_type=compute_type)
            return True
        except ImportError:
            log.warning("transcriber.faster_whisper_not_installed",
                        note="Transcription running in stub mode")
            return False
        except Exception as e:
            log.error("transcriber.load_failed", error=str(e),
                      model=model_size, device=device, compute_type=compute_type)
            return False

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
            log.warning("transcriber.not_loaded",
                        note="Call transcriber.load() at startup before transcribing")
            return [TranscriptSegment(
                text="[transcription unavailable — model not loaded]",
                start_ms=0,
                end_ms=int(len(audio) / sample_rate * 1000),
                confidence=0.0,
                is_inaudible=True,
            )]

        # faster-whisper expects float32 normalised [-1, 1]
        float_audio = audio.astype(np.float32) / 32768.0

        from app.config import get_settings
        cfg = get_settings()
        try:
            segments_iter, info = self._model.transcribe(
                float_audio,
                language=language,
                beam_size=5,
                vad_filter=False,           # We do our own VAD upstream
                word_timestamps=False,
                condition_on_previous_text=False,  # prevents hallucination loops
                no_speech_threshold=cfg.whisper_no_speech_threshold,
                compression_ratio_threshold=2.4,
                log_prob_threshold=cfg.whisper_log_prob_threshold,
            )
        except Exception as e:
            log.error("transcriber.transcribe_failed", error=str(e))
            return []

        # Known Whisper hallucination phrases on silence/noise
        _HALLUCINATIONS = {
            "thank you", "thanks for watching", "thanks for watching!", "thank you.",
            "thank you!", "thanks!", "thanks.", "you", ".",  "[music]", "[applause]",
            "[silence]", "[ silence ]", "[music playing]", "subtitles by",
            "www.", ".com", "yo.", "yo", "i don't know", "i don't know.",
        }

        results: list[TranscriptSegment] = []
        for seg in segments_iter:
            text = seg.text.strip()
            if not text:
                continue

            # Drop known hallucination phrases
            if text.lower() in _HALLUCINATIONS:
                log.info("transcriber.hallucination_dropped", text=text)
                continue

            # Drop low-confidence segments (likely silence/noise)
            avg_logprob = getattr(seg, "avg_logprob", -0.5)
            no_speech_prob = getattr(seg, "no_speech_prob", 0.0)
            confidence = float(min(1.0, max(0.0, 1.0 + avg_logprob)))

            if no_speech_prob > cfg.whisper_no_speech_threshold:
                log.info("transcriber.no_speech_dropped", text=text,
                         no_speech_prob=round(no_speech_prob, 3))
                continue

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


# Module-level singleton — loaded once at startup, shared across all sessions
transcriber = Transcriber()

"""
Silero VAD wrapper.

Segments a continuous PCM stream into speech/silence regions.
Yields complete speech segments (as numpy int16 arrays) ready
for transcription.

Silero VAD expects:
  - 16 kHz sample rate
  - 30 ms chunk size  →  480 samples per chunk
  - float32 normalised to [-1.0, 1.0]
"""

from __future__ import annotations

import numpy as np
import structlog
from typing import Generator

log = structlog.get_logger()

# Minimum/maximum segment durations to suppress noise bursts
MIN_SPEECH_MS = 300   # discard segments shorter than this
MAX_SPEECH_MS = 30_000  # force-flush segments longer than this


class VADProcessor:
    """
    Streaming VAD using silero-vad.

    Usage:
        vad = VADProcessor()
        for segment in vad.process_stream(audio_chunks):
            transcribe(segment)

    Falls back gracefully if silero is not installed (unit-test mode).
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        threshold: float = 0.5,
    ):
        self.sample_rate = sample_rate
        self.threshold = threshold
        self._model = None
        self._load_model()

    def _load_model(self) -> None:
        try:
            import torch
            from silero_vad import load_silero_vad, get_speech_timestamps  # noqa
            self._model, self._utils = load_silero_vad(), None
            # Store torch reference for stream processing
            self._torch = torch
            log.info("vad.loaded")
        except ImportError:
            log.warning("vad.silero_not_installed", note="VAD running in passthrough mode")
            self._model = None

    @property
    def available(self) -> bool:
        return self._model is not None

    def process_chunk(self, chunk: np.ndarray) -> float:
        """
        Score a single 30 ms chunk.  Returns speech probability (0.0–1.0).
        Returns 0.0 if model not available.
        """
        if not self.available:
            return float(np.abs(chunk).mean() / 32768)  # energy proxy

        tensor = self._torch.from_numpy(chunk.astype(np.float32) / 32768.0)
        with self._torch.no_grad():
            prob = self._model(tensor, self.sample_rate).item()
        return prob

    def segment_audio(
        self,
        audio: np.ndarray,
    ) -> list[dict]:
        """
        Run VAD over a complete numpy int16 buffer.
        Returns list of dicts: {start_ms, end_ms, audio}.
        """
        if not self.available:
            # Passthrough — treat entire buffer as one segment
            return [{
                "start_ms": 0,
                "end_ms": int(len(audio) / self.sample_rate * 1000),
                "audio": audio,
            }]

        try:
            from silero_vad import get_speech_timestamps
        except ImportError:
            return [{"start_ms": 0, "end_ms": len(audio) // (self.sample_rate // 1000), "audio": audio}]

        float_audio = self._torch.from_numpy(audio.astype(np.float32) / 32768.0)
        timestamps = get_speech_timestamps(
            float_audio,
            self._model,
            sampling_rate=self.sample_rate,
            threshold=self.threshold,
            min_speech_duration_ms=MIN_SPEECH_MS,
            max_speech_duration_s=MAX_SPEECH_MS / 1000,
        )

        segments = []
        for ts in timestamps:
            start_sample = ts["start"]
            end_sample = ts["end"]
            segments.append({
                "start_ms": int(start_sample / self.sample_rate * 1000),
                "end_ms": int(end_sample / self.sample_rate * 1000),
                "audio": audio[start_sample:end_sample],
            })
        return segments

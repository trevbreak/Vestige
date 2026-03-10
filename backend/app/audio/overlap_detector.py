"""
Overlap Detector.

When two speakers are detected simultaneously (e.g. by energy analysis),
buffer the segment and transcribe the louder stream. Mixed segments are
tagged [overlap] in the transcript.

In Phase 2 this is a pragmatic implementation: we detect high RMS variance
within a VAD segment as an overlap proxy, since true speaker diarization
requires Phase-3+ models. The louder half of the buffer wins.
"""

import numpy as np


def rms(audio: np.ndarray) -> float:
    """Root mean square energy of audio array."""
    return float(np.sqrt(np.mean(audio.astype(np.float32) ** 2)))


def detect_overlap(
    segment: np.ndarray,
    sample_rate: int = 16000,
    window_ms: int = 100,
    variance_threshold: float = 0.4,
) -> bool:
    """
    Heuristic overlap detection via RMS variance across short windows.

    A high coefficient of variation in energy across the segment suggests
    two interleaved speakers rather than one continuous speaker.

    Parameters
    ----------
    segment       : PCM int16 audio
    sample_rate   : samples per second
    window_ms     : window size for energy analysis
    variance_threshold : coefficient of variation above which we flag overlap

    Returns True if likely overlap, False otherwise.
    """
    window = int(sample_rate * window_ms / 1000)
    if len(segment) < window * 3:
        return False  # too short to analyse

    energies = []
    for start in range(0, len(segment) - window, window):
        chunk = segment[start : start + window]
        energies.append(rms(chunk))

    if not energies or max(energies) == 0:
        return False

    arr = np.array(energies)
    cv = float(arr.std() / arr.mean())
    return cv > variance_threshold


def select_dominant_half(segment: np.ndarray) -> np.ndarray:
    """
    Split a segment in two and return the louder half for transcription.
    Used when overlap is detected.
    """
    mid = len(segment) // 2
    first = segment[:mid]
    second = segment[mid:]
    return first if rms(first) >= rms(second) else second

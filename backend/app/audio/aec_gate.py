"""
Acoustic Echo Cancellation Gate.

Blocks mic input while an avatar TTS is playing, plus a configurable
acoustic decay window after TTS ends. Prevents the AI from hearing
and transcribing its own voice.
"""

import time
from app.config import get_settings


class EchoGate:
    """
    Thread-safe timing gate.

    Call `on_tts_start()` when TTS audio begins playing.
    Call `on_tts_end()` when TTS audio finishes (adds decay buffer).
    Query `is_open()` to know whether mic input should be processed.
    """

    def __init__(self, decay_ms: int | None = None):
        settings = get_settings()
        self._decay_s = (decay_ms if decay_ms is not None else settings.aec_decay_ms) / 1000.0
        self._gate_until: float = 0.0
        self._playing: bool = False

    def on_tts_start(self) -> None:
        """Called when TTS audio begins playing — close the gate."""
        self._playing = True
        # Keep gate closed until explicitly released + decay
        self._gate_until = float("inf")

    def on_tts_end(self) -> None:
        """Called when TTS audio finishes — start decay timer."""
        self._playing = False
        self._gate_until = time.monotonic() + self._decay_s

    def is_open(self) -> bool:
        """Return True if mic input should be processed (gate is not active)."""
        if self._playing:
            return False
        return time.monotonic() > self._gate_until

    @property
    def is_closed(self) -> bool:
        return not self.is_open()

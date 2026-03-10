"""
Presence Layer Orchestrator.

Coordinates the two real-time audio behaviours that make avatars feel present:

1. BACKCHANNELS — short "mm"/"yeah" clips played at 60% volume while humans speak.
   Zero LLM latency; uses pre-generated clips.

2. HOLDING PHRASES — ambient "thinking" audio played after the context engine
   decides an avatar should respond, while the LLM generates the full answer.

This module is called by the AudioPipeline and by the LLM router (Phase 4).
"""

from __future__ import annotations

import asyncio
import structlog
from typing import Callable, Awaitable

from app.presence.backchannel_player import BackchannelManager
from app.presence.ambient_reactions import get_holding_phrase, strip_holding_emotion

log = structlog.get_logger()

# Type alias for the async broadcast function
BroadcastFn = Callable[[dict], Awaitable[None]]


class PresenceLayer:
    """
    Per-session presence layer.

    Instantiated by the AudioPipeline alongside the AudioOutputManager.
    """

    def __init__(
        self,
        session_id: int,
        broadcast_fn: BroadcastFn,
        output_manager: "AudioOutputManager",  # injected to queue audio
    ):
        self.session_id = session_id
        self._broadcast = broadcast_fn
        self._output = output_manager
        self._backchannels = BackchannelManager()

    def register_avatar(self, avatar_id: int) -> None:
        self._backchannels.register(avatar_id)

    def unregister_avatar(self, avatar_id: int) -> None:
        self._backchannels.unregister(avatar_id)

    # ── Backchannels ──────────────────────────────────────────────────────

    async def maybe_play_backchannel(
        self,
        avatar_id: int,
        avatar_name: str,
        category: str = "neutral",
    ) -> bool:
        """
        Attempt to play a backchannel for `avatar_id`.

        Called while human speech is ongoing. Returns True if a clip was queued.
        """
        result = self._backchannels.get_clip(avatar_id, category)
        if result is None:
            return False

        text, wav_bytes = result

        # Broadcast transcript entry so the UI shows the backchannel
        await self._broadcast({
            "type": "transcript",
            "session_id": self.session_id,
            "entry": {
                "session_id": self.session_id,
                "speaker": avatar_name,
                "speaker_type": "avatar",
                "text": text,
                "utterance_type": "backchannel",
                "confidence": 1.0,
                "audio_start_ms": 0,
                "audio_end_ms": 0,
                "interrupt_score": 0.0,
                "context_type": "",
                "llm_route": "",
            },
        })

        # Queue audio at 60% volume
        if wav_bytes:
            await self._output.enqueue(
                avatar_id=avatar_id,
                avatar_name=avatar_name,
                wav_bytes=wav_bytes,
                priority=10,   # low priority, preemptible
                volume=0.6,
                utterance_type="backchannel",
            )

        log.debug("presence.backchannel", avatar=avatar_name, text=text)
        return True

    # ── Holding phrases ───────────────────────────────────────────────────

    async def play_holding_phrase(
        self,
        avatar_id: int,
        avatar_name: str,
        context_type: str,
        tts_engine: "TTSEngine",
    ) -> None:
        """
        Generate and queue a holding phrase for the given context type.

        Called immediately when the context engine decides this avatar should
        respond, before the LLM call completes.
        """
        phrase = get_holding_phrase(context_type)
        clean_text, emotion = strip_holding_emotion(phrase)

        # Broadcast "thinking" transcript entry
        await self._broadcast({
            "type": "transcript",
            "session_id": self.session_id,
            "entry": {
                "session_id": self.session_id,
                "speaker": avatar_name,
                "speaker_type": "avatar",
                "text": clean_text,
                "utterance_type": "holding_phrase",
                "confidence": 1.0,
                "audio_start_ms": 0,
                "audio_end_ms": 0,
                "interrupt_score": 0.0,
                "context_type": context_type,
                "llm_route": "",
            },
        })

        # Synthesize and queue
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: tts_engine.synthesize(
                text=clean_text,
                avatar_id=avatar_id,
                emotion=emotion,
                volume=0.9,
            ),
        )

        await self._output.enqueue(
            avatar_id=avatar_id,
            avatar_name=avatar_name,
            wav_bytes=result.audio_bytes,
            priority=3,
            volume=0.9,
            utterance_type="holding_phrase",
        )

        log.debug("presence.holding_phrase", avatar=avatar_name, text=clean_text)

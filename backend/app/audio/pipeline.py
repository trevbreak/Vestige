"""
Audio Pipeline Orchestrator.

Ties together:
  capture → AEC gate → VAD → overlap detection → transcription
  → backchannel classifier → context engine → WebSocket broadcast

Runs as a background asyncio task. Mic capture happens in a
thread pool (blocking I/O), all other processing is in-process.
"""

from __future__ import annotations

import asyncio
import time
import numpy as np
import structlog
from dataclasses import dataclass, field

from app.config import get_settings
from app.audio.aec_gate import EchoGate
from app.audio.backchannel_classifier import classify_utterance
from app.audio.context_engine import ContextEngine, _is_dm_hotword
from app.audio.cross_avatar import CrossAvatarReferencer

log = structlog.get_logger()
settings = get_settings()


@dataclass
class TranscriptEntry:
    """Normalised transcript event — sent over WebSocket and stored in DB."""
    session_id: int
    speaker: str
    speaker_type: str            # "human" | "avatar" | "dm"
    text: str
    utterance_type: str          # "speech" | "backchannel" | "overlap" | "inaudible"
    confidence: float = 1.0
    audio_start_ms: int = 0
    audio_end_ms: int = 0
    interrupt_score: float = 0.0
    context_type: str = ""
    llm_route: str = ""


class AudioPipeline:
    """
    Manages the full real-time audio pipeline for one session.

    Usage (from FastAPI lifespan or a router):
        pipeline = AudioPipeline(session_id=1, active_avatar_ids=[1, 2])
        task = asyncio.create_task(pipeline.run())
        ...
        pipeline.stop()
        await task
    """

    def __init__(
        self,
        session_id: int,
        active_avatar_ids: list[int],
        broadcast_fn,       # async callable: (TranscriptEntry) -> None
        avatar_names: dict[int, str] | None = None,   # {avatar_id: name}
        avatar_modes: dict[int, str] | None = None,   # {avatar_id: mode}
        avatar_profiles: dict[int, dict] | None = None,  # {avatar_id: profile dict}
    ):
        self.session_id = session_id
        self._running = False
        self._broadcast = broadcast_fn

        self._gate = EchoGate()
        self._context_engine = ContextEngine()
        self._deepgram_stt = None   # injected by pipeline_manager after start()

        names = avatar_names or {}
        modes = avatar_modes or {}
        profiles = avatar_profiles or {}
        for aid in active_avatar_ids:
            profile = profiles.get(aid, {})
            self._context_engine.register_avatar(
                aid,
                names.get(aid, f"Avatar {aid}"),
                modes.get(aid, "active"),
                verbosity=profile.get("verbosity", 0.5),
                interrupts_often=profile.get("interrupts_often", False),
                personality_archetype=profile.get("personality_archetype", "extrovert"),
            )

        # Phase 7: cross-avatar reference injector
        self._cross_avatar = CrossAvatarReferencer()

        # Track silence gap for passive triggers
        self._last_human_speech_at: float = 0.0

        # Rolling transcript lines for LLM prompt context (Phase 4)
        self._recent_lines: list[str] = []

    # ── Public control API ────────────────────────────────────────────────

    def stop(self) -> None:
        self._running = False

    def on_tts_start(self) -> None:
        """Called by TTS service when playback begins."""
        self._gate.on_tts_start()
        self._context_engine.on_aec_gate_changed(closed=True)

    def on_tts_end(self) -> None:
        """Called by TTS service when playback ends."""
        self._gate.on_tts_end()
        asyncio.get_event_loop().call_later(
            settings.aec_decay_ms / 1000.0 + 0.05,
            lambda: self._context_engine.on_aec_gate_changed(closed=False),
        )

    def on_avatar_spoke(self, avatar_id: int) -> None:
        self._context_engine.on_avatar_spoke(avatar_id)

    def add_transcript_line(self, speaker: str, text: str) -> None:
        """Append an avatar response to the rolling transcript context."""
        self._recent_lines.append(f"{speaker}: {text}")
        if len(self._recent_lines) > 30:
            self._recent_lines = self._recent_lines[-30:]

    def set_avatar_mode(self, avatar_id: int, mode: str) -> None:
        self._context_engine.set_avatar_mode(avatar_id, mode)

    # ── Main run loop ─────────────────────────────────────────────────────

    async def run(self) -> None:
        """
        Main pipeline coroutine.

        Starts the Deepgram STT client (which handles VAD + endpointing),
        then keeps the pipeline alive until stop() is called.
        Audio arrives via /ws/audio/{session_id} → DeepgramSTTClient.send().
        Deepgram fires _on_transcript_final() on each completed utterance.
        """
        self._running = True
        log.info("pipeline.start", session_id=self.session_id)

        # Start Deepgram connection
        from app.audio.deepgram_stt import DeepgramSTTClient
        self._deepgram_stt = DeepgramSTTClient(
            on_final=self._on_transcript_final,
        )
        ok = await self._deepgram_stt.start()
        if not ok:
            log.warning("pipeline.deepgram_unavailable",
                        hint="Set DEEPGRAM_API_KEY or install deepgram-sdk")

        while self._running:
            await asyncio.sleep(0.5)

        if self._deepgram_stt is not None:
            await self._deepgram_stt.stop()

        log.info("pipeline.stopped", session_id=self.session_id)

    async def _on_transcript_final(self, text: str, confidence: float = 1.0) -> None:
        """
        Called by DeepgramSTTClient when a complete utterance is transcribed.
        Replaces the old _flush_buffer() entry point.
        """
        text = text.strip()
        if not text:
            return

        log.info("pipeline.transcript", session_id=self.session_id,
                 text=text[:120], confidence=round(confidence, 3))

        # Update human-speech timestamp (used for silence-gap passive triggers)
        self._last_human_speech_at = time.monotonic()
        self._context_engine.on_human_speech_start()
        self._context_engine.on_human_speech_end()

        # Backchannel classification
        utterance_type = "speech"
        utype = classify_utterance(text)
        if utype == "backchannel":
            utterance_type = "backchannel"

        # DM hotword detection
        if _is_dm_hotword(text):
            self._context_engine.on_dm_hotword()
            log.info("pipeline.dm_hotword", text=text)

        # Combat signal detection
        _combat_mgr = getattr(self, "_combat_manager", None)
        if _combat_mgr is not None:
            _combat_mgr.process_transcript(self.session_id, speaker="DM", text=text)

        entry = TranscriptEntry(
            session_id=self.session_id,
            speaker="Unknown",
            speaker_type="human",
            text=text,
            utterance_type=utterance_type,
            confidence=confidence,
        )
        await self._broadcast(entry)

        if utterance_type == "speech":
            self._recent_lines.append(f"Unknown: {text}")
            if len(self._recent_lines) > 30:
                self._recent_lines = self._recent_lines[-30:]

            silence_gap = time.monotonic() - self._last_human_speech_at
            _transcript_lines_snapshot = list(self._recent_lines)
            from app.tracing import get_tracer
            _tracer = get_tracer("vestige.pipeline")
            for avatar_id, state in self._context_engine._avatar_states.items():
                with _tracer.start_as_current_span(
                    f"context_engine.evaluate/{state.name}",
                    attributes={
                        "avatar.id": avatar_id,
                        "avatar.name": state.name,
                        "transcript.text": text,
                        "pipeline.silence_gap_s": round(silence_gap, 2),
                    },
                ) as span:
                    decision = self._context_engine.evaluate(
                        text, avatar_id, silence_gap=silence_gap,
                    )
                    span.set_attribute("decision.should_respond", decision.should_respond)
                    span.set_attribute("decision.reason", decision.reason)
                    span.set_attribute("decision.interrupt_score", round(decision.interrupt_score, 3))
                    span.set_attribute("decision.context_type", decision.context_type)

                    log.info(
                        "pipeline.context_decision",
                        avatar=state.name,
                        transcript=text[:120],
                        should_respond=decision.should_respond,
                        reason=decision.reason,
                        interrupt_score=round(decision.interrupt_score, 3),
                        context_type=decision.context_type,
                        silence_gap=round(silence_gap, 1),
                    )

                    if decision.should_respond:
                        await self._dispatch_response(
                            avatar_id=avatar_id,
                            avatar_name=state.name,
                            decision=decision,
                            transcript_lines=_transcript_lines_snapshot,
                        )

    async def _flush_buffer(self, audio, start_ms: int = 0, end_ms: int = 0) -> None:
        """Backward-compat shim for tests. Real path is _on_transcript_final()."""
        # Import lazily so tests that stub transcriber still work
        try:
            from app.audio.transcriber import transcriber as _t
            import asyncio as _asyncio
            loop = _asyncio.get_running_loop()
            segments = await loop.run_in_executor(
                None, _t.transcribe, audio, settings.sample_rate,
            )
            for seg in segments:
                await self._on_transcript_final(seg.text, seg.confidence)
        except Exception as e:
            log.warning("pipeline.flush_buffer_shim_error", error=str(e))

    async def _dispatch_response(
        self,
        avatar_id: int,
        avatar_name: str,
        decision,
        transcript_lines: list[str],
    ) -> None:
        """Fire a full LLM response cycle via the injected LLMDispatcher."""
        dispatcher = getattr(self, "_dispatcher", None)
        if dispatcher is None:
            # No dispatcher injected (tests / early pipeline start) — emit placeholder
            await self._broadcast(TranscriptEntry(
                session_id=self.session_id,
                speaker=avatar_name,
                speaker_type="avatar",
                text=f"[thinking — {decision.context_type} via {decision.route}]",
                utterance_type="holding_phrase",
                interrupt_score=decision.interrupt_score,
                context_type=decision.context_type,
                llm_route=decision.route,
            ))
            return

        from app.llm.dispatcher import DispatchRequest
        profile = getattr(dispatcher, "_avatar_profiles", {}).get(avatar_id, {})

        # Phase 5: retrieve relevant memories for this avatar
        memory_chunks: list[str] = []
        db_factory = getattr(self, "_db_factory", None)
        if db_factory is not None:
            try:
                from app.memory.retriever import memory_retriever
                async with db_factory() as db:
                    memory_chunks = await memory_retriever.retrieve_from_transcript(
                        db, avatar_id, transcript_lines
                    )
            except Exception as e:
                log.warning("pipeline.memory_retrieval_failed", error=str(e))

        # Phase 6: get available actions text if in combat
        available_actions_text = ""
        _combat_mgr = getattr(self, "_combat_manager", None)
        if _combat_mgr is not None:
            try:
                profile_for_combat = profile or {}
                available_actions_text = _combat_mgr.get_available_actions_text(
                    session_id=self.session_id,
                    avatar_id=avatar_id,
                    avatar_name=avatar_name,
                    spells_known=list(profile_for_combat.get("spells_known", {}).keys()),
                    equipment=profile_for_combat.get("equipment", []),
                )
            except Exception as e:
                log.warning("pipeline.combat_actions_failed", error=str(e))

        # Phase 7: cross-avatar reference injection (25% probability)
        cross_avatar_note = self._cross_avatar.get_reference_note(
            requesting_avatar_id=avatar_id,
            requesting_avatar_name=avatar_name,
        )

        req = DispatchRequest(
            session_id=self.session_id,
            avatar_id=avatar_id,
            avatar_name=avatar_name,
            context_type=decision.context_type,
            interrupt_score=decision.interrupt_score,
            priority=decision.priority,
            transcript_lines=transcript_lines,
            memory_chunks=memory_chunks,
            available_actions_text=available_actions_text,
            cross_avatar_note=cross_avatar_note,
            **{k: v for k, v in profile.items() if k != "name"},
        )
        # Fire and forget — do not block the pipeline loop
        asyncio.create_task(
            dispatcher.dispatch(req),
            name=f"dispatch-{avatar_id}-{self.session_id}",
        )

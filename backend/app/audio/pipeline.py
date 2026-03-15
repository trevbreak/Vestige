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
from app.audio.vad import VADProcessor
from app.audio.transcriber import transcriber as _transcriber_singleton, TranscriptSegment
from app.audio.backchannel_classifier import classify_utterance, is_inaudible
from app.audio.overlap_detector import detect_overlap, select_dominant_half
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
        self._vad = VADProcessor(
            sample_rate=settings.sample_rate,
            threshold=settings.vad_threshold,
        )
        self._transcriber = _transcriber_singleton  # loaded once at startup
        self._context_engine = ContextEngine()

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

        Audio arrives via the browser mic WebSocket (/ws/audio/{session_id}),
        which calls _flush_buffer() directly. This coroutine just keeps the
        pipeline alive until stop() is called.
        """
        self._running = True
        log.info("pipeline.start", session_id=self.session_id)

        # Keep running until stop() is called; audio arrives via audio_ws.
        while self._running:
            await asyncio.sleep(0.5)

        log.info("pipeline.stopped", session_id=self.session_id)
        return

        # ── Legacy sounddevice path (server-side mic) — kept for reference ──
        try:
            import sounddevice as sd
        except ImportError:
            log.error("pipeline.sounddevice_not_installed")
            return

        loop = asyncio.get_running_loop()
        audio_queue: asyncio.Queue[np.ndarray] = asyncio.Queue(maxsize=100)

        # Accumulate samples between VAD silence boundaries
        speech_buffer: list[np.ndarray] = []
        in_speech = False
        speech_start_ms = 0
        chunk_samples = settings.chunk_samples

        def audio_callback(indata, frames, time_info, status):
            if status:
                log.warning("pipeline.sounddevice_status", status=str(status))
            if self._gate.is_open():
                chunk = indata[:, 0].copy()  # mono
                loop.call_soon_threadsafe(audio_queue.put_nowait, chunk)

        stream = sd.InputStream(
            samplerate=settings.sample_rate,
            channels=1,
            dtype="int16",
            blocksize=chunk_samples,
            device=settings.mic_device_index,
            callback=audio_callback,
        )

        with stream:
            log.info("pipeline.mic_open", device=settings.mic_device_index)
            elapsed_samples = 0

            while self._running:
                try:
                    chunk = await asyncio.wait_for(audio_queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    # Check silence gap during quiet periods
                    silence_gap = time.monotonic() - self._last_human_speech_at
                    if in_speech and silence_gap > 0.8:
                        # Flush pending buffer as the speaker has stopped
                        await self._flush_buffer(
                            np.concatenate(speech_buffer),
                            speech_start_ms,
                            int(elapsed_samples / settings.sample_rate * 1000),
                        )
                        speech_buffer = []
                        in_speech = False
                    continue

                speech_prob = self._vad.process_chunk(chunk)
                elapsed_samples += len(chunk)
                current_ms = int(elapsed_samples / settings.sample_rate * 1000)

                if speech_prob >= settings.vad_threshold:
                    if not in_speech:
                        in_speech = True
                        speech_start_ms = current_ms - settings.chunk_ms
                        self._context_engine.on_human_speech_start()
                    speech_buffer.append(chunk)
                    self._last_human_speech_at = time.monotonic()

                elif in_speech:
                    # End of utterance — flush
                    in_speech = False
                    self._context_engine.on_human_speech_end()
                    if speech_buffer:
                        full_audio = np.concatenate(speech_buffer)
                        speech_buffer = []
                        await self._flush_buffer(full_audio, speech_start_ms, current_ms)

        log.info("pipeline.stopped", session_id=self.session_id)

    async def _flush_buffer(
        self,
        audio: np.ndarray,
        start_ms: int,
        end_ms: int,
    ) -> None:
        """Process one complete speech segment through the pipeline."""
        loop = asyncio.get_running_loop()

        # Overlap detection
        overlapped = detect_overlap(audio, sample_rate=settings.sample_rate)
        if overlapped:
            audio = select_dominant_half(audio)

        # Transcription (blocking — run in thread pool)
        log.info("pipeline.transcribing", session_id=self.session_id,
                 audio_ms=end_ms - start_ms, samples=len(audio))
        segments: list[TranscriptSegment] = await loop.run_in_executor(
            None,
            self._transcriber.transcribe,
            audio,
            settings.sample_rate,
        )
        log.info("pipeline.transcribed", session_id=self.session_id, n_segments=len(segments),
                 texts=[s.text[:80] for s in segments])

        for seg in segments:
            utterance_type = "overlap" if overlapped else "speech"
            if seg.is_inaudible:
                utterance_type = "inaudible"

            # Backchannel classification
            utype = classify_utterance(seg.text)
            if utype == "backchannel":
                utterance_type = "backchannel"

            # DM hotword detection
            if _is_dm_hotword(seg.text):
                self._context_engine.on_dm_hotword()
                log.info("pipeline.dm_hotword", text=seg.text)

            # Phase 6: combat signal detection from DM speech
            _combat_mgr = getattr(self, "_combat_manager", None)
            if _combat_mgr is not None:
                _combat_mgr.process_transcript(
                    self.session_id,
                    speaker="DM",  # pipeline doesn't know speaker yet; treat as DM for detection
                    text=seg.text,
                )

            # Determine speaker (Phase 2: all human until diarization in future phase)
            speaker = "Unknown"
            speaker_type = "human"

            entry = TranscriptEntry(
                session_id=self.session_id,
                speaker=speaker,
                speaker_type=speaker_type,
                text=seg.text,
                utterance_type=utterance_type,
                confidence=seg.confidence,
                audio_start_ms=start_ms + seg.start_ms,
                audio_end_ms=start_ms + seg.end_ms,
            )

            await self._broadcast(entry)

            # Build a transcript snapshot for prompt context (human speech only)
            if utterance_type in ("speech", "overlap"):
                self._recent_lines.append(f"Unknown: {seg.text}")
                if len(self._recent_lines) > 30:
                    self._recent_lines = self._recent_lines[-30:]

            # Context engine evaluation for each active avatar
            if utterance_type in ("speech", "overlap"):
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
                            "transcript.text": seg.text,
                            "transcript.utterance_type": utterance_type,
                            "pipeline.silence_gap_s": round(silence_gap, 2),
                            "pipeline.recent_lines_count": len(_transcript_lines_snapshot),
                        },
                    ) as span:
                        decision = self._context_engine.evaluate(
                            seg.text,
                            avatar_id,
                            silence_gap=silence_gap,
                        )
                        span.set_attribute("decision.should_respond", decision.should_respond)
                        span.set_attribute("decision.reason", decision.reason)
                        span.set_attribute("decision.interrupt_score", round(decision.interrupt_score, 3))
                        span.set_attribute("decision.context_type", decision.context_type)
                        span.set_attribute("decision.route", decision.route)
                        span.set_attribute("decision.priority", decision.priority)

                        log.info(
                            "pipeline.context_decision",
                            avatar=state.name,
                            transcript=seg.text[:120],
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

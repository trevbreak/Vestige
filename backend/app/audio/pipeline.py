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
from app.audio.transcriber import Transcriber, TranscriptSegment
from app.audio.backchannel_classifier import classify_utterance, is_inaudible
from app.audio.overlap_detector import detect_overlap, select_dominant_half
from app.audio.context_engine import ContextEngine, _is_dm_hotword

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
        avatar_names: dict[int, str] | None = None,  # {avatar_id: name}
        avatar_modes: dict[int, str] | None = None,  # {avatar_id: mode}
    ):
        self.session_id = session_id
        self._running = False
        self._broadcast = broadcast_fn

        self._gate = EchoGate()
        self._vad = VADProcessor(
            sample_rate=settings.sample_rate,
            threshold=settings.vad_threshold,
        )
        self._transcriber = Transcriber(
            model_size=settings.whisper_model,
            device=settings.whisper_device,
            compute_type=settings.whisper_compute_type,
        )
        self._context_engine = ContextEngine()

        names = avatar_names or {}
        modes = avatar_modes or {}
        for aid in active_avatar_ids:
            self._context_engine.register_avatar(
                aid,
                names.get(aid, f"Avatar {aid}"),
                modes.get(aid, "active"),
            )

        # Track silence gap for passive triggers
        self._last_human_speech_at: float = 0.0

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

    def set_avatar_mode(self, avatar_id: int, mode: str) -> None:
        self._context_engine.set_avatar_mode(avatar_id, mode)

    # ── Main run loop ─────────────────────────────────────────────────────

    async def run(self) -> None:
        """
        Main pipeline coroutine. Captures mic in a thread and processes
        VAD segments asynchronously.
        """
        self._running = True
        log.info("pipeline.start", session_id=self.session_id)

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
        segments: list[TranscriptSegment] = await loop.run_in_executor(
            None,
            self._transcriber.transcribe,
            audio,
            settings.sample_rate,
        )

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

            # Context engine evaluation for each active avatar
            # (Phase 4 will hook the LLM router here; for now we emit the decision)
            if utterance_type in ("speech", "overlap"):
                silence_gap = time.monotonic() - self._last_human_speech_at
                for avatar_id, state in self._context_engine._avatar_states.items():
                    decision = self._context_engine.evaluate(
                        seg.text,
                        avatar_id,
                        silence_gap=silence_gap,
                    )
                    if decision.should_respond:
                        log.debug(
                            "pipeline.avatar_should_respond",
                            avatar=state.name,
                            context=decision.context_type,
                            route=decision.route,
                            priority=decision.priority,
                        )
                        # Phase 4 will enqueue to LLM router here
                        # For now, broadcast a "thinking" status event
                        await self._broadcast_status(avatar_id, state.name, decision)

    async def _broadcast_status(self, avatar_id: int, name: str, decision) -> None:
        """Placeholder — Phase 4 will dispatch to LLM router."""
        # This emits a WebSocket event so the frontend can show "Thinking…"
        await self._broadcast(TranscriptEntry(
            session_id=self.session_id,
            speaker=name,
            speaker_type="avatar",
            text=f"[thinking — {decision.context_type} via {decision.route}]",
            utterance_type="holding_phrase",
            interrupt_score=decision.interrupt_score,
            context_type=decision.context_type,
            llm_route=decision.route,
        ))

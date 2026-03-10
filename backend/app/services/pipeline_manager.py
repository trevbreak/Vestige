"""
Pipeline Manager — singleton that owns all active AudioPipeline instances.

Provides start/stop control from the API layer.
Injects the WebSocket broadcast function so the pipeline can push
transcript entries to connected browsers.

Phase 3: Also manages TTSEngine (singleton), AudioOutputManager (per session),
and PresenceLayer (per session). Speaker embeddings are loaded automatically
from avatar.voice_embedding_path when the pipeline starts.
"""

from __future__ import annotations

import asyncio
import structlog
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.audio.pipeline import AudioPipeline
    from app.audio.output_manager import AudioOutputManager
    from app.presence.layer import PresenceLayer

log = structlog.get_logger()


class PipelineManager:
    def __init__(self):
        self._pipelines: dict[int, "AudioPipeline"] = {}
        self._tasks: dict[int, asyncio.Task] = {}
        self._output_managers: dict[int, "AudioOutputManager"] = {}
        self._output_tasks: dict[int, asyncio.Task] = {}
        self._presence_layers: dict[int, "PresenceLayer"] = {}

        # TTS engine is a singleton — loaded once on first use
        self._tts_engine = None

    def _get_tts_engine(self):
        if self._tts_engine is None:
            from app.audio.tts import TTSEngine
            self._tts_engine = TTSEngine()
        return self._tts_engine

    def is_running(self, session_id: int) -> bool:
        return session_id in self._pipelines

    async def start(
        self,
        session_id: int,
        avatar_ids: list[int],
        avatar_names: dict[int, str],
        avatar_modes: dict[int, str],
        broadcast_fn,
        broadcast_dict_fn=None,
        avatar_embeddings: dict[int, str] | None = None,
    ) -> None:
        """
        Start the full pipeline for a session.

        broadcast_fn:      async (TranscriptEntry) → None — for pipeline transcripts
        broadcast_dict_fn: async (dict) → None — for audio/status messages
                           Falls back to broadcast_fn if not provided (legacy).
        avatar_embeddings: {avatar_id: voice_embedding_path}
        """
        if session_id in self._pipelines:
            log.warning("pipeline_manager.already_running", session_id=session_id)
            return

        # Use broadcast_dict_fn for raw dict messages; fall back if not provided
        _broadcast_dict = broadcast_dict_fn or broadcast_fn

        from app.audio.pipeline import AudioPipeline
        from app.audio.output_manager import AudioOutputManager
        from app.presence.layer import PresenceLayer

        # ── TTS engine (singleton) ─────────────────────────────────────────
        tts = self._get_tts_engine()

        # Load speaker embeddings for each avatar that has one
        if avatar_embeddings:
            for aid, emb_path in avatar_embeddings.items():
                if emb_path:
                    ok = tts.load_speaker_embedding(aid, emb_path)
                    if ok:
                        log.info(
                            "pipeline_manager.embedding_loaded",
                            avatar_id=aid,
                            path=emb_path,
                        )
                    else:
                        log.warning(
                            "pipeline_manager.embedding_failed",
                            avatar_id=aid,
                            path=emb_path,
                        )

        # ── AudioPipeline (owns the EchoGate we'll share) ─────────────────
        pipeline = AudioPipeline(
            session_id=session_id,
            active_avatar_ids=avatar_ids,
            broadcast_fn=broadcast_fn,
            avatar_names=avatar_names,
            avatar_modes=avatar_modes,
        )

        # ── AudioOutputManager (shares the pipeline's EchoGate) ───────────
        output_manager = AudioOutputManager(
            session_id=session_id,
            broadcast_fn=_broadcast_dict,
            aec_gate=pipeline._gate,
        )
        # Wire TTS lifecycle into pipeline's AEC gate
        # When output_manager plays, the gate is already managed internally.
        # We expose output_manager on the pipeline so future phases can call it.
        pipeline._output_manager = output_manager

        # ── PresenceLayer ─────────────────────────────────────────────────
        presence = PresenceLayer(
            session_id=session_id,
            output_manager=output_manager,
            broadcast_fn=_broadcast_dict,
        )
        presence._tts_engine = tts  # stash for Phase 4 use via play_holding_phrase

        # Store references
        self._pipelines[session_id] = pipeline
        self._output_managers[session_id] = output_manager
        self._presence_layers[session_id] = presence

        # Start background tasks
        task = asyncio.create_task(pipeline.run(), name=f"pipeline-{session_id}")
        self._tasks[session_id] = task

        out_task = asyncio.create_task(
            output_manager.run(), name=f"output-{session_id}"
        )
        self._output_tasks[session_id] = out_task

        log.info("pipeline_manager.started", session_id=session_id, avatars=avatar_ids)

    async def stop(self, session_id: int) -> None:
        pipeline = self._pipelines.pop(session_id, None)
        task = self._tasks.pop(session_id, None)
        output_manager = self._output_managers.pop(session_id, None)
        out_task = self._output_tasks.pop(session_id, None)
        self._presence_layers.pop(session_id, None)

        if pipeline:
            pipeline.stop()
        if output_manager:
            output_manager.stop()

        for t in (task, out_task):
            if t:
                try:
                    await asyncio.wait_for(t, timeout=3.0)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    t.cancel()

        log.info("pipeline_manager.stopped", session_id=session_id)

    async def stop_all(self) -> None:
        for sid in list(self._pipelines.keys()):
            await self.stop(sid)

    def get_pipeline(self, session_id: int) -> "AudioPipeline | None":
        return self._pipelines.get(session_id)

    def get_output_manager(self, session_id: int) -> "AudioOutputManager | None":
        return self._output_managers.get(session_id)

    def get_presence_layer(self, session_id: int) -> "PresenceLayer | None":
        return self._presence_layers.get(session_id)


pipeline_manager = PipelineManager()

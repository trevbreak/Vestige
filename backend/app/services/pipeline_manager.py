"""
Pipeline Manager — singleton that owns all active AudioPipeline instances.

Provides start/stop control from the API layer.
Injects the WebSocket broadcast function so the pipeline can push
transcript entries to connected browsers.

Phase 3: Manages TTSEngine (singleton), AudioOutputManager (per session),
and PresenceLayer (per session).

Phase 4: Creates LLMDispatcher per session. Stores avatar profiles so the
dispatcher can build DispatchRequest objects without DB access.
"""

from __future__ import annotations

import asyncio
import structlog
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.audio.pipeline import AudioPipeline
    from app.audio.output_manager import AudioOutputManager
    from app.presence.layer import PresenceLayer
    from app.llm.dispatcher import LLMDispatcher

log = structlog.get_logger()


class PipelineManager:
    def __init__(self):
        self._pipelines: dict[int, "AudioPipeline"] = {}
        self._tasks: dict[int, asyncio.Task] = {}
        self._output_managers: dict[int, "AudioOutputManager"] = {}
        self._output_tasks: dict[int, asyncio.Task] = {}
        self._presence_layers: dict[int, "PresenceLayer"] = {}
        self._dispatchers: dict[int, "LLMDispatcher"] = {}

    def _get_tts_engine(self):
        from app.audio.tts import tts_engine
        return tts_engine

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
        avatar_profiles: dict[int, dict] | None = None,
    ) -> None:
        """
        Start the full pipeline for a session.

        broadcast_fn:      async (TranscriptEntry) → None — for pipeline transcripts
        broadcast_dict_fn: async (dict) → None — for audio/status messages
        avatar_embeddings: {avatar_id: voice_embedding_path}
        avatar_profiles:   {avatar_id: dict of Avatar fields} for prompt building
        """
        if session_id in self._pipelines:
            log.warning("pipeline_manager.already_running", session_id=session_id)
            return

        _broadcast_dict = broadcast_dict_fn or broadcast_fn

        from app.audio.pipeline import AudioPipeline
        from app.audio.output_manager import AudioOutputManager
        from app.presence.layer import PresenceLayer
        from app.llm.dispatcher import LLMDispatcher

        # ── TTS engine (singleton) ─────────────────────────────────────────
        tts = self._get_tts_engine()

        if avatar_embeddings:
            for aid, emb_path in avatar_embeddings.items():
                if emb_path:
                    ok = tts.load_speaker_embedding(aid, emb_path)
                    log.info("pipeline_manager.embedding_loaded", avatar_id=aid, ok=ok)

        # Phase 8: register per-avatar voice preferences (Edge-TTS / XTTS-v2)
        for aid, profile in (avatar_profiles or {}).items():
            tts.register_avatar_voice(
                avatar_id=aid,
                voice_id=profile.get("voice_id"),
                engine_preference=profile.get("tts_engine_preference", "auto"),
            )

        # ── AudioPipeline (owns the EchoGate we'll share) ─────────────────
        # AudioPipeline.__init__ loads the Whisper model (blocking, up to 30s).
        # Run it in a thread executor so the event loop stays responsive.
        loop = asyncio.get_running_loop()
        pipeline = await loop.run_in_executor(
            None,
            lambda: AudioPipeline(
                session_id=session_id,
                active_avatar_ids=avatar_ids,
                broadcast_fn=broadcast_fn,
                avatar_names=avatar_names,
                avatar_modes=avatar_modes,
                avatar_profiles=avatar_profiles,
            ),
        )

        # ── AudioOutputManager (shares the pipeline's EchoGate) ───────────
        output_manager = AudioOutputManager(
            session_id=session_id,
            broadcast_fn=_broadcast_dict,
            aec_gate=pipeline._gate,
        )
        pipeline._output_manager = output_manager

        # ── PresenceLayer ─────────────────────────────────────────────────
        presence = PresenceLayer(
            session_id=session_id,
            output_manager=output_manager,
            broadcast_fn=_broadcast_dict,
        )

        # ── LLMDispatcher ─────────────────────────────────────────────────
        dispatcher = LLMDispatcher(
            session_id=session_id,
            tts_engine=tts,
            output_manager=output_manager,
            presence_layer=presence,
            context_engine=pipeline._context_engine,
            broadcast_fn=_broadcast_dict,
        )

        # Store avatar profiles for building DispatchRequests
        dispatcher._avatar_profiles = avatar_profiles or {}

        # Cross-references: pipeline → dispatcher (to fire LLM calls)
        #                   dispatcher → pipeline (to append avatar lines to context)
        pipeline._dispatcher = dispatcher
        dispatcher._pipeline = pipeline

        # Phase 5: inject DB session factory for memory retrieval
        from app.db.database import AsyncSessionLocal
        pipeline._db_factory = AsyncSessionLocal

        # Phase 6: inject combat manager for turn-based action context
        from app.services.combat_manager import combat_manager
        pipeline._combat_manager = combat_manager

        # Store references
        self._pipelines[session_id] = pipeline
        self._output_managers[session_id] = output_manager
        self._presence_layers[session_id] = presence
        self._dispatchers[session_id] = dispatcher

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
        self._dispatchers.pop(session_id, None)

        # Phase 6: clean up combat state
        from app.services.combat_manager import combat_manager
        combat_manager.stop_session(session_id)

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

    def get_dispatcher(self, session_id: int) -> "LLMDispatcher | None":
        return self._dispatchers.get(session_id)


pipeline_manager = PipelineManager()

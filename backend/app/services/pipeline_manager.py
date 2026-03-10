"""
Pipeline Manager — singleton that owns all active AudioPipeline instances.

Provides start/stop control from the API layer.
Injects the WebSocket broadcast function so the pipeline can push
transcript entries to connected browsers.
"""

from __future__ import annotations

import asyncio
import structlog
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.audio.pipeline import AudioPipeline

log = structlog.get_logger()


class PipelineManager:
    def __init__(self):
        self._pipelines: dict[int, "AudioPipeline"] = {}
        self._tasks: dict[int, asyncio.Task] = {}

    def is_running(self, session_id: int) -> bool:
        return session_id in self._pipelines

    async def start(
        self,
        session_id: int,
        avatar_ids: list[int],
        avatar_names: dict[int, str],
        avatar_modes: dict[int, str],
        broadcast_fn,
    ) -> None:
        if session_id in self._pipelines:
            log.warning("pipeline_manager.already_running", session_id=session_id)
            return

        from app.audio.pipeline import AudioPipeline

        pipeline = AudioPipeline(
            session_id=session_id,
            active_avatar_ids=avatar_ids,
            broadcast_fn=broadcast_fn,
            avatar_names=avatar_names,
            avatar_modes=avatar_modes,
        )
        self._pipelines[session_id] = pipeline

        task = asyncio.create_task(pipeline.run(), name=f"pipeline-{session_id}")
        self._tasks[session_id] = task
        log.info("pipeline_manager.started", session_id=session_id)

    async def stop(self, session_id: int) -> None:
        pipeline = self._pipelines.pop(session_id, None)
        task = self._tasks.pop(session_id, None)
        if pipeline:
            pipeline.stop()
        if task:
            try:
                await asyncio.wait_for(task, timeout=3.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                task.cancel()
        log.info("pipeline_manager.stopped", session_id=session_id)

    async def stop_all(self) -> None:
        for sid in list(self._pipelines.keys()):
            await self.stop(sid)

    def get_pipeline(self, session_id: int) -> "AudioPipeline | None":
        return self._pipelines.get(session_id)


pipeline_manager = PipelineManager()

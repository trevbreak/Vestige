"""
Audio Output Manager.

Enforces:
  - One avatar speaks at a time
  - Priority preemption (high-priority audio can cut off lower-priority)
  - AEC gate signalling (close mic during playback, open after)
  - WAV streaming to browser via WebSocket (base64-encoded chunks)
  - Avatar speaking/done status broadcast to frontend
"""

from __future__ import annotations

import asyncio
import base64
import time
import structlog
from dataclasses import dataclass, field
from typing import Callable, Awaitable

log = structlog.get_logger()

BroadcastFn = Callable[[dict], Awaitable[None]]


@dataclass(order=True)
class AudioJob:
    """Priority queue item. Lower priority number = higher importance."""
    priority: int
    # These fields are excluded from comparison
    avatar_id: int = field(compare=False)
    avatar_name: str = field(compare=False)
    wav_bytes: bytes = field(compare=False, default=b"")
    volume: float = field(compare=False, default=1.0)
    utterance_type: str = field(compare=False, default="speech")
    session_id: int = field(compare=False, default=0)
    enqueued_at: float = field(compare=False, default_factory=time.monotonic)
    # PCM streaming fields (ElevenLabs path)
    pcm_stream: object = field(compare=False, default=None)  # AsyncIterator[bytes] | None
    sample_rate: int = field(compare=False, default=24000)


# WAV streaming chunk size (bytes sent per WebSocket message)
STREAM_CHUNK_BYTES = 4096


class AudioOutputManager:
    """
    Per-session audio output serialiser.

    Usage:
        manager = AudioOutputManager(session_id, broadcast_fn, aec_gate)
        task = asyncio.create_task(manager.run())
        await manager.enqueue(avatar_id, avatar_name, wav_bytes, priority=2)
        manager.stop()
    """

    def __init__(
        self,
        session_id: int,
        broadcast_fn: BroadcastFn,
        aec_gate,  # EchoGate instance
    ):
        self.session_id = session_id
        self._broadcast = broadcast_fn
        self._gate = aec_gate
        self._queue: asyncio.PriorityQueue[AudioJob] = asyncio.PriorityQueue()
        self._current_job: AudioJob | None = None
        self._running = False
        self._cancel_current = asyncio.Event()

    async def enqueue(
        self,
        avatar_id: int,
        avatar_name: str,
        wav_bytes: bytes,
        priority: int = 5,
        volume: float = 1.0,
        utterance_type: str = "speech",
    ) -> None:
        job = AudioJob(
            priority=priority,
            avatar_id=avatar_id,
            avatar_name=avatar_name,
            wav_bytes=wav_bytes,
            volume=volume,
            utterance_type=utterance_type,
            session_id=self.session_id,
        )
        await self._queue.put(job)
        self._maybe_preempt(priority)

    async def enqueue_stream(
        self,
        avatar_id: int,
        avatar_name: str,
        pcm_stream,   # AsyncIterator[bytes] of raw int16 PCM at 24 kHz
        priority: int = 5,
        utterance_type: str = "speech",
        sample_rate: int = 24000,
    ) -> None:
        """Queue a streaming PCM job (ElevenLabs path). Starts playing before all audio arrives."""
        job = AudioJob(
            priority=priority,
            avatar_id=avatar_id,
            avatar_name=avatar_name,
            utterance_type=utterance_type,
            session_id=self.session_id,
            pcm_stream=pcm_stream,
            sample_rate=sample_rate,
        )
        await self._queue.put(job)
        self._maybe_preempt(priority)

    def _maybe_preempt(self, priority: int) -> None:
        # Preempt current job if new job has higher priority (lower number)
        if (
            self._current_job is not None
            and priority < self._current_job.priority
        ):
            log.debug(
                "output_manager.preempt",
                new_priority=priority,
                old_priority=self._current_job.priority,
            )
            self._cancel_current.set()

    def cancel_all(self) -> None:
        """Cancel current job and drain the queue (DM hotword handler)."""
        self._cancel_current.set()
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except asyncio.QueueEmpty:
                break
        log.info("output_manager.cancelled_all")

    def stop(self) -> None:
        self._running = False
        self.cancel_all()

    async def run(self) -> None:
        self._running = True
        log.info("output_manager.start", session_id=self.session_id)
        while self._running:
            try:
                job = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            self._current_job = job
            self._cancel_current.clear()
            await self._play_job(job)
            self._current_job = None
            self._queue.task_done()

        log.info("output_manager.stopped", session_id=self.session_id)

    async def _play_job(self, job: AudioJob) -> None:
        """Deliver one audio job to the browser via WebSocket."""
        if job.pcm_stream is not None:
            await self._play_pcm_stream(job)
        else:
            await self._play_wav_bytes(job)

    async def _play_wav_bytes(self, job: AudioJob) -> None:
        """Stream a pre-synthesised WAV to the browser in chunks."""
        self._gate.on_tts_start()
        await self._broadcast({
            "type": "avatar_speaking",
            "session_id": self.session_id,
            "avatar_id": job.avatar_id,
            "avatar_name": job.avatar_name,
            "utterance_type": job.utterance_type,
            "speaking": True,
        })

        wav = job.wav_bytes
        offset = 0
        chunk_count = 0
        cancelled = False

        await self._broadcast({
            "type": "audio_start",
            "session_id": self.session_id,
            "avatar_id": job.avatar_id,
            "avatar_name": job.avatar_name,
            "utterance_type": job.utterance_type,
            "total_bytes": len(wav),
            "encoding": "wav",
        })

        while offset < len(wav) and not cancelled:
            if self._cancel_current.is_set():
                cancelled = True
                log.debug("output_manager.job_preempted", avatar=job.avatar_name)
                break

            chunk = wav[offset : offset + STREAM_CHUNK_BYTES]
            encoded = base64.b64encode(chunk).decode("ascii")
            await self._broadcast({
                "type": "audio_chunk",
                "session_id": self.session_id,
                "avatar_id": job.avatar_id,
                "data": encoded,
                "offset": offset,
            })
            offset += STREAM_CHUNK_BYTES
            chunk_count += 1
            await asyncio.sleep(0)

        await self._broadcast({
            "type": "audio_end",
            "session_id": self.session_id,
            "avatar_id": job.avatar_id,
            "avatar_name": job.avatar_name,
            "cancelled": cancelled,
        })
        await self._broadcast({
            "type": "avatar_speaking",
            "session_id": self.session_id,
            "avatar_id": job.avatar_id,
            "avatar_name": job.avatar_name,
            "utterance_type": job.utterance_type,
            "speaking": False,
        })
        self._gate.on_tts_end()
        log.debug(
            "output_manager.wav_done",
            avatar=job.avatar_name,
            bytes=len(wav),
            chunks=chunk_count,
            cancelled=cancelled,
        )

    async def _play_pcm_stream(self, job: AudioJob) -> None:
        """Stream raw PCM chunks from ElevenLabs directly to the browser."""
        self._gate.on_tts_start()
        await self._broadcast({
            "type": "avatar_speaking",
            "session_id": self.session_id,
            "avatar_id": job.avatar_id,
            "avatar_name": job.avatar_name,
            "utterance_type": job.utterance_type,
            "speaking": True,
        })

        await self._broadcast({
            "type": "audio_start",
            "session_id": self.session_id,
            "avatar_id": job.avatar_id,
            "avatar_name": job.avatar_name,
            "utterance_type": job.utterance_type,
            "total_bytes": -1,  # Unknown for streaming
            "encoding": "pcm_s16le",
            "sample_rate": job.sample_rate,
        })

        chunk_count = 0
        cancelled = False
        try:
            async for chunk in job.pcm_stream:
                if self._cancel_current.is_set():
                    cancelled = True
                    break
                if not chunk:
                    continue
                encoded = base64.b64encode(chunk).decode("ascii")
                await self._broadcast({
                    "type": "audio_chunk",
                    "session_id": self.session_id,
                    "avatar_id": job.avatar_id,
                    "data": encoded,
                })
                chunk_count += 1
                await asyncio.sleep(0)
        except Exception as e:
            log.error("output_manager.pcm_stream_error", error=str(e))

        await self._broadcast({
            "type": "audio_end",
            "session_id": self.session_id,
            "avatar_id": job.avatar_id,
            "avatar_name": job.avatar_name,
            "cancelled": cancelled,
        })
        await self._broadcast({
            "type": "avatar_speaking",
            "session_id": self.session_id,
            "avatar_id": job.avatar_id,
            "avatar_name": job.avatar_name,
            "utterance_type": job.utterance_type,
            "speaking": False,
        })
        self._gate.on_tts_end()
        log.debug(
            "output_manager.pcm_stream_done",
            avatar=job.avatar_name,
            chunks=chunk_count,
            cancelled=cancelled,
        )

"""
Deepgram streaming STT client.

Replaces the batch faster-whisper + Silero VAD path with a persistent
WebSocket connection to Deepgram's real-time transcription API.

Deepgram handles VAD and endpointing internally, firing a final transcript
callback when it detects the end of an utterance (configurable silence gap).

Usage:
    client = DeepgramSTTClient(
        on_final=my_async_callback,   # called with (text, confidence) per utterance
        on_interim=my_interim_cb,     # optional, called with (text,) per partial
    )
    await client.start()
    client.send(int16_bytes)          # called repeatedly with raw PCM
    await client.stop()
"""

from __future__ import annotations

import asyncio
import structlog
from typing import Callable, Awaitable

from app.config import get_settings

log = structlog.get_logger()

# Type aliases
OnFinalCb = Callable[[str, float], Awaitable[None]]   # (text, confidence)
OnInterimCb = Callable[[str], Awaitable[None]]        # (text,)


class DeepgramSTTClient:
    """
    Per-session Deepgram WebSocket streaming client.

    One instance per AudioPipeline / session. Not a singleton.
    """

    def __init__(
        self,
        on_final: OnFinalCb,
        on_interim: OnInterimCb | None = None,
    ):
        self._on_final = on_final
        self._on_interim = on_interim
        self._connection = None
        self._running = False

    # ── Lifecycle ─────────────────────────────────────────────────────────

    async def start(self) -> bool:
        """
        Open a Deepgram WebSocket connection.
        Returns True on success, False if API key missing or SDK unavailable.
        """
        settings = get_settings()
        if not settings.deepgram_api_key:
            log.warning("deepgram_stt.no_api_key")
            return False

        try:
            from deepgram import DeepgramClient, LiveTranscriptionEvents, LiveOptions
        except ImportError:
            log.error("deepgram_stt.sdk_not_installed",
                       hint="pip install deepgram-sdk")
            return False

        try:
            dg = DeepgramClient(settings.deepgram_api_key)
            self._connection = dg.listen.asyncwebsocket.v("1")

            # Wire event handlers
            self._connection.on(
                LiveTranscriptionEvents.Transcript,
                self._handle_transcript,
            )
            self._connection.on(
                LiveTranscriptionEvents.Close,
                self._handle_close,
            )
            self._connection.on(
                LiveTranscriptionEvents.Error,
                self._handle_error,
            )

            options = LiveOptions(
                model=settings.deepgram_model,
                encoding="linear16",
                sample_rate=16000,
                channels=1,
                interim_results=True,
                endpointing=settings.deepgram_endpointing_ms,
                smart_format=True,
                punctuate=True,
            )

            started = await self._connection.start(options)
            if not started:
                log.error("deepgram_stt.failed_to_start")
                return False

            self._running = True
            log.info("deepgram_stt.connected",
                     model=settings.deepgram_model,
                     endpointing_ms=settings.deepgram_endpointing_ms)
            return True

        except Exception as e:
            log.error("deepgram_stt.start_error", error=str(e))
            return False

    async def stop(self) -> None:
        """Close the Deepgram connection cleanly."""
        self._running = False
        if self._connection is not None:
            try:
                await self._connection.finish()
            except Exception as e:
                log.warning("deepgram_stt.stop_error", error=str(e))
            self._connection = None
        log.info("deepgram_stt.stopped")

    # ── Audio feed ────────────────────────────────────────────────────────

    def send(self, int16_bytes: bytes) -> None:
        """
        Send a raw PCM int16 audio chunk to Deepgram.
        Non-blocking — called from the audio WebSocket receive loop.
        """
        if not self._running or self._connection is None:
            return
        try:
            asyncio.ensure_future(self._connection.send(int16_bytes))
        except Exception as e:
            log.warning("deepgram_stt.send_error", error=str(e))

    # ── Event handlers ────────────────────────────────────────────────────

    async def _handle_transcript(self, _self, result, **kwargs) -> None:
        """Called by Deepgram SDK on each transcript event."""
        try:
            alt = result.channel.alternatives[0]
            text = alt.transcript.strip()
            if not text:
                return

            confidence = getattr(alt, "confidence", 1.0) or 1.0
            is_final = result.is_final
            speech_final = getattr(result, "speech_final", False)

            if speech_final or (is_final and not getattr(result, "interim_results", True)):
                # End of utterance — fire the main pipeline callback
                log.debug("deepgram_stt.final", text=text[:120],
                           confidence=round(confidence, 3))
                await self._on_final(text, confidence)
            elif is_final and self._on_interim:
                # Interim final (with interim_results=True) — optional early signal
                await self._on_interim(text)

        except (AttributeError, IndexError) as e:
            log.warning("deepgram_stt.transcript_parse_error", error=str(e))

    async def _handle_close(self, _self, close, **kwargs) -> None:
        log.info("deepgram_stt.closed", code=getattr(close, "code", None))
        self._running = False

    async def _handle_error(self, _self, error, **kwargs) -> None:
        log.error("deepgram_stt.error", error=str(error))

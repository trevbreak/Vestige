"""
Browser microphone WebSocket endpoint.

The browser captures mic audio via Web Audio API (PCM float32, 16 kHz, mono)
and streams 30 ms chunks as binary frames over this WebSocket.

The server feeds each chunk directly into the active session's AudioPipeline
(VAD → STT → context engine → LLM → TTS).

This replaces the previous sounddevice-based server-side mic capture.

WS URL: /ws/audio/{session_id}
Binary frames: raw PCM float32 little-endian, 16 kHz mono, 512 samples (~32 ms)
"""

from __future__ import annotations

import asyncio
import numpy as np
import time
import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.pipeline_manager import pipeline_manager

log = structlog.get_logger()
router = APIRouter(tags=["audio_ws"])

# ScriptProcessor requires power-of-2 buffer; browser sends 512 samples (~32 ms at 16 kHz)
CHUNK_SAMPLES = 512
BYTES_PER_CHUNK = CHUNK_SAMPLES * 4  # float32


@router.websocket("/ws/audio/{session_id}")
async def audio_stream(websocket: WebSocket, session_id: int):
    """
    Receive PCM audio chunks from the browser and feed them into the pipeline.

    Each binary frame is 512 float32 samples (2048 bytes); variable sizes are accepted and padded/truncated.
    Frames are converted to int16 and handed to the pipeline's VAD processor.
    """
    await websocket.accept()
    log.info("audio_ws.connected", session_id=session_id)

    pipeline = pipeline_manager.get_pipeline(session_id)
    if pipeline is None:
        await websocket.send_text('{"error": "pipeline not running for this session"}')
        await websocket.close()
        return

    # Buffers matching the pipeline's speech accumulation logic
    speech_buffer: list[np.ndarray] = []
    in_speech = False
    speech_start_ms = 0
    elapsed_samples = 0
    last_human_speech_at: float = 0.0

    settings = pipeline._vad.sample_rate  # just confirming sample_rate ref
    sample_rate = 16000

    # VAD probe: log peak speech probability every 100 chunks (~3s) for diagnostics
    _vad_probe_max: float = 0.0
    _vad_probe_count: int = 0
    _VAD_PROBE_INTERVAL = 100

    from app.config import get_settings

    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_bytes(), timeout=2.0)
            except asyncio.TimeoutError:
                # Check for silence-gap flush
                if in_speech and (time.monotonic() - last_human_speech_at) > 0.8:
                    if speech_buffer:
                        audio = np.concatenate(speech_buffer)
                        n_chunks = len(speech_buffer)
                        speech_buffer = []
                        in_speech = False
                        log.info("audio_ws.silence_flush", session_id=session_id,
                                 chunks=n_chunks, duration_ms=int(elapsed_samples / sample_rate * 1000) - speech_start_ms)
                        await pipeline._flush_buffer(
                            audio, speech_start_ms,
                            int(elapsed_samples / sample_rate * 1000)
                        )
                continue
            except WebSocketDisconnect:
                break

            # Accept variable-size frames; pad/truncate to CHUNK_SAMPLES
            n_floats = len(data) // 4
            if n_floats == 0:
                continue

            float_chunk = np.frombuffer(data, dtype=np.float32)
            # Convert float32 [-1,1] → int16
            int16_chunk = (float_chunk * 32767).clip(-32768, 32767).astype(np.int16)

            # Pad if short (browser may send a final partial frame)
            if len(int16_chunk) < CHUNK_SAMPLES:
                int16_chunk = np.pad(int16_chunk, (0, CHUNK_SAMPLES - len(int16_chunk)))

            elapsed_samples += len(int16_chunk)
            current_ms = int(elapsed_samples / sample_rate * 1000)

            # Skip if AEC gate is closed (TTS playing back)
            if not pipeline._gate.is_open():
                continue

            # Re-read threshold each chunk so settings changes take effect immediately
            vad_threshold = get_settings().vad_threshold
            speech_prob = pipeline._vad.process_chunk(int16_chunk)

            # VAD probe logging
            _vad_probe_max = max(_vad_probe_max, speech_prob)
            _vad_probe_count += 1
            if _vad_probe_count >= _VAD_PROBE_INTERVAL:
                log.info("audio_ws.vad_probe", session_id=session_id,
                          peak_prob=round(_vad_probe_max, 3), threshold=round(vad_threshold, 2),
                          triggered=_vad_probe_max >= vad_threshold)
                _vad_probe_max = 0.0
                _vad_probe_count = 0

            if speech_prob >= vad_threshold:
                if not in_speech:
                    in_speech = True
                    speech_start_ms = current_ms - 30
                    pipeline._context_engine.on_human_speech_start()
                    log.info("audio_ws.speech_start", session_id=session_id, speech_prob=round(speech_prob, 3))
                speech_buffer.append(int16_chunk)
                last_human_speech_at = time.monotonic()
                pipeline._last_human_speech_at = last_human_speech_at

            elif in_speech:
                in_speech = False
                pipeline._context_engine.on_human_speech_end()
                if speech_buffer:
                    audio = np.concatenate(speech_buffer)
                    n_chunks = len(speech_buffer)
                    speech_buffer = []
                    log.info("audio_ws.speech_end", session_id=session_id,
                             chunks=n_chunks, duration_ms=current_ms - speech_start_ms)
                    await pipeline._flush_buffer(audio, speech_start_ms, current_ms)

    except Exception as e:
        log.error("audio_ws.error", session_id=session_id, error=str(e))
    finally:
        log.info("audio_ws.disconnected", session_id=session_id)

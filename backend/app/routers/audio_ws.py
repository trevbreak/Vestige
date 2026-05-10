"""
Browser microphone WebSocket endpoint.

The browser captures mic audio via Web Audio API (PCM float32, 16 kHz, mono)
and streams chunks as binary frames over this WebSocket.

The server converts each frame to int16 and forwards it to the session's
DeepgramSTTClient, which handles VAD and endpointing. When Deepgram fires a
final transcript, it calls back into pipeline._on_transcript_final().

WS URL: /ws/audio/{session_id}
Binary frames: raw PCM float32 little-endian, 16 kHz mono, ~512 samples (~32 ms)
"""

from __future__ import annotations

import asyncio
import numpy as np
import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.pipeline_manager import pipeline_manager

log = structlog.get_logger()
router = APIRouter(tags=["audio_ws"])

CHUNK_SAMPLES = 512   # ScriptProcessor power-of-2 buffer size


@router.websocket("/ws/audio/{session_id}")
async def audio_stream(websocket: WebSocket, session_id: int):
    """
    Receive PCM audio chunks from the browser and forward to Deepgram.

    Each binary frame is ~512 float32 samples; converted to int16 before
    forwarding. Frames are dropped while the AEC gate is closed (TTS playing).
    """
    await websocket.accept()
    log.info("audio_ws.connected", session_id=session_id)

    pipeline = pipeline_manager.get_pipeline(session_id)
    if pipeline is None:
        await websocket.send_text('{"error": "pipeline not running for this session"}')
        await websocket.close()
        return

    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_bytes(), timeout=5.0)
            except asyncio.TimeoutError:
                continue
            except WebSocketDisconnect:
                break

            n_floats = len(data) // 4
            if n_floats == 0:
                continue

            # Skip if AEC gate is closed (avatar TTS is playing back)
            if not pipeline._gate.is_open():
                continue

            # Convert float32 → int16, pad to CHUNK_SAMPLES if needed
            float_chunk = np.frombuffer(data, dtype=np.float32)
            int16_chunk = (float_chunk * 32767).clip(-32768, 32767).astype(np.int16)
            if len(int16_chunk) < CHUNK_SAMPLES:
                int16_chunk = np.pad(int16_chunk, (0, CHUNK_SAMPLES - len(int16_chunk)))

            # Forward to Deepgram (fire-and-forget; non-blocking)
            stt = getattr(pipeline, "_deepgram_stt", None)
            if stt is not None:
                stt.send(int16_chunk.tobytes())

    except Exception as e:
        log.error("audio_ws.error", session_id=session_id, error=str(e))
    finally:
        log.info("audio_ws.disconnected", session_id=session_id)

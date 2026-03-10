"""
WebSocket endpoint for real-time transcript and audio streaming to the browser.

Message types sent to clients:
  { type: "transcript", session_id, entry: TranscriptEntry }
  { type: "pipeline_status", status: "started"|"stopped", session_id }
  { type: "avatar_speaking", session_id, avatar_id, avatar_name, utterance_type, speaking }
  { type: "audio_start", session_id, avatar_id, avatar_name, utterance_type, total_bytes }
  { type: "audio_chunk", session_id, avatar_id, data: base64, offset }
  { type: "audio_end", session_id, avatar_id, avatar_name, cancelled }
  { type: "pong" }

Messages received from clients:
  { type: "ping" }
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import json
import structlog

router = APIRouter(tags=["websocket"])
log = structlog.get_logger()


class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.active.append(ws)
        log.info("ws.connected", total=len(self.active))

    def disconnect(self, ws: WebSocket) -> None:
        try:
            self.active.remove(ws)
        except ValueError:
            pass
        log.info("ws.disconnected", total=len(self.active))

    async def broadcast(self, message: dict) -> None:
        data = json.dumps(message, default=str)
        dead = []
        for ws in list(self.active):
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def broadcast_transcript(self, session_id: int, entry) -> None:
        """Broadcast a TranscriptEntry dataclass as a JSON message."""
        payload = {
            "type": "transcript",
            "session_id": session_id,
            "entry": {
                "session_id": entry.session_id,
                "speaker": entry.speaker,
                "speaker_type": entry.speaker_type,
                "text": entry.text,
                "utterance_type": entry.utterance_type,
                "confidence": entry.confidence,
                "audio_start_ms": entry.audio_start_ms,
                "audio_end_ms": entry.audio_end_ms,
                "interrupt_score": entry.interrupt_score,
                "context_type": entry.context_type,
                "llm_route": entry.llm_route,
            },
        }
        await self.broadcast(payload)

    async def broadcast_pipeline_status(self, session_id: int, status: str) -> None:
        await self.broadcast({
            "type": "pipeline_status",
            "session_id": session_id,
            "status": status,
        })


manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                continue
            if msg.get("type") == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        log.error("ws.error", error=str(e))
        manager.disconnect(websocket)

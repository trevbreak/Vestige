"""
WebSocket endpoint for real-time transcript and audio push to the browser.
Phase 2+ will populate this with actual audio/transcript streaming.
For Phase 1, it provides a connection point and ping/pong.
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import json
import structlog

router = APIRouter(tags=["websocket"])
log = structlog.get_logger()


class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)
        log.info("ws.connected", total=len(self.active))

    def disconnect(self, ws: WebSocket):
        self.active.remove(ws)
        log.info("ws.disconnected", total=len(self.active))

    async def broadcast(self, message: dict):
        data = json.dumps(message)
        for ws in list(self.active):
            try:
                await ws.send_text(data)
            except Exception:
                self.active.remove(ws)


manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            if msg.get("type") == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        log.error("ws.error", error=str(e))
        manager.disconnect(websocket)

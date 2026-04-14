"""
WebSocket 路由 + 連線管理器
客戶端連線後會即時收到情緒更新推播
"""
import asyncio
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
router = APIRouter(tags=["websocket"])


class ConnectionManager:
    """管理所有 WebSocket 連線"""

    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)
        logger.info("WS connected. Total: %d", len(self.active))

    def disconnect(self, ws: WebSocket):
        self.active.remove(ws)
        logger.info("WS disconnected. Total: %d", len(self.active))

    async def broadcast(self, message: str):
        """廣播給所有連線中的客戶端，斷線的自動移除"""
        dead: list[WebSocket] = []
        for ws in self.active:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            try:
                self.active.remove(ws)
            except ValueError:
                pass


manager = ConnectionManager()


@router.websocket("/ws/sentiment")
async def sentiment_ws(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        # 心跳：每 30 秒 ping 一次，確保連線存活
        while True:
            try:
                # 等待客戶端 ping 或逾時
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                if data == "ping":
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
                await websocket.send_text('{"type":"heartbeat"}')
    except WebSocketDisconnect:
        manager.disconnect(websocket)

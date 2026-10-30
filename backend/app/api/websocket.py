"""
backend/app/api/websocket.py

WS /ws/runs/{run_id}?token=<JWT>

클라이언트가 연결하면 JWT를 검증한 뒤 run_id 기반으로 WebSocketManager에 등록.
인증 실패 시 4001 코드로 즉시 연결 종료.
통제관은 담당 제대에 지정된 모드의 run 만 구독할 수 있다 (REST 와 같은 검사, 아니면 4003 으로 종료).
"""

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.security import _decode_token
from app.core.websocket_manager import ws_manager
from app.db.session import AsyncSessionLocal
from app.services.run_data import RunDataError, check_run_access

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/runs/{run_id}")
async def websocket_endpoint(run_id: int, ws: WebSocket, token: str | None = None):
    # JWT 인증 — query param ?token=<JWT>
    try:
        payload = _decode_token(token)
    except Exception:
        logger.warning("WS auth failed for run_id=%s", run_id)
        await ws.close(code=4001)   # 4001: 인증 실패
        return
    try:                            # 통제관은 지정된 모드의 run 만 (REST 의 run_path_guard 와 같은 검사)
        async with AsyncSessionLocal() as db:
            await check_run_access(db, run_id, payload)
    except RunDataError:
        logger.warning("WS mode access denied run_id=%s", run_id)
        await ws.close(code=4003)   # 4003: 권한 없음
        return

    await ws_manager.connect(run_id, ws)
    try:
        while True:
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        await ws_manager.disconnect(run_id, ws)

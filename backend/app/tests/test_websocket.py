"""
backend/app/tests/test_websocket.py

WebSocket 인증/연결 테스트 (Starlette TestClient 사용 — 추가 의존성 없음).
"""

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.security import create_access_token
from app.main import app


def test_ws_rejects_missing_token():
    with TestClient(app) as tc:
        with pytest.raises(WebSocketDisconnect) as exc:
            with tc.websocket_connect("/ws/runs/1"):
                pass
    assert exc.value.code == 4001


def test_ws_rejects_invalid_token():
    with TestClient(app) as tc:
        with pytest.raises(WebSocketDisconnect) as exc:
            with tc.websocket_connect("/ws/runs/1?token=not-a-jwt"):
                pass
    assert exc.value.code == 4001


def test_ws_connect_and_ping():
    token = create_access_token(subject="1", role="commander")
    with TestClient(app) as tc:
        with tc.websocket_connect(f"/ws/runs/1?token={token}") as ws:
            ws.send_text("ping")
            assert ws.receive_text() == "pong"

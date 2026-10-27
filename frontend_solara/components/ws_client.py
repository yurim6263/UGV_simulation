"""
frontend/components/ws_client.py

WebSocket 클라이언트 — 단일 구현체.
백엔드 WS /ws/runs/{run_id}?token=<JWT> 에 연결하고,
수신 메시지를 전역 상태(state + api_client reactives) 양쪽에 반영합니다.

공개 API:
  connect(run_id, token)   — 직접 연결 (token 명시)
  disconnect()             — 연결 종료
  start_live_updates(run_id) — api_client.auth_token 자동 사용
  stop_live_updates()      — 연결 종료 + api_client 상태 초기화
  WsStatusBadge            — 연결 상태 배지 컴포넌트
"""

import json
import os
import threading

import solara
import websocket  # websocket-client 라이브러리

import state

BACKEND_WS_URL = os.getenv("BACKEND_WS_URL", "ws://localhost:8000")

_ws_app: websocket.WebSocketApp | None = None
_ws_thread: threading.Thread | None = None


# ── 메시지 타입별 핸들러 ──────────────────────────────────────────

def _apply_ws_message(msg: dict) -> None:
    """
    WS 메시지를 파싱해 api_client reactives에 반영.
    (api_client.py 에 있던 _apply_ws_message 를 이전)
    """
    from services import api_client as _ac  # 지연 임포트 — 순환 참조 방지

    msg_type = msg.get("type")

    _STATUS_LABEL = {
        "CREATED":   "진행 전",
        "RUNNING":   "진행중",
        "COMPLETED": "진행 완료",
        "FAILED":    "실패",
        "CANCELLED": "취소",
    }

    if msg_type == "run_status":
        if msg.get("mission_success_rate") is not None:
            _ac.success_rate.set(int(msg["mission_success_rate"]))
        if msg.get("asset_damage_rate") is not None:
            _ac.asset_damage.set(int(msg["asset_damage_rate"]))
        if msg.get("status"):
            _ac.status.set(_STATUS_LABEL.get(msg["status"], msg["status"]))
        if msg.get("remaining_time_hms"):
            _ac.time_left.set(msg["remaining_time_hms"])
        if msg.get("aoi_remaining_hms"):
            _ac.patrol_area.set(msg["aoi_remaining_hms"])

    elif msg_type == "route.updated":
        payload = msg.get("payload", {})
        if payload.get("event") == "replan_suggested":
            state.pending_route.set({
                "unit_id":  payload.get("unit_id", "UGV"),
                "path_geom": payload.get("path_geom"),
                "trigger":  payload.get("trigger_label", "환경 변화 감지"),
            })
            _ac.replan_available.set(True)

    elif msg_type == "unit_update":
        pass  # 맵 뷰에서 직접 처리

    elif msg_type == "sos_triggered":
        asset_code = msg.get("asset_code", "UGV")
        current = _ac.queue_data.value[:]
        current.append({"id": asset_code, "dist": "0m"})
        _ac.queue_data.set(current)

    elif msg_type == "sos_resolved":
        asset_code = msg.get("asset_code")
        current = [q for q in _ac.queue_data.value if q["id"] != asset_code]
        _ac.queue_data.set(current)

    # 최근 50개 메시지 유지 (api_client.ws_messages)
    current_msgs = _ac.ws_messages.value[-49:]
    _ac.ws_messages.set(current_msgs + [msg])


# ── WebSocketApp 콜백 ────────────────────────────────────────────

def _on_message(ws, raw: str):
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        msg = {"raw": raw}

    # state.* 갱신 (팀원 코드 원본 핸들러)
    if msg.get("type") == "simulation_result":
        state.latest_result.value = msg.get("data")
    if msg.get("type") == "path_update":
        state.optimal_paths.value = msg.get("data", [])

    # api_client.* 갱신
    _apply_ws_message(msg)

    # state.ws_messages 갱신
    current = state.ws_messages.value[-49:]
    state.ws_messages.value = current + [msg]


def _on_open(ws):
    state.ws_connected.value = True
    from services import api_client as _ac
    _ac.ws_connected.set(True)
    _ac.connection_status.set("WebSocket 연결됨")


def _on_close(ws, close_status_code, close_msg):
    state.ws_connected.value = False
    from services import api_client as _ac
    _ac.ws_connected.set(False)
    _ac.connection_status.set("연결 종료")


def _on_error(ws, error):
    state.ws_connected.value = False
    state.error_message.value = f"WebSocket 오류: {error}"
    from services import api_client as _ac
    _ac.ws_connected.set(False)
    _ac.connection_status.set("WebSocket 재연결 중")


# ── 공개 API ─────────────────────────────────────────────────────

def connect(run_id: int, token: str = "") -> None:
    """주어진 run_id에 대한 WebSocket 연결을 시작합니다."""
    global _ws_app, _ws_thread

    disconnect()  # 기존 연결 정리

    url = f"{BACKEND_WS_URL}/ws/runs/{run_id}?token={token}"
    _ws_app = websocket.WebSocketApp(
        url,
        on_open=_on_open,
        on_message=_on_message,
        on_close=_on_close,
        on_error=_on_error,
    )
    _ws_thread = threading.Thread(
        target=_ws_app.run_forever,
        kwargs={"reconnect": 5},  # 5초마다 재연결 시도
        daemon=True,
    )
    _ws_thread.start()


def disconnect() -> None:
    """현재 WebSocket 연결을 종료합니다."""
    global _ws_app
    if _ws_app:
        _ws_app.close()
        _ws_app = None
    state.ws_connected.value = False


def start_live_updates(run_id: int) -> None:
    """
    run_id로 WS 연결 시작. api_client.auth_token을 자동으로 사용.
    대시보드 진입 시 호출.
    """
    from services.api_client import auth_token, active_run_id, refresh_dashboard
    active_run_id.set(run_id)
    connect(run_id, auth_token.value)
    # 초기 REST 갱신
    threading.Thread(target=refresh_dashboard, args=(run_id,), daemon=True).start()


def stop_live_updates() -> None:
    """WS 연결 종료 및 api_client 상태 초기화."""
    disconnect()
    from services import api_client as _ac
    _ac.ws_connected.set(False)
    _ac.connection_status.set("연결 종료")
    _ac.active_run_id.set(None)


@solara.component
def WsStatusBadge():
    """연결 상태 배지 — 다른 컴포넌트에서 임베드해서 사용."""
    color = "green" if state.ws_connected.value else "red"
    label = "● 연결됨" if state.ws_connected.value else "● 연결 끊김"
    solara.Text(label, style={"color": color, "fontSize": "0.85rem", "fontWeight": "bold"})

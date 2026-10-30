"""
frontend/services/api_client.py

전역 반응형 상태 + 백엔드 통신 유틸.

역할:
  1. Solara reactive 상태 저장소 (UI 상태 + KPI 값)
  2. 로그인 / 버튼 / 지도 탭 상태 관리
  3. FastAPI REST / WebSocket 연결 및 snapshot 반영

내 백엔드 엔드포인트:
  POST /api/auth/login          → JWT 인증
  GET  /api/runs/{run_id}/status
  GET  /api/runs/{run_id}/ugv-count
  GET  /api/runs/{run_id}/route-effect
  GET  /api/runs/{run_id}/queue/danger
  WS   /api/ws/{run_id}
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any

import requests
import solara

from components.state import (
    active_btn,
    selected_mission_mode,
    operating_ugv_plan,
    departure_times,
    ARRIVAL_TIMES_BY_MODE,
    MISSION_UGV_PLAN_BY_MODE,
)

# =========================================================
# 백엔드 연결 설정
# =========================================================
BACKEND_HTTP_BASE = os.getenv("BACKEND_URL", "http://127.0.0.1:8001")
BACKEND_WS_BASE   = os.getenv("BACKEND_WS_URL", "ws://127.0.0.1:8001")

# =========================================================
# 공통 UI 상태
# =========================================================
current_page       = solara.reactive("login")   # login | input | route_plan | main
connection_status  = solara.reactive("연결 전")
message_text       = solara.reactive("")

# ── reactive 상태 ───────────────────────────────────────────
home_role = solara.reactive("commander")          # commander | operator
home_role_label = solara.reactive("지휘관")
home_current_time = solara.reactive("2026.04.10 14:00")
home_remaining_time = solara.reactive("02:00:34")
home_mission_notice = solara.reactive("")
home_unit_label = solara.reactive("")
home_asset_modes = solara.reactive([])
selected_asset_mode = solara.reactive("balanced")

# ── 로그인 상태 ───────────────────────────────────────────
NICKNAMES = {"user1": "1제대", "user2": "2제대", "user3": "3제대"}
UGV_ICONS = {1: "①", 2: "②", 3: "③", 4: "④"}

is_logged_in    = solara.reactive(False)
input_username  = solara.reactive("")
input_password  = solara.reactive("")
login_error     = solara.reactive(False)
logged_in_user  = solara.reactive("")
auth_token      = solara.reactive("")    # Access Token
refresh_token   = solara.reactive("")    # Refresh Token

# ── 팀원 코드: 역할 기반 워크플로우 상태 ─────────────────────
# (팀원 api_client.py에서 추가된 상태 변수들)

# 로컬 임시 계정 (백엔드 미연결 시 폴백용)
USER_DB = {
    "user1": "user1",
    "user2": "user2",
    "user3": "user3",
    "admin": "admin",
}

# 현재 로그인한 사용자의 역할 (commander | controller)
user_role = solara.reactive("")

# 지휘관이 입력/시뮬레이션을 완료했는지 여부 (통제관 로그인 허용 조건)
commander_data_ready = solara.reactive(False)

# 로딩 단계 완료 여부 (CommanderPage 진입 가능 여부)
simulation_done = solara.reactive(False)

# 현재 진행 단계: 0=입력창, 1=로딩/편성, 2=메인대시보드
workflow_step = solara.reactive(0)

# 지휘관이 입력한 제대별 목적지 좌표
destination_data = solara.reactive({
    "user1": {"lat": 0.0, "lng": 0.0},
    "user2": {"lat": 0.0, "lng": 0.0},
    "user3": {"lat": 0.0, "lng": 0.0},
})

# 지휘관이 작성한 임무 메모
mission_note = solara.reactive("")

# 작전 설정 전역 상태
mission_settings = solara.reactive({
    "ugv_count": 12,
    "unit_count": 3,
    "all_controller_count": 3,
    "start_point": {"lat": 54.77, "lng": 18.41},
    "start_time": "02:00:00",
    "end_time": "08:00:00",
    "recon_times": {
        "user1": "00:30:00",
        "user2": "01:00:00",
        "user3": "00:30:00",
    },
    "controllers": {"user1": 1, "user2": 1, "user3": 1},
    "lost_ugv": {"user1": 0, "user2": 0, "user3": 0},
    "operable_ugv": {"user1": 0, "user2": 0, "user3": 0},
    # 제대별 출발/도착 예정 시각 (시뮬레이션 결과로 갱신 가능)
    "depart_times": {
        "user1": "02:20:00",
        "user2": "02:10:00",
        "user3": "02:30:00",
    },
    "arrive_times": {
        "user1": "07:30:00",
        "user2": "08:30:00",
        "user3": "08:00:00",
    },
})

# LTWR 맵 줌 레벨 (팀원 코드: zoom_levels)
zoom_levels = {
    "T":    solara.reactive(1.0),
    "T+1":  solara.reactive(1.0),
    "T+2":  solara.reactive(1.0),
    "T+3":  solara.reactive(1.0),
}

# 정찰 구역 남은 시간 (팀원 코드: recon_time — 기존 patrol_area와 동일 개념)
recon_time = solara.reactive("00:30:00")

# ── 상단 제어 버튼 상태 ──────────────────────────────────
#active_btn      = solara.reactive("")
map_selection   = solara.reactive("위험도")
replan_available = solara.reactive(False)

# ── 상세 패널 상태 ────────────────────────────────────────
selected_unit_id = solara.reactive(None)
selected_detail  = solara.reactive(None)

# ── 실행 상태 ─────────────────────────────────────────────
active_run_id    = solara.reactive(None)   # 현재 실행 중인 run_id
ws_connected     = solara.reactive(False)
ws_messages      = solara.reactive([])

# ── LTWR 슬롯 (T0~T3 HTML 맵 URL) ────────────────────────
# 각 값은 None(미수신) 또는 "/ltwr-maps/T0.html" 형태의 URL
ltwr_slots = solara.reactive({
    "T0": None,
    "T1": None,
    "T2": None,
    "T3": None,
})
ltwr_labels = solara.reactive({
    "T0": "T+0: Present Status",
    "T1": "T+1: Prediction",
    "T2": "T+2: Prediction",
    "T3": "T+3: Prediction",
})

# ── 제대별 KPI (지휘관 차트 ↔ 통제관 수치 공유) ──────────────
# 지휘관 차트와 각 통제관 화면이 이 reactive 하나를 공유한다.
# 임무 하달(POST) 시 백엔드에 저장, 브리핑 조회(GET) 시 갱신된다.
unit_kpi_data = solara.reactive({
    "user1": {"success": 78, "risk": 35},
    "user2": {"success": 64, "risk": 57},
    "user3": {"success": 86, "risk": 22},
})

# ── 상단 KPI 표시값 (백엔드 API 또는 WS 에서 갱신) ────────
success_rate  = solara.reactive(78)       # 임무성공률 (%)
asset_damage  = solara.reactive(13)       # 자산피해율 (%)
status        = solara.reactive("진행중")  # 진행 상황
time_left     = solara.reactive("00:12:34")  # 남은 시간
patrol_area   = solara.reactive("00:30:00")  # 정찰구역 시간

# ── 좌측 패널 표시값 ─────────────────────────────────────
ratio_x        = solara.reactive(4)        # 운용 UGV 수
effect_success = solara.reactive(12)       # 현재경로 효과 - 임무성공률 delta
effect_damage  = solara.reactive(-7)       # 현재경로 효과 - 자산피해율 delta
queue_data     = solara.reactive([
    {"id": "UGV-2", "dist": "12m"},
    {"id": "UGV-1", "dist": "7m"},
])

# ── 임무 입력 변수 (2페이지) ──────────────────────────
input_ugv_count      = solara.reactive(2)
input_success_thresh = solara.reactive(70)   # 임무성공률 기준 (%)
input_damage_thresh  = solara.reactive(20)   # 자산피해율 기준 (%)
input_patrol_count   = solara.reactive(3)    # 정찰 구역 수
input_action_radius  = solara.reactive(5)    # 활동 반경 (km)

# ── 제대별 정찰 목표 (InputPage map + table) ──────────
# 각 항목: {label, lat, lon, patrol_time (HH:MM:SS)}
echelon_targets = solara.reactive([
    {"label": "제대1", "lat": None, "lon": None, "patrol_time": "00:30:00"},
    {"label": "제대2", "lat": None, "lon": None, "patrol_time": "01:00:00"},
    {"label": "제대3", "lat": None, "lon": None, "patrol_time": "01:00:00"},
])
active_echelon_idx = solara.reactive(0)   # 지도 클릭 시 좌표 적용할 제대 인덱스
active_mission_id  = solara.reactive(None)  # 생성된 mission id (int | None)

# ── 경로 옵션 / 파레토 (3페이지) ─────────────────────
ROUTE_OPTIONS: list[dict] = [
    {
        "id": "A", "label": "A안 (고성공)",
        "success_rate": 88, "damage_rate": 28,
        "distance_km": 12, "eta_min": 35,
        "path": [[37.45,127.42],[37.47,127.47],[37.50,127.52],[37.53,127.56],[37.55,127.58]],
    },
    {
        "id": "B", "label": "B안 (균형)",
        "success_rate": 75, "damage_rate": 15,
        "distance_km": 15, "eta_min": 42,
        "path": [[37.45,127.42],[37.43,127.46],[37.46,127.51],[37.50,127.55],[37.53,127.57],[37.55,127.58]],
    },
    {
        "id": "C", "label": "C안 (저피해)",
        "success_rate": 62, "damage_rate": 7,
        "distance_km": 20, "eta_min": 58,
        "path": [[37.45,127.42],[37.40,127.44],[37.37,127.49],[37.40,127.54],[37.45,127.58],[37.50,127.60],[37.55,127.58]],
    },
]
route_options     = solara.reactive(list(ROUTE_OPTIONS))
selected_route_id = solara.reactive("B")

# =========================================================
# 공통 인증 헤더
# =========================================================
def _auth_headers() -> dict[str, str]:
    token = auth_token.value
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}

# =========================================================
# 홈 요약 API 호출
# =========================================================
def fetch_home_summary() -> dict[str, Any] | None:
    try:
        resp = requests.get(
            f"{BACKEND_HTTP_BASE}/api/runs/home/summary",
            headers=_auth_headers(),
            timeout=5,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None

# =========================================================
# 홈 상태 반영 함수
# =========================================================
def refresh_home_summary() -> None:
    data = fetch_home_summary()
    if not data:
        return

    home_role.set(data.get("role", "commander"))
    home_role_label.set(data.get("role_label", "지휘관"))
    home_current_time.set(data.get("current_time", ""))
    home_remaining_time.set(data.get("remaining_time", "02:00:34"))
    home_mission_notice.set(data.get("mission_notice") or "")
    home_unit_label.set(data.get("unit_label") or "")
    home_asset_modes.set(data.get("asset_modes", []))
    selected_asset_mode.set(data.get("selected_mode", "balanced"))

    # 기존 UI 변수와도 동기화
    time_left.set(data.get("remaining_time", "02:00:34"))

    # 통제관일 때 좌측 카드 이름도 같이 맞춤
    if data.get("role") == "operator" and data.get("unit_label"):
        logged_in_user.set("operator")

# =========================================================
# 버튼 선택 함수
# =========================================================
def set_selected_asset_mode(mode_key: str) -> None:
    selected_asset_mode.set(mode_key)

# =========================================================
# UI 보조 함수
# =========================================================

def attempt_login():
    """
    로그인 처리.
    1단계: POST /api/auth/login 백엔드 JWT 인증 시도
    2단계: 백엔드 미연결 시 로컬 USER_DB 폴백 (팀원 코드 로직)
    3단계: 역할(commander/controller) 판별 및 workflow_step 설정 (팀원 코드 로직)
    """
    u = input_username.value.strip()
    p = input_password.value.strip()

    if not u or not p:
        login_error.set(True)
        message_text.set("아이디 또는 비밀번호를 입력해 주세요.")
        return

    # ── 1단계: 백엔드 JWT 인증 시도 (내 코드) ─────────────────
    backend_ok = False
    try:
        resp = requests.post(
            f"{BACKEND_HTTP_BASE}/api/auth/login",
            json={"username": u, "password": p},
            timeout=5,
        )
        if resp.status_code == 200:
            data = resp.json()
            auth_token.set(data.get("access_token", ""))
            refresh_token.set(data.get("refresh_token", ""))
            backend_ok = True
        elif resp.status_code in (401, 403):
            login_error.set(True)
            message_text.set("아이디 또는 비밀번호가 올바르지 않습니다.")
            return
    except Exception:
        # 백엔드 미연결 → 로컬 USER_DB 폴백 (팀원 코드)
        pass

    # ── 2단계: 폴백 — 로컬 USER_DB 검증 (팀원 코드) ──────────
    if not backend_ok:
        if u not in USER_DB or USER_DB[u] != p:
            login_error.set(True)
            message_text.set("아이디 또는 비밀번호가 올바르지 않습니다.")
            return

    # ── 3단계: 역할 판별 및 워크플로우 설정 (팀원 코드 로직) ───
    if u == "admin":
        # 지휘관 로그인
        logged_in_user.set(u)
        is_logged_in.set(True)
        login_error.set(False)
        user_role.set("commander")
        workflow_step.set(0)
        message_text.set("")
    else:
        # 통제관 로그인 — 지휘관이 먼저 준비를 완료해야 함 (팀원 코드)
        if not commander_data_ready.value:
            is_logged_in.set(False)
            login_error.set(True)
            user_role.set("")
            logged_in_user.set("")
            workflow_step.set(0)
            message_text.set("아직 지휘관이 임무 입력 및 시뮬레이션을 완료하지 않았습니다.")
            return

        logged_in_user.set(u)
        is_logged_in.set(True)
        login_error.set(False)
        user_role.set("controller")
        workflow_step.set(0)
        message_text.set("")


def go_home() -> None:
    """로그인 화면으로 돌아가기 — refresh token 폐기 후 상태 초기화."""
    # 서버에 refresh token 폐기 요청 (내 코드 — 실패해도 로컬 상태는 초기화)
    rt = refresh_token.value
    if rt:
        try:
            requests.post(
                f"{BACKEND_HTTP_BASE}/api/auth/logout",
                json={"refresh_token": rt},
                timeout=3,
            )
        except Exception:
            pass

    is_logged_in.set(False)
    input_username.set("")
    input_password.set("")
    login_error.set(False)
    logged_in_user.set("")
    active_btn.set("실행")
    auth_token.set("")
    refresh_token.set("")
    current_page.set("login")
    from components import ws_client as _ws
    _ws.stop_live_updates()

    # 팀원 코드: 역할/단계 초기화 (다음 로그인 시 처음부터 시작)
    user_role.set("")
    workflow_step.set(0)
    message_text.set("")


# ── UGV 이동 시뮬레이션 ──────────────────────────────────
import time as _time_module

_movement_thread: threading.Thread | None = None
_movement_stop   = threading.Event()


def _parse_hms(hms: str) -> int:
    """HH:MM:SS → 초"""
    try:
        p = hms.split(":")
        return int(p[0]) * 3600 + int(p[1]) * 60 + int(p[2])
    except Exception:
        return 0


def _fmt_hms(sec: int) -> str:
    sec = max(0, sec)
    return f"{sec//3600:02d}:{(sec%3600)//60:02d}:{sec%60:02d}"


def _lerp_route(coords: list, progress: float) -> tuple[float, float]:
    """coords: [[lon,lat],...], progress 0-1 → (lat, lon)"""
    if not coords:
        return (0.0, 0.0)
    progress = max(0.0, min(1.0, progress))
    n = len(coords) - 1
    if n <= 0:
        return (coords[0][1], coords[0][0])
    t = progress * n
    i = min(int(t), n - 1)
    f = t - i
    c1, c2 = coords[i], coords[i + 1]
    return (c1[1] + (c2[1] - c1[1]) * f, c1[0] + (c2[0] - c1[0]) * f)


def _movement_loop(total_sec: int) -> None:
    import state as _state
    REAL_SEC_PER_STEP = 3.0   # 실제 3초 = 시뮬 10분
    SIM_SEC_PER_STEP  = 600   # 10분

    remaining = total_sec
    while not _movement_stop.is_set() and remaining > 0:
        _time_module.sleep(REAL_SEC_PER_STEP)
        if _movement_stop.is_set():
            break
        remaining = max(0, remaining - SIM_SEC_PER_STEP)
        time_left.set(_fmt_hms(remaining))

        progress = 1.0 - (remaining / total_sec)
        num_ugvs = max(1, int(ratio_x.value))
        new_positions = []

        for path in _state.optimal_paths.value:
            coords = path.get("path_geom", {}).get("coordinates", [])
            if not coords:
                continue
            for i in range(num_ugvs):
                # UGV마다 약간 간격을 두고 출발
                offset = i * 0.06
                p = max(0.0, progress - offset)
                lat, lon = _lerp_route(coords, p)
                new_positions.append({
                    "unit_id": f"UGV-{i+1}",
                    "lat": lat,
                    "lon": lon,
                })

        _state.ugv_positions.set(new_positions)

        if remaining <= 0:
            _state.ugv_running.set(False)
            active_btn.set("종료")
            break


def _start_ugv_movement() -> None:
    global _movement_thread
    _stop_ugv_movement()
    import state as _state
    total_sec = _parse_hms(time_left.value)
    if total_sec <= 0:
        total_sec = 3600
    _state.ugv_running.set(True)
    _movement_stop.clear()
    _movement_thread = threading.Thread(
        target=_movement_loop, args=(total_sec,), daemon=True
    )
    _movement_thread.start()


def _stop_ugv_movement() -> None:
    global _movement_thread
    _movement_stop.set()
    if _movement_thread and _movement_thread.is_alive():
        _movement_thread.join(timeout=1.5)
    _movement_thread = None
    _movement_stop.clear()


def set_active_button(name: str) -> None:
    active_btn.set(name)

    if name in MISSION_UGV_PLAN_BY_MODE:
        selected_mission_mode.set(name)
        operating_ugv_plan.set(dict(MISSION_UGV_PLAN_BY_MODE[name]))
        departure_times.set({
            "user1": "03:00:00",
            "user2": "03:00:00",
            "user3": "03:00:00",
        })
        return

    if name == "실행":
        _start_ugv_movement()
        if active_run_id.value:
            _send_command("resume")

    elif name == "종료":
        _stop_ugv_movement()
        if active_run_id.value:
            _send_command("stop")


def set_map_selection(name: str) -> None:
    map_selection.set(name)


def refresh_ltwr_slots() -> None:
    """백엔드 /api/ltwr/slots 에서 슬롯 정보를 가져와 갱신."""
    try:
        resp = requests.get(f"{BACKEND_HTTP_BASE}/api/ltwr/slots", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            new_slots = {}
            new_labels = {}
            for item in data.get("slots", []):
                slot = item["slot"]
                new_slots[slot] = item.get("url")
                new_labels[slot] = item.get("label", slot)
            ltwr_slots.set(new_slots)
            ltwr_labels.set(new_labels)
    except Exception:
        pass


def _hms_to_sec(hms: str) -> int:
    """HH:MM:SS → 초. 파싱 실패 시 1800."""
    try:
        p = hms.strip().split(":")
        return int(p[0]) * 3600 + int(p[1]) * 60 + int(p[2])
    except Exception:
        return 1800


def submit_mission() -> None:
    """
    제대별 정찰 목표를 백엔드에 제출하고 메인 대시보드로 이동.
    백엔드 미연결 시 로컬 상태만 갱신 후 진행.
    """
    targets = echelon_targets.value

    import state as _st

    valid = [t for t in targets if t.get("lat") is not None and t.get("lon") is not None]

    # optimal_paths에는 LineString만 설정 (Point 설정 시 map_view.py에서 오류)
    # 좌표가 하나뿐이면 경로 표시 없이 마커만 사용 → 빈 리스트
    _st.optimal_paths.set([])

    # UGV 위치는 첫 번째 목표지점에 배치
    if valid:
        start = valid[0]
        _st.ugv_positions.set([
            {"unit_id": f"UGV-{i+1}", "lat": start["lat"], "lon": start["lon"]}
            for i in range(max(1, input_ugv_count.value))
        ])

    ratio_x.set(max(1, input_ugv_count.value))

    # ── 백엔드 API 호출 ────────────────────────────────────────────────
    try:
        dep_lat = valid[0]["lat"] if valid else 37.50
        dep_lon = valid[0]["lon"] if valid else 127.00

        mission_resp = _http("POST", "/api/missions", json={
            "name": f"{logged_in_user.value or 'CMD'} 임무",
            "echelon_no": 1,
            "total_ugv": max(1, input_ugv_count.value),
            "max_ugv_count": max(1, input_ugv_count.value),
            "mission_duration_min": 120,
            "departure_lat": dep_lat,
            "departure_lon": dep_lon,
        })

        if mission_resp.status_code == 201:
            mid = mission_resp.json().get("id")
            active_mission_id.set(mid)

            target_body = []
            for i, t in enumerate(targets, 1):
                if t.get("lat") is not None and t.get("lon") is not None:
                    target_body.append({
                        "seq": i,
                        "lat": t["lat"],
                        "lon": t["lon"],
                        "patrol_duration_sec": _hms_to_sec(t["patrol_time"]),
                    })
            if target_body and mid:
                _http("POST", f"/api/missions/{mid}/targets", json=target_body)

            # run 생성 → active_run_id 설정 (WS 연결에 필요)
            if mid:
                run_resp = _http("POST", f"/api/missions/{mid}/runs")
                if run_resp.status_code == 201:
                    run_id = run_resp.json().get("id")
                    if run_id:
                        active_run_id.set(run_id)

    except Exception:
        pass

    # 로딩 페이지 → 3초 후 메인으로 전환
    current_page.set("loading")


def go_to_route_plan() -> None:
    """입력 변수 제출 → 경로 계획 페이지 (mock 경로 옵션 사용)."""
    route_options.set(list(ROUTE_OPTIONS))
    selected_route_id.set("B")
    current_page.set("route_plan")


def confirm_route() -> None:
    """선택 경로 확정 → KPI 초기값 갱신 후 메인 페이지로."""
    import state
    rid = selected_route_id.value
    route = next((r for r in route_options.value if r["id"] == rid), None)
    if route:
        ratio_x.set(input_ugv_count.value)
        success_rate.set(route["success_rate"])
        asset_damage.set(route["damage_rate"])
        others = [r for r in route_options.value if r["id"] != rid]
        if others:
            avg_s = sum(r["success_rate"] for r in others) / len(others)
            avg_d = sum(r["damage_rate"] for r in others) / len(others)
            effect_success.set(int(round(route["success_rate"] - avg_s)))
            effect_damage.set(int(round(route["damage_rate"] - avg_d)))

        # 선택 경로를 메인 맵(state.optimal_paths)에 반영
        coords = [[lon, lat] for lat, lon in route["path"]]
        state.optimal_paths.set([{
            "unit_id": f"{rid}안",
            "path_geom": {
                "type": "LineString",
                "coordinates": coords,
            },
        }])

        # ETA 기반으로 남은 시간 설정
        eta_min = route.get("eta_min", 60)
        time_left.set(f"00:{eta_min:02d}:00")

        # UGV를 출발지에 배치 (progress=0)
        num_ugvs = max(1, int(input_ugv_count.value))
        start = coords[0]  # [lon, lat]
        state.ugv_positions.set([
            {"unit_id": f"UGV-{i+1}", "lat": start[1], "lon": start[0]}
            for i in range(num_ugvs)
        ])

    current_page.set("main")


def open_unit_detail(detail_type: str, unit_id: str) -> None:
    selected_unit_id.value = unit_id
    selected_detail.value = {"type": detail_type, "unit_id": unit_id}


def close_unit_detail() -> None:
    selected_detail.value = None


def request_replan() -> None:
    if not replan_available.value:
        return
    import state as _state
    pending = _state.pending_route.value
    if pending and pending.get("path_geom"):
        # 제안 경로를 현재 경로로 확정
        _state.optimal_paths.set([{
            "unit_id": pending["unit_id"],
            "path_geom": pending["path_geom"],
        }])
        _state.pending_route.set(None)
    replan_available.set(False)
    message_text.set("경로 수정 완료")
    if active_run_id.value:
        _send_command("replan")


# =========================================================
# REST 호출 (내 백엔드)
# =========================================================

def _headers() -> dict:
    t = auth_token.value
    return {"Authorization": f"Bearer {t}"} if t else {}


def _try_refresh() -> bool:
    """Refresh token으로 새 access token 발급 시도. 성공 시 True."""
    rt = refresh_token.value
    if not rt:
        return False
    try:
        resp = requests.post(
            f"{BACKEND_HTTP_BASE}/api/auth/refresh",
            json={"refresh_token": rt},
            timeout=5,
        )
        if resp.status_code == 200:
            data = resp.json()
            auth_token.set(data.get("access_token", ""))
            refresh_token.set(data.get("refresh_token", ""))
            return True
    except Exception:
        pass
    return False


def _http(method: str, path: str, **kwargs) -> Any:
    resp = requests.request(
        method,
        f"{BACKEND_HTTP_BASE}{path}",
        headers=_headers(),
        timeout=5,
        **kwargs,
    )
    # access token 만료(401) 시 refresh 후 1회 재시도
    if resp.status_code == 401 and _try_refresh():
        resp = requests.request(
            method,
            f"{BACKEND_HTTP_BASE}{path}",
            headers=_headers(),
            timeout=5,
            **kwargs,
        )
    return resp


def _send_command(action: str) -> None:
    rid = active_run_id.value
    if not rid:
        return
    try:
        _http("POST", f"/api/runs/{rid}/command", json={"action": action})
    except Exception:
        pass


def refresh_dashboard(run_id: int) -> None:
    """
    대시보드 KPI를 REST로 한 번에 갱신.
    WS 가 끊겼을 때 폴링 용도로도 사용 가능.
    """
    try:
        r = _http("GET", f"/api/runs/{run_id}/status")
        if r.status_code == 200:
            d = r.json()
            if d.get("mission_success_rate") is not None:
                success_rate.set(int(d["mission_success_rate"]))
            if d.get("queue_occurrence_rate") is not None:
                asset_damage.set(int(d["queue_occurrence_rate"]))
            if d.get("status_label"):
                status.set(d["status_label"])
            if d.get("remaining_time_hms"):
                time_left.set(d["remaining_time_hms"])
            if d.get("aoi_remaining_hms"):
                patrol_area.set(d["aoi_remaining_hms"])
    except Exception:
        pass

    try:
        r = _http("GET", f"/api/runs/{run_id}/ugv-count")
        if r.status_code == 200:
            d = r.json()
            ratio_x.set(d.get("total_ugv", ratio_x.value))
    except Exception:
        pass

    try:
        r = _http("GET", f"/api/runs/{run_id}/route-effect")
        if r.status_code == 200:
            d = r.json()
            if d.get("success_rate_delta") is not None:
                effect_success.set(d["success_rate_delta"])
            if d.get("damage_rate_delta") is not None:
                effect_damage.set(d["damage_rate_delta"])
    except Exception:
        pass

    try:
        r = _http("GET", f"/api/runs/{run_id}/queue/danger")
        if r.status_code == 200:
            d = r.json()
            items = [
                {"id": item["asset_code"], "dist": f"{item['elapsed_min']}m"}
                for item in d.get("items", [])
                if not item.get("is_resolved")
            ]
            queue_data.set(items if items else queue_data.value)
    except Exception:
        pass


# ── 통제관 브리핑 API ────────────────────────────────────────────

def post_operator_mission_config() -> bool:
    """
    지휘관이 확정한 임무 설정을 백엔드에 저장.
    CommanderInputPage.handle_submit()에서 호출.
    실패 시 False 반환 (프론트 상태는 이미 업데이트된 상태).
    """
    from components.pages import asset_data  # 지연 임포트 (순환 참조 방지)

    _depart_map = mission_settings.value.get("depart_times", {})
    _arrive_map = mission_settings.value.get("arrive_times", {})
    recon_times = mission_settings.value.get("recon_times", {})
    base = asset_data.value.get("base", {})

    units: dict[str, dict] = {}
    for ukey in ("user1", "user2", "user3"):
        ud = asset_data.value.get(ukey, {})
        kpi = unit_kpi_data.value.get(ukey, {"success": 0, "risk": 0})
        units[ukey] = {
            "controllers":   int(ud.get("controllers", 1)),
            "total_ugv":     int(ud.get("total_ugv", 5)),
            "lost_ugv":      int(ud.get("lost_ugv", 0)),
            "available_ugv": int(ud.get("available_ugv", 5)),
            "target_lat":    str(ud.get("target_lat", "")),
            "target_lon":    str(ud.get("target_lon", "")),
            "depart_time":   _depart_map.get(ukey, "-"),
            "arrive_time":   _arrive_map.get(ukey, "-"),
            "recon_time":    str(recon_times.get(ukey, "-")),
            "success_rate":  int(kpi.get("success", 0)),
            "risk_rate":     int(kpi.get("risk", 0)),
        }

    payload = {
        "mode": mission_settings.value.get("mode", "균형"),
        "base_assets": {
            "total_units":       int(base.get("total_units", 3)),
            "total_controllers": int(base.get("total_controllers", 3)),
            "total_ugv":         int(base.get("total_ugv", 13)),
            "lost_ugv":          int(base.get("lost_ugv", 0)),
        },
        "units": units,
    }
    try:
        resp = _http("POST", "/api/operators/mission-config", json=payload)
        return resp.status_code == 200
    except Exception:
        return False


def fetch_operator_briefing(username: str) -> dict | None:
    """
    통제관이 UserMissionPage에서 자신의 임무 브리핑을 조회.
    성공 시 unit_kpi_data를 갱신하여 지휘관 차트와 동기화.
    실패 시 None 반환 → 프론트 상태 폴백 사용.
    """
    try:
        resp = _http("GET", f"/api/operators/{username}/briefing")
        if resp.status_code == 200:
            data = resp.json()
            # 백엔드 응답에서 KPI를 받아 module-level reactive 갱신
            unit_assets = data.get("unit_assets", {})
            s = unit_assets.get("success_rate")
            r = unit_assets.get("risk_rate")
            if s is not None and r is not None:
                updated = dict(unit_kpi_data.value)
                updated[username] = {"success": int(s), "risk": int(r)}
                unit_kpi_data.set(updated)
            return data
    except Exception:
        pass
    return None

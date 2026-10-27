"""
frontend/state.py

전역 반응형 상태 (solara.reactive)
모든 컴포넌트가 이 상태를 공유하며, 값이 바뀌면 관련 UI가 자동 갱신됩니다.
"""

import solara

# ── 현재 선택된 시나리오 / 임무 ──────────────────
selected_scenario_id = solara.reactive("")
selected_mission_id = solara.reactive(None)   # int | None

# ── 시나리오 / 임무 목록 ──────────────────────────
scenarios = solara.reactive([])   # [{"scenario_id": ..., "name": ...}, ...]
missions = solara.reactive([])    # [{"mission_id": ..., "status": ...}, ...]

# ── 지도 레이어 데이터 ────────────────────────────
grid_cells = solara.reactive([])       # [{"lat", "lon", "land_cover_type", "is_safe_area", "road_type"}, ...]
weather_data = solara.reactive([])     # [{"lat", "lon", "total_cost"}, ...]  (현재 time_step 기준)
optimal_paths = solara.reactive([])    # [{"unit_id", "path_geom": GeoJSON, "eta"}, ...]

# ── 타임슬라이더 ──────────────────────────────────
time_steps = solara.reactive([])       # ["2022-06-01T00:00:00", ...] 문자열 목록
current_time_step = solara.reactive("")

# ── 시뮬레이션 결과 ───────────────────────────────
simulation_results = solara.reactive([])  # 최근 수신된 결과 목록
latest_result = solara.reactive(None)     # 가장 최근 결과 dict

# ── WebSocket 연결 상태 ───────────────────────────
ws_connected = solara.reactive(False)
ws_messages = solara.reactive([])   # 최근 수신 메시지 (최대 50개 유지)

# ── UGV 위치 (실시간 이동) ────────────────────────────
# [{"unit_id": str, "lat": float, "lon": float}, ...]
ugv_positions = solara.reactive([])
ugv_running   = solara.reactive(False)   # 실행 중 여부

# ── 경로 수정 제안 (replan) ───────────────────────────
# 이벤트 발생 시 백엔드가 새 경로를 제안 → 사용자 확인 대기
# 형식: {"unit_id": str, "path_geom": GeoJSON, "trigger": str} | None
pending_route = solara.reactive(None)

# ── UI 상태 ───────────────────────────────────────
loading = solara.reactive(False)
error_message = solara.reactive("")

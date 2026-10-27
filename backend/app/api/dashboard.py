"""
backend/app/api/dashboard.py

실시간 대시보드 조회 API.

GET /api/runs/{run_id}/snapshots/latest
GET /api/runs/{run_id}/panels
GET /api/runs/{run_id}/units
GET /api/runs/{run_id}/queue
GET /api/runs/{run_id}/routes
GET /api/runs/{run_id}/layers
GET /api/runs/{run_id}/alerts
GET /api/runs/{run_id}/kpis
GET /api/runs/{run_id}/recommendation
"""

from fastapi import APIRouter, Depends, Query

from app.api.deps import CurrentUser, DBSession, echelon_of, require_roles
from fastapi import HTTPException

from app.db.schemas.dashboard import (
    AcknowledgeResultOut,
    AlertOut,
    AssetStatusListOut,
    AssetStatusPatchIn,
    CommanderActionResultOut,
    CommanderDashboardOut,
    CommanderEchelonsOut,
    CommanderHomeOut,
    CommanderMapOut,
    CommanderPanelsOut,
    DispatchResultOut,
    HomeSummaryOut,
    KpiOut,
    LtwrViewOut,
    MapLayerOut,
    MapViewOut,
    MissionSuccessRateOut,
    OperatorBriefingOut,
    OperatorDashboardOut,
    PanelOut,
    PatrolAreaOut,
    QueueActiveOut,
    QueueEventOut,
    RecommendationOut,
    RemainingTimeOut,
    RouteEffectOut,
    RouteOut,
    RunStatusOut,
    SnapshotOut,
    SosQueueOut,
    UgvCountOut,
    UnitInfoOut,
    UnitOut,
)

from app.services.dashboard_service import DashboardService

router = APIRouter(prefix="/runs", tags=["dashboard"])

@router.get(
    "/home/summary",
    response_model=HomeSummaryOut,
    summary="메인 홈 상단 요약 정보",
)
async def get_home_summary(db: DBSession, user: CurrentUser):
    svc = DashboardService(db)

    try:
        user_id = int(user.sub)
    except ValueError:
        raise HTTPException(status_code=401, detail="토큰이 유효하지 않습니다.")

    result = await svc.get_home_summary(user_id)
    if result is None:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
    return result

@router.get(
    "/{run_id}/status",
    response_model=RunStatusOut,
    summary="진행상황 — 상단 KPI 바",
    description=(
        "화면 상단 진행상황 영역에 필요한 모든 값을 단일 응답으로 반환.\n\n"
        "| 필드 | 화면 표시 | 설명 |\n"
        "|------|-----------|------|\n"
        "| `status_label` | 진행중 / 대기중 … | run 상태 한국어 |\n"
        "| `mission_success_rate` | 임무성공률 78% | 최신 snapshot |\n"
        "| `asset_damage_rate` | 자산피해율 13% | 최신 snapshot |\n"
        "| `remaining_time_hms` | 남은시간 00:12:34 | HH:MM:SS |\n"
        "| `aoi_remaining_hms` | 정찰구역 00:30:00 | HH:MM:SS |\n"
        "| `aoi_total_hms` | 정찰구역 총 시간 | mission 기준 |\n"
    ),
)
async def get_run_status(run_id: int, db: DBSession, user: CurrentUser):
    svc = DashboardService(db)
    result = await svc.get_run_status(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="run을 찾을 수 없습니다.")
    return result


@router.get(
    "/{run_id}/remaining-time",
    response_model=RemainingTimeOut,
    summary="남은 시간 — 실시간 카운트다운",
    description=(
        "`started_at + mission_duration_min` 기준으로 **매 호출마다** 서버에서 직접 계산.\n\n"
        "snapshot 의존 없이 항상 정확한 값을 반환한다.\n\n"
        "| 필드 | 화면 표시 | 설명 |\n"
        "|------|-----------|------|\n"
        "| `remaining_hms` | **00:12:34** | 남은 시간 (HH:MM:SS) |\n"
        "| `total_hms` | 00:30:00 | 임무 총 시간 (mission 입력값) |\n"
        "| `elapsed_hms` | 00:17:26 | 경과 시간 |\n"
        "| `progress_pct` | 58.1 | 진행률 (%) |\n"
        "| `is_expired` | false | 시간 만료 여부 |\n"
        "| `calculated_at` | — | 서버 계산 기준 시각 |\n\n"
        "**상태별 동작**\n"
        "- `CREATED` → remaining = total (시작 전)\n"
        "- `RUNNING` → 실시간 카운트다운\n"
        "- `COMPLETED/FAILED/CANCELLED` → remaining = 0\n\n"
        "**폴링 권장 주기**: 1초 (또는 WebSocket `run_status` 메시지로 대체 가능)"
    ),
)
async def get_remaining_time(run_id: int, db: DBSession, user: CurrentUser):
    svc = DashboardService(db)
    result = await svc.get_remaining_time(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="run을 찾을 수 없습니다.")
    return result


@router.get(
    "/{run_id}/success-rate",
    response_model=MissionSuccessRateOut,
    summary="임무성공률 — 현재값 + 시계열 + T+1~T+3 예측",
    description=(
        "임무성공률 위젯에 필요한 전체 데이터를 반환.\n\n"
        "| 필드 | 설명 |\n"
        "|------|------|\n"
        "| `current` | 현재 임무성공률 (%) |\n"
        "| `history` | 시계열 이력 (timestamp + value, 최대 100개) |\n"
        "| `projected.T1` | T+1 예측 성공률 (%) |\n"
        "| `projected.T2` | T+2 예측 성공률 (%) |\n"
        "| `projected.T3` | T+3 예측 성공률 (%) |\n"
    ),
)
async def get_success_rate(run_id: int, db: DBSession, user: CurrentUser):
    svc = DashboardService(db)
    result = await svc.get_success_rate(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="run을 찾을 수 없습니다.")
    return result


@router.get(
    "/{run_id}/route-effect",
    response_model=RouteEffectOut,
    summary="현재경로 효과 — 최적경로 vs 차선책 비교 delta",
    description=(
        "현재 선택된 **최적경로**가 **차선책(두 번째 최적경로)**에 비해 "
        "얼마나 효율적인지 KPI delta 값으로 반환.\n\n"
        "| 필드 | 화면 표시 | 설명 |\n"
        "|------|-----------|------|\n"
        "| `success_rate_delta_label` | **+12%** | 임무성공률 차이 (최적 − 차선책) |\n"
        "| `damage_rate_delta_label` | **-7%** | 대기열 발생시간 차이 (최적 − 차선책) |\n"
        "| `optimal_success_rate` | — | 최적경로 임무성공률 (%) |\n"
        "| `alt_success_rate` | — | 차선책 임무성공률 (%) |\n"
        "| `optimal_damage_rate` | — | 최적경로 대기열 발생시간 (%) |\n"
        "| `alt_damage_rate` | — | 차선책 대기열 발생시간 (%) |\n\n"
        "**delta 부호 해석**\n"
        "- `success_rate_delta` 양수 (+) → 최적경로가 임무성공률이 더 높음\n"
        "- `damage_rate_delta` 음수 (−) → 최적경로가 대기열 발생시간이 더 낮음 (유리)\n\n"
        "시뮬레이션 완료 전에는 모든 KPI 필드가 `null` 로 반환될 수 있음."
    ),
)
async def get_route_effect(run_id: int, db: DBSession, user: CurrentUser):
    svc = DashboardService(db)
    result = await svc.get_route_effect(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="run을 찾을 수 없습니다.")
    return result


@router.get(
    "/{run_id}/ugv-count",
    response_model=UgvCountOut,
    summary="운용 UGV 수 — 입력값 및 실시간 상태별 집계",
    description=(
        "화면 우측 상단 **운용 UGV 수** 위젯에 필요한 데이터를 반환.\n\n"
        "| 필드 | 화면 표시 | 설명 |\n"
        "|------|-----------|------|\n"
        "| `total_ugv` | **4** | 미션 생성 시 입력한 운용 UGV 수 (0 ~ 4대) |\n"
        "| `max_ugv_count` | — | 편성 가능 최대 UGV 수 |\n"
        "| `active_count` | — | 현재 MOVING / STANDBY 상태 UGV 수 |\n"
        "| `queued_count` | — | 현재 QUEUED 상태 UGV 수 |\n"
        "| `done_count` | — | 임무 완료(DONE) UGV 수 |\n"
        "| `sos_count` | — | SOS 상태 UGV 수 |\n\n"
        "`total_ugv` 는 **미션 입력값** (0 ~ 4 범위 검증).\n"
        "실시간 상태 집계(`active_count` 등)는 `run_units` 테이블 기준."
    ),
)
async def get_ugv_count(run_id: int, db: DBSession, user: CurrentUser):
    svc = DashboardService(db)
    result = await svc.get_ugv_count(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="run을 찾을 수 없습니다.")
    return result


@router.get(
    "/{run_id}/unit-info",
    response_model=UnitInfoOut,
    summary="부대 정보 — 제대 번호 및 운용 UGV 수",
    description=(
        "화면 좌측 **부대 정보** / **운용 UGV 수** 위젯에 필요한 데이터를 반환.\n\n"
        "| 필드 | 화면 표시 | 설명 |\n"
        "|------|-----------|------|\n"
        "| `echelon_label` | **1제대** | `{echelon_no}제대` 형태의 표시 문자열 |\n"
        "| `echelon_no` | 1 | 제대 번호 (숫자) |\n"
        "| `total_ugv` | **4** | 운용 UGV 수 (mission 입력값) |\n"
        "| `max_ugv_count` | — | 편성 최대 UGV 수 |\n\n"
        "mission 생성 시 `echelon_no` 를 입력하며, 미입력 시 기본값 **1** 사용."
    ),
)
async def get_unit_info(run_id: int, db: DBSession, user: CurrentUser):
    svc = DashboardService(db)
    result = await svc.get_unit_info(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="run을 찾을 수 없습니다.")
    return result


@router.get(
    "/{run_id}/snapshots/latest",
    response_model=SnapshotOut | None,
    summary="최신 상태 스냅샷 (raw)",
)
async def latest_snapshot(run_id: int, db: DBSession, user: CurrentUser):
    svc = DashboardService(db)
    return await svc.latest_snapshot(run_id)


@router.get("/{run_id}/panels", response_model=list[PanelOut], summary="T/T+1/T+2/T+3 패널")
async def get_panels(run_id: int, db: DBSession, user: CurrentUser):
    svc = DashboardService(db)
    return await svc.get_panels(run_id)


@router.get("/{run_id}/units", response_model=list[UnitOut], summary="UGV 유닛 상태")
async def get_units(run_id: int, db: DBSession, user: CurrentUser):
    svc = DashboardService(db)
    return await svc.get_units(run_id)


@router.get(
    "/{run_id}/queue/active",
    response_model=QueueActiveOut,
    summary="대기열 발생시간 — 현재 대기 중인 UGV 목록",
    description=(
        "현재 QUEUED 상태인 UGV와 각각의 대기열 발생 경과 시간을 반환.\n\n"
        "| 필드 | 화면 표시 | 설명 |\n"
        "|------|-----------|------|\n"
        "| `asset_code` | UGV-2 | UGV 식별코드 |\n"
        "| `entered_at` | — | 대기열 진입 시각 (발생시간) |\n"
        "| `elapsed_min` | 12m | 진입 후 경과 시간 (분) |\n"
        "| `wait_time_min` | — | 예상 잔여 대기 시간 (분) |\n"
        "| `priority_score` | — | 우선순위 점수 (0~1) |\n\n"
        "**정렬**: elapsed_sec 내림차순 (오래 기다린 UGV가 맨 위)"
    ),
)
async def get_active_queue(run_id: int, db: DBSession, user: CurrentUser):
    svc = DashboardService(db)
    result = await svc.get_active_queue(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="run을 찾을 수 없습니다.")
    return result


@router.get(
    "/{run_id}/queue/danger",
    response_model=SosQueueOut,
    summary="대기열 — SOS 발생 UGV FIFO 카운트업",
    description=(
        "**SOS 요청 발생 순간**부터 해당 UGV의 누적 대기시간을 카운트업하여 반환.\n\n"
        "| 필드 | 화면 표시 | 설명 |\n"
        "|------|-----------|------|\n"
        "| `asset_code` | **UGV-2** | UGV 식별코드 |\n"
        "| `elapsed_min` | **12m** | SOS 발생 후 경과 시간 (분) |\n"
        "| `elapsed_hms` | 00:12:00 | 경과 시간 HH:MM:SS |\n"
        "| `fifo_position` | 1 | FIFO 처리 순서 (1 = 가장 먼저 SOS 발생) |\n"
        "| `is_resolved` | false | 일대일 처리 완료 여부 |\n"
        "| `danger_count` | 2 | 현재 미처리 SOS 대기 UGV 수 |\n\n"
        "**FIFO 로직**\n"
        "- `sos_at` 오름차순 정렬 → `fifo_position` 1번이 가장 먼저 처리\n"
        "- `resolved_at` NULL = 대기 중 / 값 있음 = 일대일 처리 완료\n"
        "- 완료된 항목도 이력으로 포함 (`is_resolved=true`)\n\n"
        "**폴링 권장 주기**: 1초"
    ),
)
async def get_danger_queue(run_id: int, db: DBSession, user: CurrentUser):
    svc = DashboardService(db)
    result = await svc.get_danger_queue(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="run을 찾을 수 없습니다.")
    return result


@router.get("/{run_id}/queue", response_model=list[QueueEventOut], summary="대기열 이벤트 이력 (raw)")
async def get_queue(run_id: int, db: DBSession, user: CurrentUser):
    svc = DashboardService(db)
    return await svc.get_queue_events(run_id)


@router.get("/{run_id}/routes", response_model=list[RouteOut], summary="경로 데이터")
async def get_routes(run_id: int, db: DBSession, user: CurrentUser):
    svc = DashboardService(db)
    return await svc.get_routes(run_id)


@router.get(
    "/{run_id}/map-view",
    response_model=MapViewOut,
    summary="중앙 그리드 맵 — 레이어 3종 + UGV/출발지/도착지 마커",
    description=(
        "중앙 맵 렌더링에 필요한 **레이어 정보 + 마커 목록**을 단일 응답으로 반환.\n\n"
        "**레이어 탭 3종 (순서 고정)**\n\n"
        "| `layer_type` | `layer_label` | 설명 |\n"
        "|---|---|---|\n"
        "| `RISK` | 위험도 | 위험 지역 열지도 |\n"
        "| `MOBILITY` | 기동성(토양수분) | 토양수분 기반 이동 가능 여부 |\n"
        "| `SENSOR` | 센서(가시성) | 센서 가시 범위 |\n\n"
        "`is_ready=false` → 해당 레이어 파일 아직 수신 전 (\"위험도 맵 데이터 수신 중...\" 표시)\n\n"
        "**마커 타입**\n\n"
        "| `marker_type` | 화면 범례 | 설명 |\n"
        "|---|---|---|\n"
        "| `DEPARTURE` | 출발지 (녹색) | mission.departure_lat/lon |\n"
        "| `TARGET` | 도착지 (빨강) | mission_targets 목적지 |\n"
        "| `UGV` | UGV-1~4 (번호) | run_units 현재 위치 |\n\n"
        "UGV `status`: `STANDBY` / `MOVING` / `QUEUED` / `SOS` / `DONE`\n\n"
        "**폴링 권장 주기**: 2~5초 (레이어 수신 완료 전), 완료 후 UGV 위치는 WebSocket `unit_update` 사용"
    ),
)
async def get_map_view(run_id: int, db: DBSession, user: CurrentUser):
    svc = DashboardService(db)
    result = await svc.get_map_view(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="run을 찾을 수 없습니다.")
    return result


@router.get(
    "/{run_id}/ltwr-view",
    response_model=LtwrViewOut,
    summary="LTWR 현황 — T+0~T+3 기상 예측 지도 슬롯",
    description=(
        "우측 스크롤 박스에 표시할 **T+0 ~ T+3 기상 예측 지도** 슬롯 목록을 반환.\n\n"
        "| `time_slot` | `slot_label` | 설명 |\n"
        "|---|---|---|\n"
        "| `T0` | T+0: Present Status | 현재 기상 상태 |\n"
        "| `T1` | T+1: Prediction | 1단계 예측 |\n"
        "| `T2` | T+2: Prediction | 2단계 예측 |\n"
        "| `T3` | T+3: Prediction | 3단계 예측 |\n\n"
        "**항상 4개 슬롯** (T0~T3)을 고정 순서로 반환.\n\n"
        "| 필드 | 설명 |\n"
        "|---|---|\n"
        "| `file_path` | 기상 예측 지도 파일 경로 (GeoTIFF 등) |\n"
        "| `is_ready` | `true` = 수신 완료 / `false` = 수신 대기 중 |\n"
        "| `ready_count` | 수신 완료된 슬롯 수 (0~4) |\n\n"
        "`is_ready=false` 슬롯은 프론트에서 로딩 스피너 표시.\n"
        "수신 완료는 WebSocket `map_layer_update` (layer_type=LTWR) 이벤트로 실시간 감지."
    ),
)
async def get_ltwr_view(run_id: int, db: DBSession, user: CurrentUser):
    svc = DashboardService(db)
    result = await svc.get_ltwr_view(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="run을 찾을 수 없습니다.")
    return result


@router.get("/{run_id}/layers", response_model=list[MapLayerOut], summary="맵 레이어")
async def get_layers(run_id: int, db: DBSession, user: CurrentUser):
    svc = DashboardService(db)
    return await svc.get_map_layers(run_id)


@router.get("/{run_id}/alerts", response_model=list[AlertOut], summary="알림 목록")
async def get_alerts(run_id: int, db: DBSession, user: CurrentUser):
    svc = DashboardService(db)
    return await svc.get_alerts(run_id)


@router.get("/{run_id}/kpis", response_model=list[KpiOut], summary="KPI 결과")
async def get_kpis(run_id: int, db: DBSession, user: CurrentUser):
    svc = DashboardService(db)
    return await svc.get_kpis(run_id)


@router.get(
    "/{run_id}/recommendation",
    response_model=list[RecommendationOut],
    summary="투입 편성 추천",
)
async def get_recommendation(run_id: int, db: DBSession, user: CurrentUser):
    svc = DashboardService(db)
    return await svc.get_recommendations(run_id)


@router.get(
    "/{run_id}/patrol-area",
    response_model=PatrolAreaOut,
    summary="정찰구역 — 목적지별 카운트다운",
    description=(
        "UGV가 목적지에 도착한 시각(`arrived_at`)부터 `patrol_duration_sec` 기준 카운트다운.\n\n"
        "| 필드 | 화면 표시 | 설명 |\n"
        "|------|-----------|------|\n"
        "| `remaining_hms` | **00:12:34** | 남은 정찰 시간 (HH:MM:SS) |\n"
        "| `patrol_duration_hms` | 00:30:00 | 총 정찰 시간 (mission_targets 설정값) |\n"
        "| `progress_pct` | 58.1 | 경과 비율 (%) |\n"
        "| `is_completed` | false | 정찰 완료 여부 |\n"
        "| `is_expired` | false | 시간 만료됐는데 아직 RUNNING 상태 |\n"
        "| `active_count` | 2 | 현재 정찰 중인 UGV 수 |\n\n"
        "**남은시간 종속**: 정찰구역 카운트다운은 UGV 도착(`arrived_at`) 기준이며 "
        "임무 남은시간(`remaining-time`)과 독립적으로 계산됨.\n\n"
        "**폴링 권장 주기**: 1초"
    ),
)
async def get_patrol_area(run_id: int, db: DBSession, user: CurrentUser):
    svc = DashboardService(db)
    result = await svc.get_patrol_area(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="run을 찾을 수 없습니다.")
    return result

@router.get("/commander/{run_id}/home", response_model=CommanderHomeOut, summary="지휘관 메인 좌측 패널")
async def get_commander_home(run_id: int, db: DBSession, user: CurrentUser):
    svc = DashboardService(db)
    result = await svc.get_commander_home(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="run을 찾을 수 없습니다.")
    return result


@router.get("/commander/{run_id}/echelons", response_model=CommanderEchelonsOut, summary="지휘관 메인 상단 제대 표")
async def get_commander_echelons(run_id: int, db: DBSession, user: CurrentUser):
    svc = DashboardService(db)
    result = await svc.get_commander_echelons(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="run을 찾을 수 없습니다.")
    return result


@router.get("/commander/{run_id}/map", response_model=CommanderMapOut, summary="지휘관 메인 맵")
async def get_commander_map(run_id: int, layer: str = "risk", db: DBSession = None, user: CurrentUser = None):
    svc = DashboardService(db)
    result = await svc.get_commander_map(run_id, layer)
    if result is None:
        raise HTTPException(status_code=404, detail="run을 찾을 수 없습니다.")
    return result


@router.get("/commander/{run_id}/panels", response_model=CommanderPanelsOut, summary="지휘관 메인 보조 패널")
async def get_commander_panels(run_id: int, db: DBSession, user: CurrentUser):
    svc = DashboardService(db)
    result = await svc.get_commander_panels(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="run을 찾을 수 없습니다.")
    return result


@router.post("/commander/{run_id}/actions/execute", response_model=CommanderActionResultOut, summary="작전 실행")
async def commander_execute(run_id: int, db: DBSession, user: CurrentUser):
    svc = DashboardService(db)
    result = await svc.commander_action(run_id, "execute")
    if result is None:
        raise HTTPException(status_code=404, detail="run을 찾을 수 없습니다.")
    return result


@router.post("/commander/{run_id}/actions/terminate", response_model=CommanderActionResultOut, summary="작전 종료")
async def commander_terminate(run_id: int, db: DBSession, user: CurrentUser):
    svc = DashboardService(db)
    result = await svc.commander_action(run_id, "terminate")
    if result is None:
        raise HTTPException(status_code=404, detail="run을 찾을 수 없습니다.")
    return result


@router.post("/commander/{run_id}/actions/dispatch", response_model=CommanderActionResultOut, summary="임무 하달")
async def commander_dispatch(run_id: int, db: DBSession, user: CurrentUser):
    svc = DashboardService(db)
    result = await svc.commander_action(run_id, "dispatch")
    if result is None:
        raise HTTPException(status_code=404, detail="run을 찾을 수 없습니다.")
    return result


@router.post("/commander/{run_id}/actions/replan-route", response_model=CommanderActionResultOut, summary="경로 수정")
async def commander_replan_route(run_id: int, db: DBSession, user: CurrentUser):
    svc = DashboardService(db)
    result = await svc.commander_action(run_id, "replan-route")
    if result is None:
        raise HTTPException(status_code=404, detail="run을 찾을 수 없습니다.")
    return result


# ── 지휘관 대시보드 통합 API ────────────────────────────────

@router.get(
    "/{run_id}/commander/dashboard",
    response_model=CommanderDashboardOut,
    summary="지휘관 메인 화면 통합 데이터 (PDF 5페이지)",
    tags=["dashboard"],
)
async def get_commander_dashboard(run_id: int, db: DBSession, user: CurrentUser):
    svc = DashboardService(db)
    result = await svc.get_commander_dashboard(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="run을 찾을 수 없습니다.")
    return result


@router.post(
    "/{run_id}/commander/mode",
    response_model=CommanderActionResultOut,
    summary="임무 모드 변경 (균형/정찰/신속)",
    dependencies=[Depends(require_roles("commander"))],
    tags=["dashboard"],
)
async def set_commander_mode(run_id: int, mode: str, db: DBSession, user: CurrentUser):
    svc = DashboardService(db)
    result = await svc.set_run_mode(run_id, mode)
    if result is None:
        raise HTTPException(status_code=400, detail="유효하지 않은 모드이거나 run을 찾을 수 없습니다.")
    return result


# ── 자산 현황 API ──────────────────────────────────────────

@router.get(
    "/{run_id}/asset-status",
    response_model=AssetStatusListOut,
    summary="자산 현황 조회 (PDF 6, 10페이지)",
    description=(
        "commander: 전체 제대 조회 가능.\n"
        "operator: 본인 제대(assigned_echelon_no)만 조회 가능.\n"
        "DB에 저장된 값이 없으면 mission 기반 기본값 반환."
    ),
    tags=["dashboard"],
)
async def get_asset_status(run_id: int, db: DBSession, user: CurrentUser):
    svc = DashboardService(db)
    role = user.role or "operator"
    # operator 의 담당 제대: 토큰 unit 클레임 (user1→1제대 …)
    scope = None if role == "commander" else echelon_of(user)
    result = await svc.get_asset_status(run_id, role, scope)
    if result is None:
        raise HTTPException(status_code=404, detail="run을 찾을 수 없습니다.")
    return result


@router.patch(
    "/{run_id}/asset-status",
    response_model=AssetStatusListOut,
    summary="자산 현황 저장 (PDF 6, 10페이지 저장 버튼)",
    description=(
        "commander: 전체 제대 수정 가능.\n"
        "operator: 본인 제대만 수정 가능.\n"
        "취소 버튼은 프론트 동작이므로 백엔드 API 없음."
    ),
    tags=["dashboard"],
)
async def patch_asset_status(
    run_id: int, body: AssetStatusPatchIn, db: DBSession, user: CurrentUser
):
    svc = DashboardService(db)
    role = user.role or "operator"
    try:
        user_id = int(user.sub)
    except Exception:
        user_id = 0
    scope = None if role == "commander" else echelon_of(user)
    result = await svc.patch_asset_status(run_id, user_id, role, scope, body)
    if result is None:
        raise HTTPException(status_code=404, detail="run을 찾을 수 없습니다.")
    return result


# ── 임무 하달 / 통제관 브리핑 API ──────────────────────────

@router.post(
    "/{run_id}/dispatch",
    response_model=DispatchResultOut,
    summary="임무 하달 (지휘관 → 통제관)",
    dependencies=[Depends(require_roles("commander"))],
    tags=["dashboard"],
)
async def dispatch_mission(run_id: int, db: DBSession, user: CurrentUser):
    svc = DashboardService(db)
    result = await svc.dispatch_mission(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="run을 찾을 수 없습니다.")
    return result


@router.get(
    "/{run_id}/operator/briefing",
    response_model=OperatorBriefingOut,
    summary="통제관 임무 브리핑 조회 (PDF 8페이지)",
    tags=["dashboard"],
)
async def get_operator_briefing(run_id: int, db: DBSession, user: CurrentUser):
    svc = DashboardService(db)
    # 통제관의 담당 제대 (토큰 unit 클레임)
    echelon_no = echelon_of(user)
    result = await svc.get_operator_briefing(run_id, echelon_no)
    if result is None:
        raise HTTPException(status_code=404, detail="run을 찾을 수 없습니다.")
    return result


@router.post(
    "/{run_id}/operator/acknowledge",
    response_model=AcknowledgeResultOut,
    summary="통제관 임무 수령 확인 (PDF 8페이지 완료 버튼)",
    tags=["dashboard"],
)
async def acknowledge_operator_briefing(run_id: int, db: DBSession, user: CurrentUser):
    svc = DashboardService(db)
    result = await svc.acknowledge_operator_briefing(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="run을 찾을 수 없습니다.")
    return result


@router.get(
    "/{run_id}/operator/dashboard",
    response_model=OperatorDashboardOut,
    summary="통제관 메인 화면 통합 데이터 (PDF 9페이지)",
    tags=["dashboard"],
)
async def get_operator_dashboard(run_id: int, db: DBSession, user: CurrentUser):
    svc = DashboardService(db)
    echelon_no = echelon_of(user)
    result = await svc.get_operator_dashboard(run_id, echelon_no)
    if result is None:
        raise HTTPException(status_code=404, detail="run을 찾을 수 없습니다.")
    return result


@router.get(
    "/{run_id}/operator/map",
    response_model=CommanderMapOut,
    summary="통제관 맵 — 자기 제대 경로/마커만 반환",
    description=(
        "commander/map 과 동일한 구조이지만, "
        "routes / markers 를 로그인한 통제관의 제대로 필터링하여 반환.\n\n"
        "- `echelon_id` 가 없는 공통 마커(출발지 등)는 항상 포함\n"
        "- 다른 제대의 경로/마커는 제외\n\n"
        "**사용 예**: `GET /api/runs/12/operator/map?layer=risk`"
    ),
    tags=["dashboard"],
)
async def get_operator_map(
    run_id: int,
    db: DBSession,
    user: CurrentUser,
    layer: str = Query("risk", description="레이어 타입: risk | mobility | sensor"),
):
    svc = DashboardService(db)
    echelon_no = echelon_of(user)
    result = await svc.get_operator_map(run_id, echelon_no, layer)
    if result is None:
        raise HTTPException(status_code=404, detail="run을 찾을 수 없습니다.")
    return result
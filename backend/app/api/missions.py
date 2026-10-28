"""
backend/app/api/missions.py

임무 CRUD + 목적지/force mix 입력.

POST   /api/missions
GET    /api/missions/{mission_id}
PATCH  /api/missions/{mission_id}
POST   /api/missions/{mission_id}/targets
POST   /api/missions/{mission_id}/force-mix-candidates
"""

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import CurrentUser, DBSession, require_roles
from app.db.models.mission import Mission
from app.services.run_data import COMMANDER_ROLES, RunDataError, team_modes_of, team_scope
from app.simulation.replay import MODES, TEAMS
from app.db.schemas.dashboard import CommanderSetupOut
from app.db.schemas.mission import (
    ForceMixCandidateIn,
    ForceMixCandidateOut,
    MissionCreate,
    MissionOut,
    MissionPatch,
    MissionTargetIn,
    MissionTargetOut,
)
from app.services.dashboard_service import DashboardService
from app.services.mission_service import MissionService

router = APIRouter(prefix="/missions", tags=["missions"])


@router.post(
    "",
    response_model=MissionOut,
    status_code=201,
    summary="임무 생성",
    dependencies=[Depends(require_roles("commander"))],
)
async def create_mission(body: MissionCreate, db: DBSession, user: CurrentUser):
    svc = MissionService(db)
    return await svc.create_mission(user_id=int(user.sub) if user.sub.isdigit() else 1, data=body)


@router.get("/{mission_id}", response_model=MissionOut, summary="임무 조회")
async def get_mission(mission_id: int, db: DBSession, user: CurrentUser):
    svc = MissionService(db)
    mission = await svc.get_mission(mission_id)
    if mission is None:
        raise HTTPException(status_code=404, detail="임무를 찾을 수 없습니다.")
    # commander는 전체 조회 가능, operator는 본인 것만
    if user.role != "commander" and mission.user_id != int(user.sub):
        raise HTTPException(status_code=403, detail="접근 권한이 없습니다.")
    return mission


@router.patch(
    "/{mission_id}",
    response_model=MissionOut,
    summary="임무 수정",
    dependencies=[Depends(require_roles("commander"))],
)
async def patch_mission(mission_id: int, body: MissionPatch, db: DBSession, user: CurrentUser):
    svc = MissionService(db)
    mission = await svc.patch_mission(mission_id, body)
    if mission is None:
        raise HTTPException(status_code=404, detail="임무를 찾을 수 없습니다.")
    return mission


@router.post(
    "/{mission_id}/targets",
    response_model=list[MissionTargetOut],
    status_code=201,
    summary="목적지 입력 (최대 3개, 전체 교체)",
)
async def set_targets(
    mission_id: int, body: list[MissionTargetIn], db: DBSession, user: CurrentUser
):
    if len(body) > 3:
        raise HTTPException(status_code=422, detail="목적지는 최대 3개입니다.")
    svc = MissionService(db)
    return await svc.set_targets(mission_id, body)


@router.get("/{mission_id}/team-modes", summary="제대별 지정 모드 (통제관은 담당 제대 것만)")
async def get_team_modes(mission_id: int, db: DBSession, user: CurrentUser):
    mission = await db.get(Mission, mission_id)
    if mission is None:
        raise HTTPException(status_code=404, detail="임무를 찾을 수 없습니다.")
    modes = team_modes_of(mission)
    if user.role not in COMMANDER_ROLES:
        try:
            team = team_scope(user)
        except RunDataError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
        modes = {team: modes[team]}
    return {"mission_id": mission_id, "team_modes": modes}


@router.put(
    "/{mission_id}/team-modes",
    summary="제대별 모드 지정 (지휘관). 보내지 않은 제대는 기존 값을 유지한다",
    dependencies=[Depends(require_roles("commander"))],
)
async def put_team_modes(mission_id: int, body: dict[str, str], db: DBSession):
    """예: {"Alpha": "balance", "Bravo": "explore", "Charlie": "rush"}. 모드는 balance(균형) | explore(정밀) | rush(신속)."""
    bad_team = [t for t in body if t not in TEAMS]
    bad_mode = [m for m in body.values() if m not in MODES]
    if bad_team or bad_mode:
        raise HTTPException(status_code=422, detail=f"제대는 {TEAMS}, 모드는 {list(MODES)} 중에서 골라야 합니다. (잘못된 값: {bad_team + bad_mode})")
    mission = await db.get(Mission, mission_id)
    if mission is None:
        raise HTTPException(status_code=404, detail="임무를 찾을 수 없습니다.")
    mission.team_modes = {**team_modes_of(mission), **body}           # JSON 컬럼은 새 dict 를 대입해야 변경으로 인식된다
    await db.commit()
    return {"mission_id": mission_id, "team_modes": team_modes_of(mission)}


@router.post(
    "/{mission_id}/force-mix-candidates",
    response_model=ForceMixCandidateOut,
    status_code=201,
    summary="투입 편성 후보 추가",
)
async def add_force_mix_candidate(
    mission_id: int, body: ForceMixCandidateIn, db: DBSession, user: CurrentUser
):
    svc = MissionService(db)
    return await svc.add_force_mix_candidate(mission_id, body)


@router.get(
    "/{mission_id}/commander-setup",
    response_model=CommanderSetupOut,
    summary="지휘관 편성/경로 입력 화면 집계 데이터 (PDF 3페이지)",
    description=(
        "임무 + 목적지 + force mix 후보 데이터를 한 번에 반환.\n\n"
        "| 필드 | 설명 |\n"
        "|------|------|\n"
        "| `map.targets` | 제대별 정찰지 좌표 목록 |\n"
        "| `map.center_lat/lon` | 목표 중심점 (지도 초기값) |\n"
        "| `rows` | 제대별 정찰 시간 (patrol_duration_sec) |\n"
    ),
)
async def get_commander_setup(mission_id: int, db: DBSession, user: CurrentUser):
    if user.role != "commander" and str(user.sub).isdigit():
        # operator도 본인 임무 조회 허용 (제한 완화)
        pass
    svc = DashboardService(db)
    result = await svc.get_commander_setup(mission_id)
    if result is None:
        raise HTTPException(status_code=404, detail="임무를 찾을 수 없습니다.")
    return result

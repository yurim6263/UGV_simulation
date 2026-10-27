"""
backend/app/api/runs.py

시뮬레이션 실행 관리.

POST /api/missions/{mission_id}/runs   — run 생성
GET  /api/runs/{run_id}                — run 조회
POST /api/runs/{run_id}/start          — run 시작
POST /api/runs/{run_id}/cancel         — run 취소
"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.api.deps import CurrentUser, DBSession, require_roles
from app.db.schemas.simulation import RunOut
from app.services.simulation_service import SimulationService

router = APIRouter(tags=["runs"])


@router.post(
    "/missions/{mission_id}/runs",
    response_model=RunOut,
    status_code=201,
    summary="시뮬레이션 run 생성",
)
async def create_run(mission_id: int, db: DBSession, user: CurrentUser):
    svc = SimulationService(db)
    run = await svc.create_run(mission_id)
    if run is None:
        raise HTTPException(status_code=404, detail="임무를 찾을 수 없습니다.")
    return run


@router.get("/runs/{run_id}", response_model=RunOut, summary="run 조회")
async def get_run(run_id: int, db: DBSession, user: CurrentUser):
    svc = SimulationService(db)
    run = await svc.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run을 찾을 수 없습니다.")
    return run


@router.post(
    "/runs/{run_id}/start",
    response_model=RunOut,
    summary="run 시작",
    dependencies=[Depends(require_roles("commander"))],
)
async def start_run(
    run_id: int, db: DBSession, user: CurrentUser, background_tasks: BackgroundTasks
):
    svc = SimulationService(db)
    existing = await svc.get_run(run_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="run을 찾을 수 없습니다.")
    if existing.status != "CREATED":       # 이미 시작/종료된 run 을 다시 시작하면 기록이 중복된다
        raise HTTPException(status_code=409, detail=f"이미 {existing.status} 상태인 run 입니다.")
    return await svc.start_run(run_id, background_tasks)


@router.post(
    "/runs/{run_id}/cancel",
    response_model=RunOut,
    summary="run 취소",
    dependencies=[Depends(require_roles("commander"))],
)
async def cancel_run(run_id: int, db: DBSession, user: CurrentUser):
    svc = SimulationService(db)
    run = await svc.cancel_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run을 찾을 수 없습니다.")
    return run

"""
backend/app/api/runs.py

시뮬레이션 실행 관리.

POST /api/missions/{mission_id}/runs   — run 생성
GET  /api/runs/{run_id}                — run 조회
POST /api/runs/{run_id}/start          — run 시작
POST /api/runs/{run_id}/cancel         — run 취소
"""

from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession, require_roles
from app.db.models.simulation_run import SimulationRun
from app.db.schemas.simulation import RunOut, RunSetItem, RunSetOut
from app.services.simulation_service import SimulationService

router = APIRouter(tags=["runs"])


@router.post(
    "/missions/{mission_id}/runs",
    response_model=RunOut,
    status_code=201,
    summary="시뮬레이션 run 생성",
)
async def create_run(
    mission_id: int, db: DBSession, user: CurrentUser,
    mode: Literal["balanced", "recon", "rapid"] | None = None,
):
    """mode: 균형(balanced) / 정밀(recon) / 신속(rapid). 생략하면 균형."""
    svc = SimulationService(db)
    run = await svc.create_run(mission_id, mode)
    if run is None:
        raise HTTPException(status_code=404, detail="임무를 찾을 수 없습니다.")
    return run


@router.get("/runs/latest-set", response_model=RunSetOut, summary="가장 최근 임무의 실행 목록 (모드별)")
async def latest_run_set(db: DBSession, user: CurrentUser):
    """지휘관이 마지막으로 실행한 임무의 run 들을 돌려준다. 통제관은 이것으로 같은 결과를 이어서 본다.
    실행이 하나도 없으면 404."""
    latest = (await db.execute(
        select(SimulationRun.mission_id).order_by(SimulationRun.id.desc()).limit(1)
    )).scalar_one_or_none()
    if latest is None:
        raise HTTPException(status_code=404, detail="아직 실행된 시뮬레이션이 없습니다.")
    runs = (await db.execute(
        select(SimulationRun).where(SimulationRun.mission_id == latest).order_by(SimulationRun.id)
    )).scalars().all()
    return RunSetOut(
        mission_id=latest,
        runs=[RunSetItem(id=r.id, mode=r.selected_mode or "balanced", status=r.status, progress_pct=r.progress_pct) for r in runs],
        all_completed=all(r.status == "COMPLETED" for r in runs),
    )


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

"""
backend/app/api/plan.py

POST /api/missions/{id}/plan   편성 계산 시작 (지휘관). 같은 입력의 계산이 있으면 그것을 돌려준다 (cached 면 즉시 완료).
GET  /api/missions/{id}/plan   진행률과 결과 (지휘관). 후보 편성 전체는 제대를 가로지르는 비교라 지휘관 전용이다.

계산은 백그라운드에서 돌고(보통 40~60초), 진행률은 done/total(에피소드 수)로 본다.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.api.deps import CurrentUser, DBSession, require_roles
from app.services import plan_service

router = APIRouter(tags=["plan"], dependencies=[Depends(require_roles("commander"))])


@router.post("/missions/{mission_id}/plan", summary="제대별 UGV 투입 대수(1~3) 편성 계산 시작")
async def start_plan(mission_id: int, db: DBSession, user: CurrentUser, background_tasks: BackgroundTasks):
    row = await plan_service.start_plan(db, mission_id, background_tasks)
    if row is None:
        raise HTTPException(status_code=404, detail="임무를 찾을 수 없습니다.")
    return plan_service.state_of(row)


@router.get("/missions/{mission_id}/plan", summary="편성 계산 진행률과 결과")
async def get_plan(mission_id: int, db: DBSession, user: CurrentUser):
    if await plan_service.load_mission_dict(db, mission_id) is None:
        raise HTTPException(status_code=404, detail="임무를 찾을 수 없습니다.")
    row = await plan_service.latest_plan(db, mission_id)
    if row is None:
        raise HTTPException(status_code=404, detail="이 임무의 편성 계산이 없습니다. POST 로 시작하세요.")
    return plan_service.state_of(row)

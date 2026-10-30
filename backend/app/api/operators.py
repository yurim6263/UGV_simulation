"""
backend/app/api/operators.py

통제관 임무 브리핑 API.

엔드포인트 (prefix: /api):
  POST /api/operators/mission-config       — 지휘관이 임무 설정 저장 (JWT 필요)
  GET  /api/operators/{username}/briefing  — 통제관이 자신의 임무 브리핑 조회 (JWT 필요)
"""

from __future__ import annotations

from typing import Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import CurrentUser as _CurrentUserDep

router = APIRouter(tags=["operators"])

CurrentUser = _CurrentUserDep

# ── 인메모리 임무 설정 저장소 ────────────────────────────────────
# 실 운용 시 DB로 교체 가능. commander가 POST하면 여기에 저장되고,
# 각 operator가 GET으로 읽어간다.
_mission_config: dict = {}


# ── 스키마 ───────────────────────────────────────────────────────

class BaseAssetIn(BaseModel):
    total_units: int = 3
    total_controllers: int = 3
    total_ugv: int = 13
    lost_ugv: int = 1


class UnitAssetIn(BaseModel):
    controllers: int = 1
    total_ugv: int = 5
    lost_ugv: int = 0
    available_ugv: int = 5
    target_lat: str = ""
    target_lon: str = ""
    depart_time: str = "-"
    arrive_time: str = "-"
    recon_time: str = "-"
    success_rate: int = 0   # 임무 성공률 (%)
    risk_rate: int = 0      # 임무 위험률 (%)


class MissionConfigIn(BaseModel):
    mode: str = "균형"
    base_assets: BaseAssetIn = BaseAssetIn()
    units: Dict[str, UnitAssetIn] = {}


class UnitAssetOut(BaseModel):
    controllers: int
    total_ugv: int
    lost_ugv: int
    available_ugv: int
    target_lat: str
    target_lon: str
    depart_time: str
    arrive_time: str
    recon_time: str
    success_rate: int = 0
    risk_rate: int = 0


class MissionInfoOut(BaseModel):
    mode: str
    available_ugv: int
    depart_time: str
    arrive_time: str
    recon_time: str


class OperatorBriefingOut(BaseModel):
    username: str
    unit_label: str
    base_assets: BaseAssetIn
    unit_assets: UnitAssetOut
    mission: MissionInfoOut


# ── 엔드포인트 ────────────────────────────────────────────────────

@router.post(
    "/operators/mission-config",
    summary="지휘관: 임무 설정 저장",
)
async def set_mission_config(body: MissionConfigIn, current_user: CurrentUser):
    """
    지휘관이 CommanderInputPage에서 확정한 임무 설정을 백엔드에 저장.
    통제관들이 브리핑 페이지에서 이 데이터를 조회한다.
    """
    if current_user.role not in ("commander", "admin"):
        raise HTTPException(status_code=403, detail="지휘관 전용 엔드포인트입니다.")

    global _mission_config
    _mission_config = body.model_dump()
    return {"ok": True, "message": "임무 설정이 저장되었습니다."}


@router.get(
    "/operators/{username}/briefing",
    response_model=OperatorBriefingOut,
    summary="통제관: 임무 브리핑 조회",
)
async def get_operator_briefing(username: str, current_user: CurrentUser):
    """
    통제관 로그인 후 임무 브리핑 페이지에서 호출.
    지휘관이 저장한 임무 설정을 username 기준으로 필터링하여 반환.
    """
    if not _mission_config:
        raise HTTPException(
            status_code=404,
            detail="아직 저장된 임무 설정이 없습니다. 지휘관이 먼저 임무를 확정해야 합니다.",
        )

    _unit_label_map = {
        "user1": "1제대",
        "user2": "2제대",
        "user3": "3제대",
    }
    unit_label = _unit_label_map.get(username, username)

    # 통제관은 자기 제대의 브리핑만 볼 수 있다 (지휘관은 전체)
    if current_user.role not in ("commander", "admin") and current_user.unit != unit_label:
        raise HTTPException(status_code=403, detail="다른 제대의 브리핑은 조회할 수 없습니다.")

    units: dict = _mission_config.get("units", {})
    unit_raw = units.get(username)
    if unit_raw is None:
        raise HTTPException(
            status_code=404,
            detail=f"'{username}' 에 해당하는 제대 설정이 없습니다.",
        )

    base_raw = _mission_config.get("base_assets", {})

    return OperatorBriefingOut(
        username=username,
        unit_label=unit_label,
        base_assets=BaseAssetIn(**base_raw),
        unit_assets=UnitAssetOut(**unit_raw),
        mission=MissionInfoOut(
            mode=_mission_config.get("mode", "균형"),
            available_ugv=unit_raw.get("available_ugv", 0),
            depart_time=unit_raw.get("depart_time", "-"),
            arrive_time=unit_raw.get("arrive_time", "-"),
            recon_time=unit_raw.get("recon_time", "-"),
        ),
    )

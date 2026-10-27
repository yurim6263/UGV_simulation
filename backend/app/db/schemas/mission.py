"""
backend/app/db/schemas/mission.py

missions / mission_targets / mission_force_mix_candidates Pydantic 스키마.
"""

from datetime import datetime

from pydantic import BaseModel, Field


# ── MissionTarget ─────────────────────────────────────────

class MissionTargetIn(BaseModel):
    seq: int = Field(..., ge=1, le=3)
    lat: float
    lon: float
    patrol_duration_sec: int = Field(1800, ge=0, description="정찰 유지 시간 (초). 기본값 30분.")


class MissionTargetOut(MissionTargetIn):
    id: int
    mission_id: int

    model_config = {"from_attributes": True}


# ── ForceMixCandidate ─────────────────────────────────────

class ForceMixCandidateIn(BaseModel):
    candidate_name: str
    ugv_count: int = Field(..., ge=1)
    config: dict | None = None


class ForceMixCandidateOut(ForceMixCandidateIn):
    id: int
    mission_id: int

    model_config = {"from_attributes": True}


# ── Mission ────────────────────────────────────────────────

class MissionCreate(BaseModel):
    name: str
    echelon_no: int = Field(1, ge=1, description="몇 제대인지 (1, 2, 3 …)")
    total_ugv: int = Field(..., ge=0, le=20, description="임무 전체 운용 UGV 수. 목표(제대) 수에 따라 최대 3개 제대로 나눠 편성한다")
    max_ugv_count: int | None = Field(None, ge=1, description="미입력 시 total_ugv 값 사용")
    mission_duration_min: int = Field(120, ge=1)
    departure_lat: float = Field(37.50)
    departure_lon: float = Field(127.00)


class MissionPatch(BaseModel):
    name: str | None = None
    echelon_no: int | None = Field(None, ge=1)
    total_ugv: int | None = Field(None, ge=0, le=20)
    max_ugv_count: int | None = None
    mission_duration_min: int | None = None
    departure_lat: float | None = None
    departure_lon: float | None = None


class MissionOut(BaseModel):
    id: int
    user_id: int
    name: str
    echelon_no: int
    total_ugv: int
    max_ugv_count: int
    mission_duration_min: int
    departure_lat: float
    departure_lon: float
    status: str
    created_at: datetime
    updated_at: datetime
    targets: list[MissionTargetOut] = []
    force_mix_candidates: list[ForceMixCandidateOut] = []

    model_config = {"from_attributes": True}

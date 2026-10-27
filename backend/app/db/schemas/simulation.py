"""
backend/app/db/schemas/simulation.py

simulation_runs 관련 Pydantic 스키마.
"""

from datetime import datetime

from pydantic import BaseModel


class RunCreate(BaseModel):
    pass  # 생성은 mission_id로만 트리거 (POST /missions/{id}/runs)


class RunSetItem(BaseModel):
    id: int
    mode: str          # balanced | recon | rapid
    status: str
    progress_pct: int


class RunSetOut(BaseModel):
    """가장 최근 임무의 실행들 (모드별 1개씩)."""
    mission_id: int
    runs: list[RunSetItem]
    all_completed: bool


class RunOut(BaseModel):
    id: int
    mission_id: int
    status: str
    phase: str | None
    progress_pct: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    model_config = {"from_attributes": True}


class RunSummary(BaseModel):
    id: int
    status: str
    progress_pct: int
    created_at: datetime

    model_config = {"from_attributes": True}

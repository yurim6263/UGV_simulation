"""
backend/app/db/models/snapshot.py

run_status_snapshots / run_time_series_panels 테이블 ORM 모델.

run_status_snapshots:
    - 실시간 대시보드 상단 패널용 스냅샷 (진행률, KPI 요약)

run_time_series_panels:
    - 우측 사이드바 T/T+1/T+2/T+3 패널 데이터
"""

from datetime import datetime

from sqlalchemy import DateTime, Double, ForeignKey, Integer, String, func
from app.db.types import JSONType
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class RunStatusSnapshot(Base):
    __tablename__ = "run_status_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    phase: Mapped[str | None] = mapped_column(String(30), nullable=True)
    progress_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mission_success_rate: Mapped[float | None] = mapped_column(Double, nullable=True)
    asset_damage_rate: Mapped[float | None] = mapped_column(Double, nullable=True)
    remaining_time_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    aoi_remaining_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 정찰구역 잔여 시간 (초). mission.mission_duration_min 기반으로 카운트다운
    queue_length: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    run: Mapped["SimulationRun"] = relationship(  # noqa: F821
        "SimulationRun", back_populates="snapshots"
    )


class RunTimeSeriesPanel(Base):
    __tablename__ = "run_time_series_panels"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    panel_type: Mapped[str] = mapped_column(String(5), nullable=False)  # T0|T1|T2|T3
    data: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    run: Mapped["SimulationRun"] = relationship(  # noqa: F821
        "SimulationRun", back_populates="panels"
    )

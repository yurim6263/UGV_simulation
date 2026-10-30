"""
backend/app/db/models/route.py

run_routes / run_map_layers / run_kpis / run_recommendations /
run_route_effects 테이블 ORM 모델.

run_routes:
    - 유닛별 경로 (GeoJSON LineString)

run_map_layers:
    - 위험도/기동성/센서/LTWR 맵 레이어 파일 참조

run_kpis:
    - 시뮬레이션 KPI 결과 (성공률, 피해율, 완료시간 등)

run_recommendations:
    - force mix 후보별 점수 + 선택 결과

run_route_effects:
    - 현재경로 효과: 최적경로 vs 차선책 KPI 비교 delta
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Double, ForeignKey, Integer, String, func
from app.db.types import JSONType
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class RunRoute(Base):
    __tablename__ = "run_routes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    unit_no: Mapped[int] = mapped_column(Integer, nullable=False)
    route_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # INITIAL | UPDATED
    reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    geojson: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    run: Mapped["SimulationRun"] = relationship(  # noqa: F821
        "SimulationRun", back_populates="routes"
    )


class RunMapLayer(Base):
    __tablename__ = "run_map_layers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    layer_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # RISK | MOBILITY | SENSOR | LTWR
    time_slot: Mapped[str | None] = mapped_column(String(5), nullable=True)
    # T0 | T1 | T2 | T3
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    run: Mapped["SimulationRun"] = relationship(  # noqa: F821
        "SimulationRun", back_populates="map_layers"
    )


class RunKpi(Base):
    __tablename__ = "run_kpis"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    success_rate: Mapped[float | None] = mapped_column(Double, nullable=True)
    damage_rate: Mapped[float | None] = mapped_column(Double, nullable=True)
    makespan_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    queue_kpi: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    bottleneck_index: Mapped[float | None] = mapped_column(Double, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    run: Mapped["SimulationRun"] = relationship(  # noqa: F821
        "SimulationRun", back_populates="kpis"
    )


class RunRecommendation(Base):
    __tablename__ = "run_recommendations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("mission_force_mix_candidates.id"), nullable=True
    )
    score: Mapped[float | None] = mapped_column(Double, nullable=True)
    is_selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rationale: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    run: Mapped["SimulationRun"] = relationship(  # noqa: F821
        "SimulationRun", back_populates="recommendations"
    )


class RunRouteEffect(Base):
    __tablename__ = "run_route_effects"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # ── 최적경로 (현재 선택된 경로) ─────────────────────────
    optimal_success_rate: Mapped[float | None] = mapped_column(Double, nullable=True)
    # 임무성공률 (0 ~ 100 %)
    optimal_damage_rate: Mapped[float | None] = mapped_column(Double, nullable=True)
    # 대기열 발생시간 (-100 ~ 100 %)

    # ── 차선책 (두 번째 최적경로 알고리즘 결과) ──────────────
    alt_success_rate: Mapped[float | None] = mapped_column(Double, nullable=True)
    alt_damage_rate: Mapped[float | None] = mapped_column(Double, nullable=True)

    # ── Delta (최적 - 차선책) ────────────────────────────────
    # 화면 표시: 임무성공률 +12% / 자산피해율 -7%
    # 양수 = 최적경로가 더 좋음, 음수 = 최적경로가 더 나쁨 (이론상 없음)
    success_rate_delta: Mapped[float | None] = mapped_column(Double, nullable=True)
    damage_rate_delta: Mapped[float | None] = mapped_column(Double, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    run: Mapped["SimulationRun"] = relationship(  # noqa: F821
        "SimulationRun", back_populates="route_effects"
    )

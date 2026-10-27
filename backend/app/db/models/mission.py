"""
backend/app/db/models/mission.py

missions / mission_targets / mission_force_mix_candidates 테이블 ORM 모델.

missions:
    - 사용자가 입력하는 작전 기본 정보 (출발지/목적지/UGV 수 등)

mission_targets:
    - 임무 목적지 목록 (최대 3개, seq 순서)

mission_force_mix_candidates:
    - 투입 병력 편성 후보군 (force mix 비교 대상)
"""

from datetime import datetime

from sqlalchemy import DateTime, Double, ForeignKey, Integer, String, func
from app.db.types import JSONType
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Mission(Base):
    __tablename__ = "missions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    echelon_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # 몇 제대인지 (1, 2, 3 …). 화면의 "1제대" 숫자 부분.
    total_ugv: Mapped[int] = mapped_column(Integer, nullable=False)
    # 운용 UGV 수: 0 ~ 4(대) 범위. 미션 생성 시 사용자가 입력.
    max_ugv_count: Mapped[int] = mapped_column(Integer, nullable=False)
    mission_duration_min: Mapped[int] = mapped_column(Integer, nullable=False)
    departure_lat: Mapped[float] = mapped_column(Double, nullable=False)
    departure_lon: Mapped[float] = mapped_column(Double, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    # DRAFT | READY | RUNNING | COMPLETED
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # 관계
    user: Mapped["User"] = relationship("User", back_populates="missions")  # noqa: F821
    targets: Mapped[list["MissionTarget"]] = relationship(
        "MissionTarget", back_populates="mission", cascade="all, delete-orphan"
    )
    force_mix_candidates: Mapped[list["MissionForceMixCandidate"]] = relationship(
        "MissionForceMixCandidate", back_populates="mission", cascade="all, delete-orphan"
    )
    runs: Mapped[list["SimulationRun"]] = relationship(  # noqa: F821
        "SimulationRun", back_populates="mission"
    )


class MissionTarget(Base):
    __tablename__ = "mission_targets"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    mission_id: Mapped[int] = mapped_column(
        ForeignKey("missions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)  # 1, 2, 3
    lat: Mapped[float] = mapped_column(Double, nullable=False)
    lon: Mapped[float] = mapped_column(Double, nullable=False)
    patrol_duration_sec: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1800
    )
    # 해당 목적지 도착 후 정찰 유지 시간 (초). 기본값 30분.
    # 도착 시점부터 카운트다운 시작 → 00:00:00 도달 시 정찰 완료.

    mission: Mapped["Mission"] = relationship("Mission", back_populates="targets")


class MissionForceMixCandidate(Base):
    __tablename__ = "mission_force_mix_candidates"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    mission_id: Mapped[int] = mapped_column(
        ForeignKey("missions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    candidate_name: Mapped[str] = mapped_column(String(100), nullable=False)
    ugv_count: Mapped[int] = mapped_column(Integer, nullable=False)
    config: Mapped[dict] = mapped_column(JSONType, nullable=True)

    mission: Mapped["Mission"] = relationship(
        "Mission", back_populates="force_mix_candidates"
    )

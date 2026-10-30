"""
backend/app/db/models/formation_plan.py

formation_plans 테이블: 임무별 편성 계산 결과 (제대당 UGV 1~3대 후보 평가와 모드별 추천).

  status      PENDING | RUNNING | COMPLETED | FAILED
  done/total  진행률 (에피소드 수)
  cache_key   입력(출발지, 목표, 정찰 시간, 날씨 강도, 시드, 모드 전술 등)의 해시. 같으면 계산 결과를 다시 쓴다.
  plan        계산 결과 전체 (formation.plan_formations 의 dict) — 완료되었을 때만
  cached      다른 임무/미리 계산한 결과를 재사용했는가
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import JSONType


class FormationPlan(Base):
    __tablename__ = "formation_plans"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    mission_id: Mapped[int] = mapped_column(ForeignKey("missions.id", ondelete="CASCADE"), nullable=False, index=True)
    cache_key: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cached: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    plan: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

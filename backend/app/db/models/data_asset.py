"""
backend/app/db/models/data_asset.py

data_assets / mission_assets / run_input_assets 테이블 ORM 모델.

data_assets:
    - 전처리된 정적/동적 파일 참조 (parquet/tif/geojson 경로 + 메타)

mission_assets:
    - 임무에 연결된 데이터 에셋

run_input_assets:
    - 특정 run에서 사용된 에셋 + 역할 (STATIC_GRID, SAFE_AREA, RISK_T0 …)
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from app.db.types import JSONType
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class DataAsset(Base):
    __tablename__ = "data_assets"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    asset_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # STATIC_GRID | SAFE_AREA | RISK_MAP | MOBILITY_MAP | SENSOR_MAP | WEATHER
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    meta: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class MissionAsset(Base):
    __tablename__ = "mission_assets"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    mission_id: Mapped[int] = mapped_column(
        ForeignKey("missions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("data_assets.id"), nullable=False
    )

    asset: Mapped["DataAsset"] = relationship("DataAsset")


class RunInputAsset(Base):
    __tablename__ = "run_input_assets"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    asset_id: Mapped[int] = mapped_column(ForeignKey("data_assets.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    # STATIC_GRID | SAFE_AREA | RISK_T0 | RISK_T1 | RISK_T2 | RISK_T3

    asset: Mapped["DataAsset"] = relationship("DataAsset")

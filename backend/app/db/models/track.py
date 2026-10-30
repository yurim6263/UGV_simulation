"""
backend/app/db/models/track.py

run_tracks 테이블: 시뮬레이션 이동/이벤트 기록 (한 행 = 한 에이전트의 한 번의 행동).

재생 화면(지도 + 이벤트 타임라인), KPI 집계, SQL 분석의 기반 데이터다.
ERD 설계의 UGV_State_Log + Event_Log 에 해당한다.
"""

from sqlalchemy import Double, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RunTrack(Base):
    __tablename__ = "run_tracks"
    __table_args__ = (Index("ix_run_tracks_run_seq", "run_id", "seq_idx"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    turn_idx: Mapped[int] = mapped_column(Integer, nullable=False)       # 10분 단위 턴
    seq_idx: Mapped[int] = mapped_column(Integer, nullable=False)        # 전 에이전트에 걸친 단조 증가 순번
    agent_id: Mapped[str] = mapped_column(String(50), nullable=False)    # UGV_Alpha_1 / Manned_Alpha / OP_Alpha
    row: Mapped[int] = mapped_column(Integer, nullable=False)
    col: Mapped[int] = mapped_column(Integer, nullable=False)
    lat: Mapped[float] = mapped_column(Double, nullable=False)
    lon: Mapped[float] = mapped_column(Double, nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False)      # MISSION, SOS_SENSOR, INTERVENE->UGV_x, ...
    ap: Mapped[int] = mapped_column(Integer, nullable=False)             # 행동 후 잔여 AP
    total: Mapped[float | None] = mapped_column(Double, nullable=True)   # normalized_c_total
    mob: Mapped[float | None] = mapped_column(Double, nullable=True)     # c_mob_prime
    sen: Mapped[float | None] = mapped_column(Double, nullable=True)     # c_sen_prime
    grade: Mapped[str | None] = mapped_column(String(1), nullable=True)  # G | A | R

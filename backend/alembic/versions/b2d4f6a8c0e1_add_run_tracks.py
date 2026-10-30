"""add run_tracks

Revision ID: b2d4f6a8c0e1
Revises: a1c3f5e7b9d2
Create Date: 2026-09-08 00:00:00.000000

시뮬레이션 이동/이벤트 기록 테이블. create_all 로 이미 만들어진 DB 에서도 실패하지 않도록 존재 여부를 확인한다.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b2d4f6a8c0e1"
down_revision: Union[str, None] = "a1c3f5e7b9d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("run_tracks"):
        return
    op.create_table(
        "run_tracks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("turn_idx", sa.Integer(), nullable=False),
        sa.Column("seq_idx", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.String(length=50), nullable=False),
        sa.Column("row", sa.Integer(), nullable=False),
        sa.Column("col", sa.Integer(), nullable=False),
        sa.Column("lat", sa.Double(), nullable=False),
        sa.Column("lon", sa.Double(), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("ap", sa.Integer(), nullable=False),
        sa.Column("total", sa.Double(), nullable=True),
        sa.Column("mob", sa.Double(), nullable=True),
        sa.Column("sen", sa.Double(), nullable=True),
        sa.Column("grade", sa.String(length=1), nullable=True),
    )
    op.create_index("ix_run_tracks_run_id", "run_tracks", ["run_id"])
    op.create_index("ix_run_tracks_run_seq", "run_tracks", ["run_id", "seq_idx"])


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("run_tracks"):
        op.drop_index("ix_run_tracks_run_seq", table_name="run_tracks")
        op.drop_index("ix_run_tracks_run_id", table_name="run_tracks")
        op.drop_table("run_tracks")

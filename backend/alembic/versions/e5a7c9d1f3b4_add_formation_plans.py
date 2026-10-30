"""add formation_plans

Revision ID: e5a7c9d1f3b4
Revises: d4f6b8c0e2a3
Create Date: 2026-10-28 00:00:00.000000

임무별 편성 계산 결과. create_all 로 이미 만들어진 DB 에서도 실패하지 않도록 존재 여부를 확인한다.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db.types import JSONType


revision: str = "e5a7c9d1f3b4"
down_revision: Union[str, None] = "d4f6b8c0e2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("formation_plans"):
        return
    op.create_table(
        "formation_plans",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("mission_id", sa.Integer(), sa.ForeignKey("missions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cache_key", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("done", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cached", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("plan", JSONType, nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_formation_plans_mission_id", "formation_plans", ["mission_id"])
    op.create_index("ix_formation_plans_cache_key", "formation_plans", ["cache_key"])


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("formation_plans"):
        op.drop_index("ix_formation_plans_cache_key", table_name="formation_plans")
        op.drop_index("ix_formation_plans_mission_id", table_name="formation_plans")
        op.drop_table("formation_plans")

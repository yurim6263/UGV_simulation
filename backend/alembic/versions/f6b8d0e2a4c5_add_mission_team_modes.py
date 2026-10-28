"""add missions.team_modes

Revision ID: f6b8d0e2a4c5
Revises: e5a7c9d1f3b4
Create Date: 2026-10-28 00:00:00.000000

제대별 지정 모드. create_all 로 만들어진 DB 에 컬럼만 더한다 (이미 있으면 건너뛴다).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db.types import JSONType


revision: str = "f6b8d0e2a4c5"
down_revision: Union[str, None] = "e5a7c9d1f3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column() -> bool:
    return any(c["name"] == "team_modes" for c in sa.inspect(op.get_bind()).get_columns("missions"))


def upgrade() -> None:
    if not _has_column():
        op.add_column("missions", sa.Column("team_modes", JSONType, nullable=True))


def downgrade() -> None:
    if _has_column():
        with op.batch_alter_table("missions") as batch:
            batch.drop_column("team_modes")

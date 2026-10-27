"""add users.assigned_unit

Revision ID: a1c3f5e7b9d2
Revises: e8e09d2faebd
Create Date: 2026-09-07 00:00:00.000000

통제관 담당 제대(assigned_unit) 컬럼 추가.
create_all 로 이미 컬럼이 만들어진 DB 에서도 실패하지 않도록 존재 여부를 확인한다.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1c3f5e7b9d2"
down_revision: Union[str, None] = "e8e09d2faebd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    if not _has_column("users", "assigned_unit"):
        op.add_column("users", sa.Column("assigned_unit", sa.String(length=20), nullable=True))


def downgrade() -> None:
    if _has_column("users", "assigned_unit"):
        op.drop_column("users", "assigned_unit")

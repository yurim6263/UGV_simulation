"""assistant_logs.kind

Revision ID: d4f6b8c0e2a3
Revises: c3e5a7b9d1f2
Create Date: 2026-10-28 00:00:00.000000

AI 호출 종류(질문 / 임무 초안 / 상황 보고) 구분 컬럼. 이미 있으면 건너뛴다.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4f6b8c0e2a3"
down_revision: Union[str, None] = "c3e5a7b9d1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column() -> bool:
    return any(c["name"] == "kind" for c in sa.inspect(op.get_bind()).get_columns("assistant_logs"))


def upgrade() -> None:
    if not _has_column():
        op.add_column("assistant_logs", sa.Column("kind", sa.String(length=20), nullable=False, server_default="ask"))


def downgrade() -> None:
    if _has_column():
        op.drop_column("assistant_logs", "kind")

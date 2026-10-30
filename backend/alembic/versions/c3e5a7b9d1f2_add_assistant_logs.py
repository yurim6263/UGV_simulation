"""add assistant_logs

Revision ID: c3e5a7b9d1f2
Revises: b2d4f6a8c0e1
Create Date: 2026-10-27 00:00:00.000000

AI 어시스턴트 호출 기록. create_all 로 이미 만들어진 DB 에서도 실패하지 않도록 존재 여부를 확인한다.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db.types import JSONType


revision: str = "c3e5a7b9d1f2"
down_revision: Union[str, None] = "b2d4f6a8c0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("assistant_logs"):
        return
    op.create_table(
        "assistant_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(length=50), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("question", sa.String(length=300), nullable=False),
        sa.Column("model", sa.String(length=80), nullable=False),
        sa.Column("tools", JSONType, nullable=False),
        sa.Column("denied_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tool_errors", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("grounded", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("warnings", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("steps", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_assistant_logs_user_id", "assistant_logs", ["user_id"])


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("assistant_logs"):
        op.drop_index("ix_assistant_logs_user_id", table_name="assistant_logs")
        op.drop_table("assistant_logs")

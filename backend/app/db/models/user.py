"""
backend/app/db/models/user.py

users 테이블 ORM 모델.
역할: 지휘관(commander) / 통제관(operator)
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, default="operator"
    )  # commander | operator
    assigned_unit: Mapped[str | None] = mapped_column(
        String(20), nullable=True, default=None
    )  # 통제관 담당 제대 (예: "1제대"), 지휘관은 None
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # 관계
    missions: Mapped[list["Mission"]] = relationship(  # noqa: F821
        "Mission", back_populates="user", lazy="select"
    )

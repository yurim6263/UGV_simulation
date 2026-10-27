"""
backend/app/db/models/assistant_log.py

assistant_logs 테이블: AI 어시스턴트 질문 1건당 1행. 품질/비용/권한 차단 현황을 SQL 로 볼 수 있게 남긴다.

질문 원문은 앞 300자만 저장한다. 답변 본문은 저장하지 않는다 (근거 id 와 경고 수만).
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import JSONType


class AssistantLog(Base):
    __tablename__ = "assistant_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    question: Mapped[str] = mapped_column(String(300), nullable=False)
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    tools: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)       # 호출한 도구 이름들
    denied_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)     # 권한 때문에 막힌 호출 수
    tool_errors: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    grounded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)     # 숫자/인용 확인 통과 여부
    warnings: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    steps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(String(200), nullable=True)             # 모델 호출 실패 사유
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

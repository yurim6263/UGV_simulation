"""
backend/app/api/assistant.py

GET  /api/assistant/status   — 어시스턴트 사용 가능 여부 (키 설정 여부, 모델 이름, 내 역할이 쓸 수 있는 도구)
POST /api/assistant/ask      — 질문 → 도구 호출로 근거를 모아 답변 (읽기 전용)

키가 없으면 ask 는 503. 모델 호출이 실패하면 상세 오류는 서버 로그에만 남기고 502 로 알린다.
"""

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, DBSession
from app.assistant import factory
from app.assistant.agent import ask
from app.assistant.schema import ModelError, ToolContext
from app.assistant.tools import role_of, visible_tools
from app.core.config import settings
from app.core.rate_limit import limiter
from app.db.models.assistant_log import AssistantLog

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/assistant", tags=["assistant"])


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)


class EvidenceOut(BaseModel):
    id: str
    tool: str
    args: dict
    result: dict
    denied: bool = False
    error: str | None = None


class AskResponse(BaseModel):
    answer: str
    evidences: list[EvidenceOut]
    warnings: list[str]
    model: str
    latency_ms: int


@router.get("/status", summary="AI 어시스턴트 사용 가능 여부")
async def assistant_status(user: CurrentUser):
    return {
        "enabled": factory.is_configured(),
        "model": settings.gemini_model if factory.is_configured() else None,
        "role": role_of(user),
        "tools": [t.name for t in visible_tools(role_of(user))],
    }


@router.post("/ask", response_model=AskResponse, summary="어시스턴트에게 질문")
@limiter.limit(settings.assistant_rate_limit)
async def ask_assistant(request: Request, body: AskRequest, db: DBSession, user: CurrentUser):
    if not factory.is_configured():
        raise HTTPException(status_code=503, detail="AI 어시스턴트가 설정되지 않았습니다 (서버에 GEMINI_API_KEY 가 필요합니다).")
    role = role_of(user)
    ctx = ToolContext(db=db, user=user, role=role)
    log = AssistantLog(user_id=str(user.sub), role=role, question=body.question[:300], model="", tools=[])
    try:
        result = await ask(body.question, ctx, factory.get_model())
    except ModelError as exc:
        logger.error("assistant model error: %s", exc)
        log.error = str(exc)[:200]
        db.add(log)
        await db.commit()
        raise HTTPException(status_code=502, detail="AI 모델 호출에 실패했습니다. 잠시 후 다시 시도하세요.") from exc

    log.model = result.model
    log.tools = [e.tool for e in result.evidences]
    log.denied_calls = sum(e.denied for e in result.evidences)
    log.tool_errors = sum(1 for e in result.evidences if e.error and not e.denied)
    log.warnings = len(result.warnings)
    log.grounded = result.grounded
    log.steps, log.latency_ms = result.steps, result.latency_ms
    log.prompt_tokens, log.output_tokens = result.usage.get("prompt_tokens", 0), result.usage.get("output_tokens", 0)
    db.add(log)
    await db.commit()
    return AskResponse(
        answer=result.answer, warnings=result.warnings, model=result.model, latency_ms=result.latency_ms,
        evidences=[EvidenceOut(id=e.id, tool=e.tool, args=e.args, result=e.result, denied=e.denied, error=e.error) for e in result.evidences],
    )

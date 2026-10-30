"""
backend/app/assistant/schema.py

어시스턴트 공통 타입. 모델 공급자(Gemini 등)와 무관하다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict


@dataclass
class ModelTurn:
    """모델의 한 번의 응답: 도구 호출 요청이거나 최종 답변 텍스트."""
    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: Any = None                  # 공급자 원본 응답(다음 턴에 그대로 돌려보내야 하는 값, 예: 사고 서명)
    usage: dict = field(default_factory=dict)


@dataclass
class Message:
    """대화 기록 한 칸. role: user | model | tool"""
    role: str
    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)       # role=model
    tool_results: list[tuple[ToolCall, dict]] = field(default_factory=list)   # role=tool
    raw: Any = None                                                # role=model 일 때 공급자 원본


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict                 # JSON Schema (type 은 소문자)
    roles: tuple[str, ...]           # 이 도구를 쓸 수 있는 역할 (commander / operator)
    handler: Callable[["ToolContext", dict], Awaitable[dict]]


@dataclass
class ToolContext:
    db: Any                          # AsyncSession
    user: Any                        # TokenPayload
    role: str                        # commander | operator (admin 은 commander 로 취급)


class ToolError(Exception):
    """도구가 의도적으로 돌려주는 오류 (잘못된 인자, 기록 없음 등). 모델에게 그대로 보여 준다."""


@dataclass
class Evidence:
    """도구 호출 1건 = 근거 1건. 답변은 [E1] 처럼 이 id 로 인용해야 한다."""
    id: str
    tool: str
    args: dict
    result: dict
    denied: bool = False
    error: str | None = None


@dataclass
class AssistantResult:
    answer: str
    evidences: list[Evidence]
    warnings: list[str]
    steps: int
    model: str
    latency_ms: int
    usage: dict = field(default_factory=dict)
    grounded: bool = True            # 최종 답변이 숫자/인용 확인을 통과했는가


class ModelClient(Protocol):
    name: str

    async def next(self, system: str, messages: list[Message], tools: list[ToolSpec]) -> ModelTurn: ...


class ModelError(Exception):
    """모델 호출 실패 (네트워크, 인증, 모델 이름 오류 등). 메시지에는 비밀 값이 들어 있지 않아야 한다."""

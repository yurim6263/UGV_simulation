"""
backend/app/assistant/factory.py

설정에서 모델 클라이언트를 만든다. 테스트는 `override_model` 로 다른 모델을 끼워 넣는다.
"""

from __future__ import annotations

from app.assistant.gemini import GeminiClient
from app.assistant.schema import ModelClient
from app.core.config import settings

_override: ModelClient | None = None


def override_model(model: ModelClient | None) -> None:
    """테스트/평가용: 실제 모델 대신 쓸 모델을 지정한다 (None 이면 해제)."""
    global _override
    _override = model


def is_configured() -> bool:
    return _override is not None or bool(settings.gemini_api_key)


def get_model() -> ModelClient:
    """설정된 모델을 돌려준다. 키가 없으면 ModelError."""
    if _override is not None:
        return _override
    return GeminiClient(settings.gemini_api_key, settings.gemini_model)

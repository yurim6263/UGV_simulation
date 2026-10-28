"""
backend/scripts/list_gemini_models.py

내 키로 쓸 수 있는 Gemini 모델 이름을 보여준다. GEMINI_MODEL 에 넣을 이름을 고를 때 쓴다.
backend/.env 의 GEMINI_API_KEY 를 읽는다. 키는 출력하지 않는다.

    python scripts\\list_gemini_models.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")      # 설정 객체가 요구하는 값 (이 스크립트는 DB 를 쓰지 않는다)

from app.core.config import settings  # noqa: E402


def main() -> int:
    if not settings.gemini_api_key:
        print("GEMINI_API_KEY 가 없습니다 (backend/.env 에 넣으세요).", file=sys.stderr)
        return 2
    from google import genai

    client = genai.Client(api_key=settings.gemini_api_key)
    try:
        models = list(client.models.list())
    except Exception as exc:  # noqa: BLE001
        print(f"목록을 가져오지 못했습니다 ({type(exc).__name__}): {str(exc).replace(settings.gemini_api_key, '***')[:300]}", file=sys.stderr)
        return 1
    names = []
    for m in models:
        actions = getattr(m, "supported_actions", None) or []
        if "generateContent" in actions:
            names.append(m.name.removeprefix("models/"))
    print(f"현재 설정: GEMINI_MODEL={settings.gemini_model}")
    print(f"generateContent 를 지원하는 모델 {len(names)}개:")
    for n in sorted(names):
        print("  ", n)
    return 0


if __name__ == "__main__":
    sys.exit(main())

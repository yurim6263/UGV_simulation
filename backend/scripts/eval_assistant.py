"""
backend/scripts/eval_assistant.py

AI 어시스턴트 평가. 임시 DB 에 작은 임무를 3개 모드로 실행해 기록을 만든 뒤, 질문 세트(app/assistant/evals.py)를 물어 채점한다.
운영 DB 는 건드리지 않는다 (DATABASE_URL 을 임시 SQLite 파일로 덮어쓴다).

    # 모델 없이 파이프라인 확인 (규칙 기반 모델 — LLM 품질을 재는 것이 아니다)
    python scripts/eval_assistant.py

    # 실제 Gemini 로 평가 (backend/.env 에 GEMINI_API_KEY 필요)
    python scripts/eval_assistant.py --live --delay 4

backend 폴더에서 실행한다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

TMP = Path(tempfile.mkdtemp(prefix="fw_eval_"))
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{(TMP / 'eval.db').as_posix()}"      # 운영 DB 보호
os.environ["JWT_SECRET_KEY"] = "eval-only-secret-0123456789abcdef"
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "eval-admin-pass"
os.environ["SIM_TICK_SLEEP"] = "0"
os.environ.setdefault("SIM_WEATHER_SCALE", "moderate")

MISSION = {"name": "assistant eval", "total_ugv": 4, "max_ugv_count": 4, "mission_duration_min": 90,
           "departure_lat": 54.48, "departure_lon": 18.32}
TARGETS = [{"seq": 1, "lat": 54.45, "lon": 18.40, "patrol_duration_sec": 600},
           {"seq": 2, "lat": 54.42, "lon": 18.36, "patrol_duration_sec": 600}]      # 2제대만 편성된다


async def build_runs() -> int:
    from httpx import ASGITransport, AsyncClient

    from app.db.base import Base
    from app.db.init_db import init_db
    from app.db.session import engine
    from app.main import app as fastapi_app
    import app.db.models as _models  # noqa: F401 — Base.metadata 에 모든 모델 등록

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await init_db()
    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://eval") as c:
        tok = (await c.post("/api/auth/login", json={"username": "admin", "password": "eval-admin-pass"})).json()["access_token"]
        c.headers["Authorization"] = f"Bearer {tok}"
        mid = (await c.post("/api/missions", json=MISSION)).json()["id"]
        await c.post(f"/api/missions/{mid}/targets", json=TARGETS)
        balanced = None
        for mode in ("balanced", "recon", "rapid"):
            rid = (await c.post(f"/api/missions/{mid}/runs?mode={mode}")).json()["id"]
            await c.post(f"/api/runs/{rid}/start")
            balanced = balanced or rid
    return balanced


async def main(args) -> int:
    from app.assistant.evals import run_eval, summarize
    from app.assistant.gemini import GeminiClient
    from app.assistant.scripted import RuleBasedModel
    from app.core.config import settings
    from app.db.session import AsyncSessionLocal

    if args.live:
        if not settings.gemini_api_key:
            print("GEMINI_API_KEY 가 없습니다 (backend/.env 에 넣으세요).", file=sys.stderr)
            return 2
        model = GeminiClient(settings.gemini_api_key, settings.gemini_model)
        if args.delay:
            model = Throttled(model, args.delay)
    else:
        model = RuleBasedModel()

    print("임시 DB에 실행 기록을 만드는 중...", flush=True)
    run_id = await build_runs()
    from app.assistant.schema import ModelError

    async with AsyncSessionLocal() as db:
        try:
            results = await run_eval(model, db, run_id, only=set(args.only.split(",")) if args.only else None)
        except ModelError as exc:
            print(f"\n모델 호출 실패: {exc}", file=sys.stderr)
            if "404" in str(exc):
                print("모델 이름 문제입니다. backend/.env 의 GEMINI_MODEL 을 AI Studio 에 보이는 이름으로 바꾸세요.", file=sys.stderr)
            elif "PerDay" in str(exc):
                print("무료 키의 하루 호출 한도가 소진됐습니다. 한도가 풀릴 때까지(오류 문구의 'retry in' 시간) 기다리거나, 다른 모델/결제 설정을 쓰세요.", file=sys.stderr)
            elif any(c in str(exc) for c in ("429", "503")):
                print("구글 서버가 붐비거나 호출 한도에 걸렸습니다. 잠시 뒤 다시 하거나 --delay 값을 늘리세요.", file=sys.stderr)
            return 2
    summary = summarize(results)

    print(f"\n모델: {model.name}  |  통과 {summary['passed']}/{summary['cases']}")
    for r in results:
        mark = "OK  " if r.passed else "FAIL"
        print(f"  {mark} {r.case.id:22s} tools={r.tools} denied={r.denied} {' '.join(r.notes)}")
    for k, v in summary["by_check"].items():
        print(f"  {k:22s} {v['passed']}/{v['total']}")
    if not args.live:
        print("\n※ 규칙 기반 모델 결과입니다. 파이프라인 확인용이며 LLM 의 이해/답변 품질을 나타내지 않습니다.")
    if args.out:
        Path(args.out).write_text(json.dumps({"model": model.name, "summary": summary, "cases": [
            {"id": r.case.id, "user": r.case.user, "question": r.case.question, "checks": r.checks, "tools": r.tools,
             "denied": r.denied, "answer": r.answer} for r in results]}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"결과 저장: {args.out}")
    return 0 if summary["passed"] == summary["cases"] else 1


class Throttled:
    """무료 요금제의 분당 호출 제한을 피하려고 호출 사이에 쉰다."""

    def __init__(self, inner, delay: float):
        self.inner, self.delay, self.name = inner, delay, inner.name

    async def next(self, system, messages, tools):
        await asyncio.sleep(self.delay)
        return await self.inner.next(system, messages, tools)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="규칙 기반 모델 대신 Gemini 사용")
    ap.add_argument("--delay", type=float, default=0.0, help="모델 호출 사이 대기(초)")
    ap.add_argument("--out", help="결과 JSON 저장 경로")
    ap.add_argument("--only", help="이 id 들만 평가 (쉼표로 구분). 무료 키의 하루 호출 한도를 아낄 때 쓴다")
    sys.exit(asyncio.run(main(ap.parse_args())))

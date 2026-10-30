"""
backend/app/services/plan_service.py

편성 계산을 임무에 연결한다: 시작/진행률/재사용(캐시)/결과 조회, 그리고 실행기가 쓸 "모드별 선택 편성".

재사용 순서: (1) 같은 입력으로 완료된 계산(DB) (2) 미리 계산해 둔 기본 목표 결과(data/formation/default_plan.json) (3) 새로 계산.
진행률은 서버 메모리에 두고(재시작하면 사라진다), 끝난 결과만 DB 에 저장한다. 재시작 때문에 멈춘 계산은 FAILED 로 표시한다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import BackgroundTasks
from sqlalchemy import select

from app.db.models.formation_plan import FormationPlan
from app.db.models.mission import Mission, MissionTarget
from app.db.session import AsyncSessionLocal
from app.simulation.formation import MODES, PlanInput, plan_formations, plan_input_for

logger = logging.getLogger(__name__)

DEFAULT_PLAN_PATH = Path(__file__).resolve().parents[2] / "data" / "formation" / "default_plan.json"
_progress: dict[int, tuple[int, int]] = {}          # plan_id → (끝난 에피소드, 전체)
_active: set[int] = set()


def plan_workers() -> int:
    """병렬 작업자 수. 작업자 하나가 메모리를 약 180MB 쓰므로 기본은 낮게 둔다 (PLAN_WORKERS 로 조절)."""
    return max(1, int(os.getenv("PLAN_WORKERS", "4")))


async def load_mission_dict(db, mission_id: int) -> dict | None:
    mission = await db.get(Mission, mission_id)
    if mission is None:
        return None
    targets = (await db.execute(select(MissionTarget).where(MissionTarget.mission_id == mission_id).order_by(MissionTarget.seq))).scalars().all()
    return {
        "id": mission.id, "total_ugv": max(1, mission.total_ugv), "departure_lat": mission.departure_lat,
        "departure_lon": mission.departure_lon, "targets": [(t.lat, t.lon) for t in targets],
        "patrol_sec": [t.patrol_duration_sec for t in targets], "duration_min": mission.mission_duration_min,
    }


def _scale() -> float:
    from app.simulation.real_runner import _weather_scale
    return _weather_scale()


def _default_plan(key: str) -> dict | None:
    """미리 계산해 둔 기본 목표 결과. 입력이 같을 때(키가 같을 때)만 쓴다."""
    if not DEFAULT_PLAN_PATH.exists():
        return None
    try:
        plan = json.loads(DEFAULT_PLAN_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return plan if plan.get("cache_key") == key else None


def state_of(row: FormationPlan | None) -> dict:
    if row is None:
        return {"status": "NONE", "done": 0, "total": 0, "cached": False, "plan": None, "error": None}
    done, total = _progress.get(row.id, (row.done, row.total))
    return {"status": row.status, "done": done, "total": total, "cached": row.cached,
            "plan": row.plan if row.status == "COMPLETED" else None, "error": row.error}


async def latest_plan(db, mission_id: int) -> FormationPlan | None:
    row = (await db.execute(select(FormationPlan).where(FormationPlan.mission_id == mission_id).order_by(FormationPlan.id.desc()).limit(1))).scalar_one_or_none()
    if row is not None and row.status in ("PENDING", "RUNNING") and row.id not in _active:
        row.status, row.error, row.finished_at = "FAILED", "서버가 다시 시작되어 계산이 중단되었습니다. 다시 실행하세요.", datetime.now(timezone.utc)
        await db.commit()
    return row


async def start_plan(db, mission_id: int, background_tasks: BackgroundTasks) -> FormationPlan | None:
    """편성 계산을 시작한다 (이미 같은 입력의 계산이 있으면 그것을 돌려준다)."""
    mission = await load_mission_dict(db, mission_id)
    if mission is None:
        return None
    inp = plan_input_for(mission, _scale())
    key = inp.cache_key()

    current = await latest_plan(db, mission_id)
    if current is not None and current.cache_key == key and current.status in ("RUNNING", "PENDING", "COMPLETED"):
        return current

    reuse = (await db.execute(select(FormationPlan).where(FormationPlan.cache_key == key, FormationPlan.status == "COMPLETED")
                              .order_by(FormationPlan.id.desc()).limit(1))).scalar_one_or_none()
    cached_plan = reuse.plan if reuse is not None else _default_plan(key)
    if cached_plan is not None:
        row = FormationPlan(mission_id=mission_id, cache_key=key, status="COMPLETED", cached=True, plan=cached_plan,
                            done=cached_plan.get("episodes", 0), total=cached_plan.get("episodes", 0), finished_at=datetime.now(timezone.utc))
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row

    total = inp.n_teams * (inp.max_per_team - inp.min_per_team + 1) * len(inp.seeds) * len(MODES)       # 단독 에피소드 수
    row = FormationPlan(mission_id=mission_id, cache_key=key, status="RUNNING", done=0, total=total)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    _active.add(row.id)
    _progress[row.id] = (0, total)
    background_tasks.add_task(_run, row.id, inp)
    return row


async def _run(plan_id: int, inp: PlanInput) -> None:
    def on_progress(done: int, total: int) -> None:
        _progress[plan_id] = (done, total)

    plan, error = None, None
    try:
        try:
            plan = await asyncio.to_thread(plan_formations, inp, plan_workers(), on_progress)
        except Exception:  # noqa: BLE001 — 작업자 프로세스가 죽는 등 병렬 실행 문제면 한 프로세스로 다시 한다 (느리지만 끝낸다)
            logger.exception("병렬 편성 계산 실패, 순차 실행으로 재시도")
            plan = await asyncio.to_thread(plan_formations, inp, 1, on_progress)
    except Exception as exc:  # noqa: BLE001
        logger.exception("편성 계산 실패 plan_id=%d", plan_id)
        error = f"{type(exc).__name__}: {str(exc)[:200]}"
    finally:
        async with AsyncSessionLocal() as db:
            row = await db.get(FormationPlan, plan_id)
            if row is not None:
                row.status = "COMPLETED" if plan is not None else "FAILED"
                row.plan, row.error, row.finished_at = plan, error, datetime.now(timezone.utc)
                row.done = row.total = (plan or {}).get("episodes", row.total)
                await db.commit()
        _active.discard(plan_id)
        _progress.pop(plan_id, None)


async def chosen_formation(mission: dict, mode: str, scale: float) -> tuple | None:
    """실행기가 쓸 모드별 편성. 이 임무에 입력이 같은 완료된 계산이 있을 때만 (없거나 입력이 바뀌었으면 None)."""
    key = plan_input_for(mission, scale).cache_key()
    async with AsyncSessionLocal() as db:
        row = (await db.execute(select(FormationPlan).where(FormationPlan.mission_id == mission["id"], FormationPlan.cache_key == key,
                                                           FormationPlan.status == "COMPLETED").order_by(FormationPlan.id.desc()).limit(1))).scalar_one_or_none()
    if row is None or not row.plan:
        logger.warning("mission_id=%s 에 일치하는 편성 계산이 없어 보유 대수를 고르게 나눕니다", mission["id"])
        return None
    return tuple(row.plan["modes"][mode]["pick"]["formation"])

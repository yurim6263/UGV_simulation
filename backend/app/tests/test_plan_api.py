"""
backend/app/tests/test_plan_api.py

편성 계산 API와 실행 연결 테스트. 계산량을 줄이려고 시드를 1개로, 작업자를 1개로 줄이고 목표 1곳(제대 1개)으로 한다.
"""

import json

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.models.formation_plan import FormationPlan
from app.db.session import AsyncSessionLocal
from app.services import plan_service
from app.simulation import formation

MISSION = {"name": "편성 계산 확인", "total_ugv": 3, "max_ugv_count": 3, "mission_duration_min": 120,
           "departure_lat": 54.48, "departure_lon": 18.32}
TARGET = {"seq": 1, "lat": 54.45, "lon": 18.40, "patrol_duration_sec": 600}


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setenv("SIM_TICK_SLEEP", "0")
    monkeypatch.setenv("SIM_WEATHER_SCALE", "clear")
    monkeypatch.setenv("PLAN_WORKERS", "1")
    original = formation.plan_input_for
    monkeypatch.setattr(plan_service, "plan_input_for", lambda mission, scale: original(mission, scale, seeds=(7,)))
    monkeypatch.setattr(plan_service, "DEFAULT_PLAN_PATH", plan_service.DEFAULT_PLAN_PATH.with_name("__none__.json"))
    plan_service._progress.clear()


async def finish_plan(c: AsyncClient, mid: int) -> dict:
    """계획을 시작하고(응답은 시작 시점 상태) 끝난 뒤의 상태를 읽는다. 테스트에서는 요청이 끝날 때 백그라운드 계산도 끝난다."""
    await c.post(f"/api/missions/{mid}/plan")
    return (await c.get(f"/api/missions/{mid}/plan")).json()


async def new_mission(c: AsyncClient, **over) -> int:
    mid = (await c.post("/api/missions", json={**MISSION, **over})).json()["id"]
    await c.post(f"/api/missions/{mid}/targets", json=[TARGET])
    return mid


@pytest.mark.asyncio
async def test_plan_runs_in_the_background_and_returns_picks_for_every_mode(auth_client: AsyncClient):
    mid = await new_mission(auth_client)
    started = (await auth_client.post(f"/api/missions/{mid}/plan")).json()
    assert started["status"] == "RUNNING" and started["total"] == 9 and started["plan"] is None       # 시작 시점: 아직 계산 중
    state = (await auth_client.get(f"/api/missions/{mid}/plan")).json()
    assert state["status"] == "COMPLETED" and state["cached"] is False and state["done"] == state["total"] == 9
    modes = state["plan"]["modes"]
    assert set(modes) == {"balance", "explore", "rush"}
    for m in modes.values():
        assert [c["formation"] for c in m["candidates"]] == [[1], [2], [3]]
        assert m["pick"]["formation"] in ([1], [2], [3])


@pytest.mark.asyncio
async def test_same_inputs_reuse_the_finished_plan_without_recomputing(auth_client: AsyncClient, monkeypatch):
    first = await new_mission(auth_client)
    original = await finish_plan(auth_client, first)
    monkeypatch.setattr(plan_service, "plan_formations", lambda *a, **k: (_ for _ in ()).throw(AssertionError("다시 계산하면 안 된다")))
    second = await new_mission(auth_client)
    state = (await auth_client.post(f"/api/missions/{second}/plan")).json()
    assert state["status"] == "COMPLETED" and state["cached"] is True and state["plan"] == original["plan"]
    # 입력이 다르면(정찰 시간) 재사용하지 않는다 — 여기서는 계산 함수가 막혀 있으므로 FAILED 로 드러난다
    third = (await auth_client.post("/api/missions", json=MISSION)).json()["id"]
    await auth_client.post(f"/api/missions/{third}/targets", json=[{**TARGET, "patrol_duration_sec": 1800}])
    changed = await finish_plan(auth_client, third)
    assert changed["cached"] is False and changed["status"] == "FAILED"


@pytest.mark.asyncio
async def test_runs_use_the_planned_formation_of_their_mode(auth_client: AsyncClient):
    mid = await new_mission(auth_client)
    plan = (await finish_plan(auth_client, mid))["plan"]["modes"]
    for server_mode, mode in (("rapid", "rush"), ("recon", "explore")):
        run_id = (await auth_client.post(f"/api/missions/{mid}/runs?mode={server_mode}")).json()["id"]
        await auth_client.post(f"/api/runs/{run_id}/start")
        per_team = (await auth_client.get(f"/api/runs/{run_id}/replay")).json()["mode"]["kpi"]["per_team"]
        assert per_team["Alpha"]["ugv"] == plan[mode]["pick"]["formation"][0], mode


@pytest.mark.asyncio
async def test_run_without_a_plan_splits_the_fleet_evenly_capped_at_three_per_team(auth_client: AsyncClient):
    mid = await new_mission(auth_client, total_ugv=2, max_ugv_count=2)
    run_id = (await auth_client.post(f"/api/missions/{mid}/runs")).json()["id"]
    await auth_client.post(f"/api/runs/{run_id}/start")
    assert (await auth_client.get(f"/api/runs/{run_id}/replay")).json()["mode"]["kpi"]["per_team"]["Alpha"]["ugv"] == 2


@pytest.mark.asyncio
async def test_plan_is_ignored_when_the_mission_inputs_changed_after_planning(auth_client: AsyncClient):
    mid = await new_mission(auth_client)
    await finish_plan(auth_client, mid)
    await auth_client.post(f"/api/missions/{mid}/targets", json=[{**TARGET, "lat": 54.42, "lon": 18.40}])     # 목표를 바꿈
    async with AsyncSessionLocal() as db:
        mission = await plan_service.load_mission_dict(db, mid)
    assert await plan_service.chosen_formation(mission, "balance", 0.15) is None


# ── AI 도구: 편성이 왜 그렇게 정해졌는지 ─────────────────────────────────────

@pytest.mark.asyncio
async def test_formation_tool_reports_picks_reasons_and_not_dominated_candidates(auth_client: AsyncClient):
    from app.assistant.schema import ToolCall, ToolContext
    from app.assistant.tools import execute_tool
    from app.core.security import TokenPayload

    mid = await new_mission(auth_client)
    plan = (await finish_plan(auth_client, mid))["plan"]
    run_id = (await auth_client.post(f"/api/missions/{mid}/runs")).json()["id"]          # 가장 최근 임무를 만든다
    assert run_id
    async with AsyncSessionLocal() as db:
        ctx = ToolContext(db=db, user=TokenPayload(sub="1", role="commander"), role="commander")
        e = await execute_tool(ctx, ToolCall("get_formation_plan", {}), "E1")
    assert not e.error, e.result
    r = e.result
    assert r["mission_id"] == mid and r["seeds"] == 1 and r["fleet_ugv"] == 9 and r["min_arrival_pct"] == 80 and "시뮬레이션 추정" in r["caveat"]
    for key, label in (("balance", "균형"), ("explore", "정밀"), ("rush", "신속")):
        m = r["modes"][key]
        assert m["label"] == label and m["pick"]["formation"] == plan["modes"][key]["pick"]["formation"]
        assert m["pick_metrics"]["formation"] == m["pick"]["formation"] and 0 <= m["pick_metrics"]["arrival_pct"] <= 100
        assert m["not_dominated_candidates"] and m["candidates_total"] == 3


@pytest.mark.asyncio
async def test_formation_tool_is_commander_only_and_reports_a_missing_plan(auth_client: AsyncClient):
    from app.assistant.schema import ToolCall, ToolContext
    from app.assistant.tools import execute_tool, visible_tools
    from app.core.security import TokenPayload

    assert "get_formation_plan" in {t.name for t in visible_tools("commander")}
    assert "get_formation_plan" not in {t.name for t in visible_tools("operator")}
    mid = await new_mission(auth_client)
    await auth_client.post(f"/api/missions/{mid}/runs")                                # 계산 없이 만든 임무
    async with AsyncSessionLocal() as db:
        none = await execute_tool(ToolContext(db=db, user=TokenPayload(sub="1", role="commander"), role="commander"), ToolCall("get_formation_plan", {}), "E1")
        denied = await execute_tool(ToolContext(db=db, user=TokenPayload(sub="2", role="operator", unit="1제대"), role="operator"), ToolCall("get_formation_plan", {}), "E2")
    assert none.error and "편성 계산이 없습니다" in none.result["error"]
    assert denied.denied


@pytest.mark.asyncio
async def test_plan_endpoints_are_commander_only_and_validate_the_mission(operator_client: AsyncClient, auth_client: AsyncClient):
    assert (await operator_client.post("/api/missions/1/plan")).status_code == 403
    assert (await operator_client.get("/api/missions/1/plan")).status_code == 403
    assert (await auth_client.post("/api/missions/9999/plan")).status_code == 404
    assert (await auth_client.get("/api/missions/9999/plan")).status_code == 404
    mid = await new_mission(auth_client)
    assert (await auth_client.get(f"/api/missions/{mid}/plan")).status_code == 404         # 시작 전


@pytest.mark.asyncio
async def test_unfinished_plan_after_a_server_restart_is_marked_failed(auth_client: AsyncClient):
    mid = await new_mission(auth_client)
    async with AsyncSessionLocal() as db:
        db.add(FormationPlan(mission_id=mid, cache_key="x" * 40, status="RUNNING", done=3, total=9))
        await db.commit()
    state = (await auth_client.get(f"/api/missions/{mid}/plan")).json()
    assert state["status"] == "FAILED" and "다시 시작" in state["error"]


@pytest.mark.asyncio
async def test_precomputed_default_plan_is_used_when_the_key_matches(auth_client: AsyncClient, monkeypatch, tmp_path):
    mid = await new_mission(auth_client)
    async with AsyncSessionLocal() as db:
        mission = await plan_service.load_mission_dict(db, mid)
    key = plan_service.plan_input_for(mission, plan_service._scale()).cache_key()
    stored = {"cache_key": key, "episodes": 9, "modes": {m: {"candidates": [], "pick": {"formation": [2], "reason": "저장본"}} for m in formation.MODES}}
    path = tmp_path / "default_plan.json"
    path.write_text(json.dumps(stored), encoding="utf-8")
    monkeypatch.setattr(plan_service, "DEFAULT_PLAN_PATH", path)
    monkeypatch.setattr(plan_service, "plan_formations", lambda *a, **k: (_ for _ in ()).throw(AssertionError("저장본이 있으면 계산하지 않는다")))
    state = (await auth_client.post(f"/api/missions/{mid}/plan")).json()
    assert state["cached"] is True and state["plan"]["modes"]["rush"]["pick"]["reason"] == "저장본"
    path.write_text(json.dumps({**stored, "cache_key": "0" * 40}), encoding="utf-8")           # 키가 다르면 쓰지 않는다
    assert plan_service._default_plan(key) is None

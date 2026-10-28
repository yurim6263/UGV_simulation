"""
backend/app/tests/test_real_runner.py

엔진 기반 시뮬레이션 실행 → DB 기록 → KPI → 재생 API 통합 테스트.
작은 임무(UGV 2대, 목표 1곳, 6턴)로 실행해 시간을 줄였다.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.db.models.patrol import RunPatrolEvent
from app.db.models.route import RunKpi, RunRecommendation, RunRoute, RunRouteEffect
from app.db.models.simulation_run import SimulationRun
from app.db.models.snapshot import RunStatusSnapshot
from app.db.models.track import RunTrack
from app.db.models.unit_state import RunUnit
from app.db.session import AsyncSessionLocal
from app.simulation.presets import MODE_PRESETS
from app.simulation.real_runner import build_scenario, even_split, run_real

MISSION = {
    "name": "엔진 통합 테스트",
    "total_ugv": 2,
    "max_ugv_count": 2,
    "mission_duration_min": 60,          # 6턴
    "departure_lat": 54.48,
    "departure_lon": 18.32,
}


@pytest.fixture(autouse=True)
def _fast_clear_weather(monkeypatch):
    monkeypatch.setenv("SIM_TICK_SLEEP", "0")
    monkeypatch.setenv("SIM_WEATHER_SCALE", "clear")


async def _make_run(c: AsyncClient) -> int:
    mid = (await c.post("/api/missions", json=MISSION)).json()["id"]
    targets = await c.post(f"/api/missions/{mid}/targets", json=[{"seq": 1, "lat": 54.45, "lon": 18.40, "patrol_duration_sec": 600}])
    assert targets.status_code == 201, targets.text
    return (await c.post(f"/api/missions/{mid}/runs")).json()["id"]


async def _count(model, run_id: int) -> int:
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(func.count()).select_from(model).where(model.run_id == run_id))).scalar_one()


# ── 시나리오 구성 (DB 불필요) ────────────────────────────────────────────

def test_even_split_distributes_all_ugvs():
    assert even_split(9, 3) == (3, 3, 3)
    assert even_split(13, 3) == (5, 4, 4)
    assert sum(even_split(7, 2)) == 7


def test_scenario_uses_one_team_per_target_and_an_even_capped_split_without_a_plan():
    base = {"departure_lat": 54.48, "departure_lon": 18.32, "duration_min": 240}
    three = [(54.40, 18.54), (54.33, 18.36), (54.37, 18.50)]
    spec, _ = build_scenario({**base, "total_ugv": 9, "targets": three}, "balance", 0.3)
    assert spec.formation == (3, 3, 3) and len(spec.pois) == 3         # 모드에 묶인 고정 편성은 없다
    spec, _ = build_scenario({**base, "total_ugv": 13, "targets": three}, "balance", 0.3)
    assert spec.formation == (3, 3, 3)                                  # 제대당 최대 3대
    spec, _ = build_scenario({**base, "total_ugv": 5, "targets": three[:2]}, "rush", 0.3)
    assert spec.formation == (3, 2) and spec.assignment == (0, 1)     # 균등 분배
    spec, _ = build_scenario({**base, "total_ugv": 4, "targets": []}, "explore", 0.3)
    assert len(spec.pois) == 3 and spec.formation == (2, 1, 1)         # 목표가 없으면 기본 정찰지 3곳


def test_scenario_uses_the_planned_formation_for_the_mode_when_given():
    base = {"departure_lat": 54.48, "departure_lon": 18.32, "duration_min": 240, "total_ugv": 9}
    three = [(54.40, 18.54), (54.33, 18.36), (54.37, 18.50)]
    for mode in ("balance", "explore", "rush"):                         # 같은 계산 결과라면 모드와 무관하게 주어진 편성을 쓴다
        spec, _ = build_scenario({**base, "targets": three, "formation": (2, 1, 3)}, mode, 0.3)
        assert spec.formation == (2, 1, 3) and spec.assignment == (0, 1, 2)
    spec, _ = build_scenario({**base, "targets": three, "formation": (2, 1)}, "balance", 0.3)   # 제대 수와 안 맞으면 무시
    assert spec.formation == (3, 3, 3)


def test_scenario_turn_limit_follows_the_mission_duration():
    base = {"departure_lat": 54.48, "departure_lon": 18.32, "total_ugv": 2, "targets": [(54.45, 18.40)]}
    assert build_scenario({**base, "duration_min": 60}, "balance", 0.3)[0].max_turns == 6
    assert build_scenario({**base, "duration_min": 10_000}, "balance", 0.3)[0].max_turns == 31   # 실황 데이터 범위


# ── 실행 ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_produces_real_records_and_kpis(auth_client: AsyncClient):
    run_id = await _make_run(auth_client)
    started = await auth_client.post(f"/api/runs/{run_id}/start")
    assert started.status_code == 200

    async with AsyncSessionLocal() as db:
        run = await db.get(SimulationRun, run_id)
        assert run.status == "COMPLETED" and run.progress_pct == 100

    assert await _count(RunTrack, run_id) > 20                 # 이동 기록이 쌓였다
    assert await _count(RunStatusSnapshot, run_id) >= 1
    assert await _count(RunUnit, run_id) == 2                  # UGV 2대
    assert await _count(RunKpi, run_id) == 1
    assert await _count(RunRouteEffect, run_id) == 1
    assert await _count(RunRecommendation, run_id) == 1
    assert await _count(RunRoute, run_id) == 2

    async with AsyncSessionLocal() as db:
        kpi = (await db.execute(select(RunKpi).where(RunKpi.run_id == run_id))).scalar_one()
        effect = (await db.execute(select(RunRouteEffect).where(RunRouteEffect.run_id == run_id))).scalar_one()
    assert 0.0 <= kpi.success_rate <= 100.0
    assert kpi.makespan_sec % 600 == 0                          # 턴 단위
    assert {"v1_coverage", "v2_minutes", "v3_overload_minutes"} <= set(kpi.queue_kpi)
    assert effect.success_rate_delta == pytest.approx(effect.optimal_success_rate - effect.alt_success_rate)


@pytest.mark.asyncio
async def test_kpis_are_deterministic_for_the_same_run_id_not_random(auth_client: AsyncClient):
    """예전 real_runner 는 성공률을 `40 + tick*3.5 + random` 으로 만들었다. 이제 엔진 결과만 쓴다."""
    run_id = await _make_run(auth_client)
    await auth_client.post(f"/api/runs/{run_id}/start")
    async with AsyncSessionLocal() as db:
        first = (await db.execute(select(RunKpi).where(RunKpi.run_id == run_id))).scalar_one().success_rate
    tracks = await _count(RunTrack, run_id)
    # 같은 run 을 다시 실행해도(시드 = 임무 id) 같은 결과이고, 이전 산출물이 쌓여 중복되지 않아야 한다
    await run_real(run_id)
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(RunKpi).where(RunKpi.run_id == run_id))).scalars().all()
    assert len(rows) == 1 and rows[0].success_rate == first
    assert await _count(RunTrack, run_id) == tracks


@pytest.mark.asyncio
async def test_cancelled_run_stops_without_finalizing(auth_client: AsyncClient):
    run_id = await _make_run(auth_client)
    assert (await auth_client.post(f"/api/runs/{run_id}/cancel")).status_code == 200
    await run_real(run_id)                                     # 취소된 run 은 스트리밍/KPI 확정 없이 멈춘다
    assert await _count(RunKpi, run_id) == 0
    assert await _count(RunStatusSnapshot, run_id) == 0
    async with AsyncSessionLocal() as db:
        assert (await db.get(SimulationRun, run_id)).status == "CANCELLED"


@pytest.mark.asyncio
async def test_out_of_domain_departure_fails_loudly(auth_client: AsyncClient):
    seoul = {**MISSION, "departure_lat": 37.5, "departure_lon": 127.0}
    mid = (await auth_client.post("/api/missions", json=seoul)).json()["id"]
    run_id = (await auth_client.post(f"/api/missions/{mid}/runs")).json()["id"]
    await auth_client.post(f"/api/runs/{run_id}/start")        # orchestrator 가 실패를 잡아 FAILED 로 표시
    async with AsyncSessionLocal() as db:
        assert (await db.get(SimulationRun, run_id)).status == "FAILED"


# ── 재생 API ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_replay_endpoint_returns_the_frontend_format(auth_client: AsyncClient):
    run_id = await _make_run(auth_client)
    await auth_client.post(f"/api/runs/{run_id}/start")
    resp = await auth_client.get(f"/api/runs/{run_id}/replay")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    mode = body["mode"]
    assert {"agents", "actions", "columns", "steps", "kpi"} <= set(mode)
    assert len(mode["steps"]) == await _count(RunTrack, run_id)
    assert body["scenario"]["bounds"][0][0] < body["scenario"]["bounds"][1][0]
    assert body["scenario"]["pois"][0]["id"] == 1


@pytest.mark.asyncio
async def test_replay_is_404_before_a_run_has_records(auth_client: AsyncClient):
    run_id = await _make_run(auth_client)
    assert (await auth_client.get(f"/api/runs/{run_id}/replay")).status_code == 404
    assert (await auth_client.get("/api/runs/99999/replay")).status_code == 404


@pytest.mark.asyncio
async def test_starting_a_run_twice_is_rejected(auth_client: AsyncClient):
    run_id = await _make_run(auth_client)
    assert (await auth_client.post(f"/api/runs/{run_id}/start")).status_code == 200
    again = await auth_client.post(f"/api/runs/{run_id}/start")
    assert again.status_code == 409
    assert await _count(RunKpi, run_id) == 1                   # 두 번째 시작이 기록을 중복시키지 않았다


@pytest.mark.asyncio
async def test_arrival_starts_the_patrol_countdown_with_the_mission_patrol_time(auth_client: AsyncClient):
    run_id = await _make_run(auth_client)                      # 목표의 정찰 시간 600초
    await auth_client.post(f"/api/runs/{run_id}/start")
    async with AsyncSessionLocal() as db:
        events = (await db.execute(select(RunPatrolEvent).where(RunPatrolEvent.run_id == run_id))).scalars().all()
    assert events, "UGV 가 도착했다면 정찰 이벤트가 있어야 한다"
    assert all(e.patrol_duration_sec == 600 and e.target_seq == 1 for e in events)


def test_scenario_converts_patrol_seconds_to_turns():
    base = {"departure_lat": 54.48, "departure_lon": 18.32, "total_ugv": 5, "duration_min": 240,
            "targets": [(54.40, 18.54), (54.33, 18.36)], "patrol_sec": [1800, 601]}
    spec, _ = build_scenario(base, "rush", 0.3)
    assert spec.dwell_turns == (3, 2)                          # 1800초 = 3턴, 601초는 올림해 2턴


# ── 프론트 연동용 API ────────────────────────────────────────────────────

BIG = {**MISSION, "total_ugv": 9}


@pytest.mark.asyncio
async def test_mission_can_hold_the_whole_force_not_just_four_ugvs(auth_client: AsyncClient):
    """예전 스키마는 total_ugv 를 4대로 제한했다. 임무 하나가 3개 제대 전체를 편성하므로 9대가 가능해야 한다."""
    assert (await auth_client.post("/api/missions", json=BIG)).status_code == 201
    assert (await auth_client.post("/api/missions", json={**MISSION, "total_ugv": 21})).status_code == 422


@pytest.mark.asyncio
async def test_run_can_be_created_with_a_mode_and_rejects_unknown_modes(auth_client: AsyncClient):
    mid = (await auth_client.post("/api/missions", json=MISSION)).json()["id"]
    ok = await auth_client.post(f"/api/missions/{mid}/runs?mode=rapid")
    assert ok.status_code == 201
    assert (await auth_client.post(f"/api/missions/{mid}/runs?mode=turbo")).status_code == 422


@pytest.mark.asyncio
async def test_latest_run_set_lists_the_most_recent_missions_runs_by_mode(auth_client: AsyncClient, login_as):
    assert (await auth_client.get("/api/runs/latest-set")).status_code == 404       # 아직 아무것도 없음
    old = (await auth_client.post("/api/missions", json=MISSION)).json()["id"]
    await auth_client.post(f"/api/missions/{old}/runs")
    mid = (await auth_client.post("/api/missions", json=MISSION)).json()["id"]
    for mode in ("balanced", "recon", "rapid"):
        await auth_client.post(f"/api/missions/{mid}/runs?mode={mode}")

    user1 = await login_as("user1")                                                  # 통제관도 같은 결과를 이어서 본다
    body = (await user1.get("/api/runs/latest-set")).json()
    assert body["mission_id"] == mid                                                 # 이전 임무가 아니라 가장 최근 임무
    assert [r["mode"] for r in body["runs"]] == ["balanced", "recon", "rapid"]
    assert body["all_completed"] is False and all(r["status"] == "CREATED" for r in body["runs"])


@pytest.mark.asyncio
async def test_all_completed_turns_true_once_every_run_finished(auth_client: AsyncClient):
    mid = (await auth_client.post("/api/missions", json=MISSION)).json()["id"]
    await auth_client.post(f"/api/missions/{mid}/targets", json=[{"seq": 1, "lat": 54.45, "lon": 18.40, "patrol_duration_sec": 600}])
    run_id = (await auth_client.post(f"/api/missions/{mid}/runs?mode=balanced")).json()["id"]
    await auth_client.post(f"/api/runs/{run_id}/start")
    body = (await auth_client.get("/api/runs/latest-set")).json()
    assert body["all_completed"] is True and body["runs"][0]["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_overlay_image_is_public_png_and_validates_its_arguments(client: AsyncClient):
    resp = await client.get("/api/map/overlay/total/3.png", params={"scale": 0.3})   # <img> 는 인증 헤더를 보낼 수 없다
    assert resp.status_code == 200 and resp.headers["content-type"] == "image/png"
    assert resp.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert (await client.get("/api/map/overlay/total/99.png")).status_code == 404
    assert (await client.get("/api/map/overlay/humidity/1.png")).status_code == 422
    other = await client.get("/api/map/overlay/sensor/3.png", params={"scale": 0.3})
    assert other.content != resp.content                                              # 종류에 따라 다른 이미지


# ── 통제관 재생 데이터 / 공통 시드 ───────────────────────────────────────

async def _two_team_run(c: AsyncClient, mode: str = "balanced") -> tuple[int, int]:
    """UGV 2대, 목표 2곳 → 1제대(Alpha)와 2제대(Bravo)만 편성된다. (mission_id, run_id)"""
    mid = (await c.post("/api/missions", json=MISSION)).json()["id"]
    await c.post(f"/api/missions/{mid}/targets", json=[
        {"seq": 1, "lat": 54.45, "lon": 18.40, "patrol_duration_sec": 600},
        {"seq": 2, "lat": 54.42, "lon": 18.36, "patrol_duration_sec": 600},
    ])
    run_id = (await c.post(f"/api/missions/{mid}/runs?mode={mode}")).json()["id"]
    return mid, run_id


@pytest.mark.asyncio
async def test_operator_replay_contains_only_their_own_unit(auth_client: AsyncClient, login_as):
    _, run_id = await _two_team_run(auth_client)
    await auth_client.post(f"/api/runs/{run_id}/start")

    commander = (await auth_client.get(f"/api/runs/{run_id}/replay")).json()["mode"]
    assert {a["team"] for a in commander["agents"]} == {"Alpha", "Bravo"}            # 지휘관은 전체

    user2 = await login_as("user2")                                                  # 2제대 = Bravo
    body = (await user2.get(f"/api/runs/{run_id}/replay")).json()["mode"]
    assert body["agents"] and {a["team"] for a in body["agents"]} == {"Bravo"}
    assert set(body["kpi"]["per_team"]) == {"Bravo"}
    assert len(body["steps"]) < len(commander["steps"])                              # 다른 제대의 기록은 내려가지 않는다


@pytest.mark.asyncio
async def test_operator_of_a_team_that_was_not_formed_gets_404_not_a_server_error(auth_client: AsyncClient, login_as):
    _, run_id = await _two_team_run(auth_client)
    await auth_client.post(f"/api/runs/{run_id}/start")
    user3 = await login_as("user3")                                                  # 3제대는 이 임무에 없다
    resp = await user3.get(f"/api/runs/{run_id}/replay")
    assert resp.status_code == 404
    assert "Charlie" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_runs_of_one_mission_share_a_seed_so_same_mode_gives_the_same_result(auth_client: AsyncClient):
    """모드 비교가 시드 운에 흔들리지 않으려면 한 임무의 run 들이 같은 난수를 써야 한다 (예전에는 시드가 run id 였다)."""
    mid, first = await _two_team_run(auth_client)
    second = (await auth_client.post(f"/api/missions/{mid}/runs?mode=balanced")).json()["id"]
    await auth_client.post(f"/api/runs/{first}/start")
    await auth_client.post(f"/api/runs/{second}/start")
    a = (await auth_client.get(f"/api/runs/{first}/replay")).json()["mode"]
    b = (await auth_client.get(f"/api/runs/{second}/replay")).json()["mode"]
    assert a["steps"] == b["steps"] and a["kpi"] == b["kpi"]

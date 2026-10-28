"""
backend/app/tests/test_target_assignment.py

지휘관이 입력한 "목표 i"는 "i제대"가 맡는다. 예전에는 모드 프리셋에 들어 있던 최적화 배정(순열, 예: 1제대→목표2)이
입력과 상관없이 적용되어, 2제대 목표로 입력한 지점에 다른 제대가 갔다.
"""

import pytest
from httpx import AsyncClient

from app.simulation.presets import MODE_PRESETS
from app.simulation.real_runner import build_scenario

TARGETS = [(54.45, 18.40), (54.42, 18.36), (54.40, 18.50)]


def mission(targets, total=9, patrol=None):
    return {"targets": targets, "total_ugv": total, "duration_min": 60, "departure_lat": 54.48, "departure_lon": 18.32,
            "patrol_sec": patrol or [600] * len(targets)}


@pytest.mark.parametrize("mode", ["balance", "explore", "rush"])
def test_commander_targets_are_assigned_in_order_for_every_mode(mode):
    spec, _ = build_scenario(mission(TARGETS), mode, 0.3)
    assert spec.assignment == (0, 1, 2)                         # i제대 → 목표 i
    assert spec.formation == MODE_PRESETS[mode]["formation"]    # 편성(제대별 UGV 수)은 모드 프리셋을 그대로 쓴다


def test_each_team_dwell_time_follows_its_own_target():
    spec, _ = build_scenario(mission(TARGETS, patrol=[600, 1800, 3000]), "balance", 0.3)
    assert spec.dwell_turns == (1, 3, 5)


def test_default_targets_keep_the_optimized_assignment_of_the_mode():
    """목표를 입력하지 않으면 기본 목표(팀원 시나리오)로, 그 목표에 맞춰 최적화된 배정을 쓴다."""
    spec, _ = build_scenario({**mission([]), "targets": []}, "balance", 0.3)
    assert spec.assignment == MODE_PRESETS["balance"]["assignment"]


@pytest.mark.asyncio
async def test_replay_shows_each_team_at_the_target_entered_for_it(auth_client: AsyncClient, monkeypatch):
    monkeypatch.setenv("SIM_TICK_SLEEP", "0")
    monkeypatch.setenv("SIM_WEATHER_SCALE", "clear")
    mid = (await auth_client.post("/api/missions", json={
        "name": "배정 확인", "total_ugv": 9, "max_ugv_count": 9, "mission_duration_min": 240,
        "departure_lat": 54.48, "departure_lon": 18.32})).json()["id"]
    await auth_client.post(f"/api/missions/{mid}/targets", json=[
        {"seq": i + 1, "lat": lat, "lon": lon, "patrol_duration_sec": 600} for i, (lat, lon) in enumerate(TARGETS)])
    run_id = (await auth_client.post(f"/api/missions/{mid}/runs?mode=balanced")).json()["id"]
    await auth_client.post(f"/api/runs/{run_id}/start")
    per_team = (await auth_client.get(f"/api/runs/{run_id}/replay")).json()["mode"]["kpi"]["per_team"]
    reached = {t: v["poi"] for t, v in per_team.items() if v["poi"] is not None}      # 도착한 제대가 도착한 목표
    assert len(reached) >= 2
    assert all(reached[t] == {"Alpha": 1, "Bravo": 2, "Charlie": 3}[t] for t in reached), reached

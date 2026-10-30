"""
backend/app/tests/test_episode.py

에피소드 시뮬레이터 테스트. 저장소의 그단스크 20km 데이터를 사용한다.
각 에피소드는 수 초가 걸리므로 모듈 단위로 한 번만 실행해 여러 검증에 재사용한다.
"""

from collections import defaultdict

import numpy as np
import pytest

from app.simulation.algo.ap_resolver import AP_TURN, ap_orthogonal, resolve_critical_event, resolve_tile_entry
from app.simulation.algo.environment import Environment
from app.simulation.algo.episode import Genes, ScenarioSpec, run_episode
from app.simulation.algo.sim_config import SimAlgoConfig as Cfg

pytestmark = pytest.mark.skipif(
    Cfg.DATASET != "map_20km", reason="20km 데이터셋 기준 테스트 (SIM_DATASET=map_20km)"
)

SPEC = dict(
    start=(54.48, 18.32),
    pois=((54.40, 18.54), (54.33, 18.36), (54.37, 18.50)),
    formation=(2, 2, 2),
    assignment=(2, 0, 1),
)
SOS_ACTIONS = ("SOS_SENSOR", "SOS_MOBILITY", "SOS_COMPLEX_FAILURE")


@pytest.fixture(scope="module")
def env():
    e = Environment(Cfg())
    e.load_base_layer()
    e.load_all_data()
    return e


@pytest.fixture(scope="module")
def clear(env):
    return run_episode(env, ScenarioSpec(**SPEC, weather_scale=0.15), Genes(), seed=1)


# ── AP / 사고 규칙 ───────────────────────────────────────────────────────

def test_ap_formula_matches_the_reference_values():
    # 팀원 기록의 실제 AP 소모량 (대각선 이동)
    assert resolve_tile_entry(0.134932, 0.165485, True) == 121_701
    assert resolve_tile_entry(0.244569, 0.165485, True) == 132_312


def test_ap_grows_with_risk_and_diagonal_costs_more():
    assert ap_orthogonal(0.0, 0.0) == 80_000
    assert ap_orthogonal(1.0, 1.0) == 400_000
    assert resolve_tile_entry(0.5, 0.5, True) > resolve_tile_entry(0.5, 0.5, False)


def test_critical_event_probabilities_follow_the_risk():
    rng = np.random.default_rng(0)

    def hit_rate(risk):
        return sum(resolve_critical_event(risk, 0.0, rng) != "NORMAL" for _ in range(20_000)) / 20_000

    assert hit_rate(0.0) == 0.0
    assert hit_rate(1.0) == pytest.approx(0.20, abs=0.02)      # P_MAX_MOB
    assert hit_rate(0.5) == pytest.approx(0.05, abs=0.01)      # 위험도의 제곱에 비례


# ── 에피소드 불변식 ──────────────────────────────────────────────────────

def test_clear_weather_episode_completes(clear):
    m = clear.metrics
    assert m["completed"] and m["ugv_arrived"] == m["ugv_total"] == 6
    assert m["turns"] <= 24
    assert 0.0 < m["v1_coverage"] <= 1.0
    assert m["v2_minutes"] == m["turns"] * 10


def test_ugvs_end_on_their_assigned_poi(clear):
    targets = {"Alpha": clear.poi_cells[2], "Bravo": clear.poi_cells[0], "Charlie": clear.poi_cells[1]}
    last = {}
    for row in clear.log:
        last[row["agent_id"]] = (row["row"], row["col"])
    for agent, cell in last.items():
        if agent.startswith("UGV_"):
            assert cell == targets[agent.split("_")[1]], agent


def test_ap_never_goes_negative_and_never_increases_within_a_turn(clear):
    prev = defaultdict(lambda: None)
    for row in clear.log:
        if row["agent_id"].startswith("OP_"):
            continue
        assert row["ap"] >= 0
        key = (row["agent_id"], row["turn_idx"])
        if prev[key] is not None:
            assert row["ap"] <= prev[key], f"{key} AP 가 턴 안에서 늘어남"
        prev[key] = row["ap"]
    assert max(r["ap"] for r in clear.log) <= AP_TURN


def test_moves_are_single_adjacent_steps_on_passable_cells(clear, env):
    last = {}
    for row in clear.log:
        a = row["agent_id"]
        if a.startswith("OP_"):            # 운용자는 유인기에 탑승하므로 위치가 유인기를 따라간다
            continue
        cell = (row["row"], row["col"])
        if a in last:
            assert max(abs(cell[0] - last[a][0]), abs(cell[1] - last[a][1])) <= 1, a
        assert not env.blocked[cell], f"{a} 가 통행 불가 셀 {cell} 에 있음"
        last[a] = cell


def test_a_ugv_waiting_for_repair_stays_where_it_stopped(clear):
    last_cell = {}
    for row in clear.log:
        a = row["agent_id"]
        if not a.startswith("UGV_"):
            continue
        cell = (row["row"], row["col"])
        if row["action"] in ("SOS_WAIT", "BLIND"):      # 개입을 기다리는 동안에는 제자리
            assert cell == last_cell[a], f"{a} 가 대기 중에 이동함"
        last_cell[a] = cell


def test_every_intervention_targets_a_ugv_that_had_an_sos(clear):
    sos_seen = set()
    for row in clear.log:
        if row["action"] in SOS_ACTIONS:
            sos_seen.add(row["agent_id"])
        if row["action"].startswith("INTERVENE->"):
            assert row["action"].split("->")[1] in sos_seen


def test_ugvs_stay_within_communication_range_of_their_manned_vehicle(clear):
    manned = {team: clear.start_cell for team in clear.teams}   # 유인기는 출발 셀에서 시작
    worst = 0.0
    for row in clear.log:
        a = row["agent_id"]
        if a.startswith("Manned_"):
            manned[a.split("_")[1]] = (row["row"], row["col"])
        elif a.startswith("UGV_") and row["action"] == "MISSION":
            m = manned[a.split("_")[1]]
            worst = max(worst, np.hypot(row["row"] - m[0], row["col"] - m[1]) * 0.2)
    assert worst < 2.2, f"통신 한계(1.8km)를 크게 넘음: {worst:.2f}km"


def test_metrics_agree_with_the_log(clear):
    sos_rows = sum(1 for r in clear.log if r["action"] in SOS_ACTIONS)
    interventions = sum(1 for r in clear.log if r["action"].startswith("INTERVENE->"))
    arrived = len({r["agent_id"] for r in clear.log if r["agent_id"].startswith("UGV_") and r["action"] == "ARRIVED"})
    assert clear.metrics["sos_events"] == sos_rows
    assert clear.metrics["interventions"] == interventions
    assert clear.metrics["ugv_arrived"] == arrived


def test_same_seed_gives_identical_results_and_other_seeds_differ(env, clear):
    again = run_episode(env, ScenarioSpec(**SPEC, weather_scale=0.15), Genes(), seed=1)
    assert again.log == clear.log
    other = run_episode(env, ScenarioSpec(**SPEC, weather_scale=0.15, max_turns=8), Genes(), seed=2)
    assert other.log != clear.log[: len(other.log)]


def test_harsher_weather_causes_more_sos(env):
    def total_sos(scale):
        return sum(
            run_episode(env, ScenarioSpec(**SPEC, weather_scale=scale, max_turns=10), Genes(), seed=s).metrics["sos_events"]
            for s in (1, 2)
        )

    assert total_sos(0.6) > total_sos(0.15)


def test_launch_delay_postpones_a_team(env):
    r = run_episode(env, ScenarioSpec(**SPEC, weather_scale=0.15, max_turns=4), Genes(launch_delay=(0, 0, 3)), seed=1)
    first_move = {}
    for row in r.log:
        if row["agent_id"].startswith("UGV_") and row["action"] == "MISSION":
            first_move.setdefault(row["agent_id"].split("_")[1], row["turn_idx"])
    assert first_move["Charlie"] >= 3 > first_move["Alpha"]


# ── 재생 데이터 변환 ─────────────────────────────────────────────────────

def test_replay_kpis_agree_with_engine_metrics(clear):
    from app.simulation.replay import build_mode, log_to_frame

    data = build_mode(log_to_frame(clear.log), "balance", "균형", clear.poi_cells)
    k, m = data["kpi"], clear.metrics
    assert k["ugv_arrived"] == m["ugv_arrived"]
    assert k["sos_events"] == m["sos_events"]          # 수리 직후 재고장도 별개로 센다
    assert k["interventions"] == m["interventions"]
    assert len(data["steps"]) == len(clear.log)
    assert set(data["columns"]) >= {"turn", "seq", "agent", "lat", "lon", "action", "grade"}


# ── 정찰(체류) 시간 ──────────────────────────────────────────────────────

def test_patrol_time_extends_the_mission_after_arrival(env, clear):
    dwell = run_episode(env, ScenarioSpec(**SPEC, weather_scale=0.15, dwell_turns=(2, 2, 2)), Genes(), seed=1)
    assert dwell.metrics["completed"]
    assert dwell.metrics["turns"] == clear.metrics["turns"] + 2    # 같은 시드 → 도착까지는 같고, 마지막 제대가 2턴 더 머문다
    patrol = [r for r in dwell.log if r["action"] == "PATROL"]
    assert patrol and all(r["agent_id"].startswith("UGV_") for r in patrol)
    # 정찰 중인 UGV 는 정찰지에 머무른다
    targets = {"Alpha": dwell.poi_cells[2], "Bravo": dwell.poi_cells[0], "Charlie": dwell.poi_cells[1]}
    assert all((r["row"], r["col"]) == targets[r["agent_id"].split("_")[1]] for r in patrol)


# ── 지도 기동성 레이어 ──────────────────────────────────────────────────

def test_mobility_layer_gets_harder_with_higher_terrain_cost():
    from app.services.tactical_map_service import _make_mobility_layer
    from app.simulation.terrain import BLOCKED_COST

    terrain = np.array([[1.0, 1.1, 1.5, BLOCKED_COST]], dtype=np.float32)
    values = {c.col: c.value for c in _make_mobility_layer(terrain).cells}
    assert values[3] == 1.0                              # 통행 불가 = 가장 어려움
    assert values[0] < values[1] < values[2] < values[3]  # 예전에는 반대로 비용이 높을수록 값이 낮았다

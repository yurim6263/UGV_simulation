"""
backend/app/tests/test_optimize.py

NSGA-II 최적화 / 몬테카를로 검증 테스트.
최적화 실행 테스트는 아주 작은 예산(개체 4, 2세대, 시나리오 1개)으로 돌린다.
"""

import numpy as np
import pytest

from app.simulation.algo.episode import Genes, ScenarioSpec
from app.simulation.algo.sim_config import SimAlgoConfig as Cfg
from app.simulation.optimize import (
    PERMUTATIONS, EvalPlan, _repair_formation, aggregate, decode, encode, gene_specs, monte_carlo,
    run_nsga2, select_archetypes,
)
from app.simulation.presets import DEFAULT_POIS, DEFAULT_START, MODE_PRESETS, REFERENCE_PRESETS, load_optimized

BASE = ScenarioSpec(start=DEFAULT_START, pois=DEFAULT_POIS, weather_scale=0.3, max_turns=4)
needs_data = pytest.mark.skipif(Cfg.DATASET != "map_20km", reason="20km 데이터셋 기준 테스트")


# ── 유전자 해석 ──────────────────────────────────────────────────────────

def test_every_random_vector_decodes_to_a_valid_force_structure():
    specs = gene_specs()
    xl = np.array([g.low for g in specs])
    xu = np.array([g.high for g in specs])
    rng = np.random.default_rng(0)
    for x in rng.uniform(xl, xu, size=(300, len(specs))):
        spec, genes, vals = decode(x, 9, BASE)
        assert sum(spec.formation) == 9 and all(2 <= n <= 5 for n in spec.formation)
        assert sorted(spec.assignment) == [0, 1, 2]                      # 각 제대가 서로 다른 정찰지로
        assert genes.recall_km > genes.hold_km >= genes.resume_km        # 목줄 임계값의 순서
        assert all(d in range(5) for d in genes.launch_delay)
        assert 0 <= genes.dispersion_weight <= 3 and 0 <= genes.weather_sensitivity <= 2


def test_frozen_genes_override_the_search_vector():
    specs = gene_specs()
    x = np.array([g.high for g in specs])
    _, genes, vals = decode(x, 9, BASE, frozen={"dispersion_weight": 0.0, "launch_delay_1": 2, "perm": 3})
    assert genes.dispersion_weight == 0.0 and genes.launch_delay[0] == 2
    assert vals["perm"] == 3


def test_repair_keeps_the_total_and_rejects_impossible_totals():
    assert _repair_formation(5, 5, 9, 2, 5) == (4, 3, 2) or sum(_repair_formation(5, 5, 9, 2, 5)) == 9
    assert _repair_formation(2, 2, 9, 2, 5) == (3, 2, 4) or sum(_repair_formation(2, 2, 9, 2, 5)) == 9
    for u1 in range(2, 6):
        for u2 in range(2, 6):
            a, b, c = _repair_formation(u1, u2, 9, 2, 5)
            assert a + b + c == 9 and all(2 <= n <= 5 for n in (a, b, c))
    with pytest.raises(ValueError):
        _repair_formation(2, 2, 20, 2, 5)


def test_presets_round_trip_through_encode_and_decode():
    for mode, p in REFERENCE_PRESETS.items():
        spec = ScenarioSpec(start=DEFAULT_START, pois=DEFAULT_POIS, formation=p["formation"], assignment=p["assignment"])
        out_spec, out_genes, _ = decode(encode(spec, p["genes"]), 9, BASE)
        assert out_spec.formation == p["formation"] and out_spec.assignment == p["assignment"], mode
        assert out_genes.dispersion_weight == pytest.approx(p["genes"].dispersion_weight)
        assert out_genes.hold_km == pytest.approx(p["genes"].hold_km)
    assert len(PERMUTATIONS) == 6


# ── 집계와 대표 전술 선택 ────────────────────────────────────────────────

def _m(arrival, v1, v2, v3, completed=True):
    return {"arrival_rate": arrival, "v1_coverage": v1, "v2_minutes": v2, "v3_overload_minutes": v3,
            "completed": completed, "sos_events": 10}


def test_aggregate_reports_mean_and_the_bad_tail():
    metrics = [_m(1.0, 0.5, 200, 0)] * 90 + [_m(0.2, 0.3, 240, 60, False)] * 10    # 10% 가 크게 실패
    agg = aggregate(metrics)
    assert agg["arrival"] == pytest.approx(0.92)
    assert agg["arrival_p5"] == pytest.approx(0.2)       # 평균(92%)은 괜찮아 보여도 하위 5% 는 실패 구간이다
    assert agg["v2_p95"] >= agg["v2"]


def test_archetypes_pick_fastest_widest_and_knee():
    front = [
        {"validation": {"v1": 0.30, "v2": 150, "v3": 10}},   # 가장 빠름
        {"validation": {"v1": 0.60, "v2": 230, "v3": 40}},   # 가장 넓게 훑음
        {"validation": {"v1": 0.52, "v2": 175, "v3": 15}},   # 균형 (무릎점)
        {"validation": {"v1": 0.35, "v2": 200, "v3": 50}},   # 열등
    ]
    chosen = select_archetypes(front, key="validation")
    assert chosen == {"balance": 2, "rush": 0, "explore": 1}


def test_archetypes_stay_distinct_and_work_for_tiny_fronts():
    one = select_archetypes([{"validation": {"v1": 0.5, "v2": 200, "v3": 10}}], key="validation")
    assert set(one) == {"balance", "rush", "explore"} and set(one.values()) == {0}
    two = select_archetypes([{"validation": {"v1": 0.3, "v2": 150, "v3": 5}}, {"validation": {"v1": 0.6, "v2": 240, "v3": 30}}], key="validation")
    assert two["rush"] != two["explore"]
    assert select_archetypes([]) == {}


# ── 최적화 실행 (작은 예산) ──────────────────────────────────────────────

PLAN = EvalPlan(scales=(0.15,), seeds=(1,), max_turns=3)


@needs_data
def test_nsga2_runs_and_returns_a_non_dominated_front_with_frozen_genes_fixed():
    result = run_nsga2(BASE, total_ugv=6, plan=PLAN, pop_size=4, generations=2, seed=3, min_arrival=0.0,
                       frozen={"perm": 1, "dispersion_weight": 0.5}, workers=2)
    assert result.front and len(result.history) == 2 and result.history[-1]["evals"] >= 4
    for item in result.front:
        assert item["values"]["perm"] == 1 and item["values"]["dispersion_weight"] == 0.5
        assert sum(item["values"][f"ugv_{i}"] for i in (1, 2, 3)) == 6
    objs = np.array([[-f["train"]["v1"], f["train"]["v2"], f["train"]["v3"]] for f in result.front])
    for i in range(len(objs)):                                       # 서로 지배하지 않는다
        for j in range(len(objs)):
            if i != j:
                assert not (np.all(objs[j] <= objs[i]) and np.any(objs[j] < objs[i]))


@needs_data
def test_nsga2_is_reproducible_for_the_same_seed():
    kw = dict(base=BASE, total_ugv=6, plan=PLAN, pop_size=4, generations=1, seed=5, min_arrival=0.0, workers=2)
    a, b = run_nsga2(**kw), run_nsga2(**kw)
    assert [f["x"] for f in a.front] == [f["x"] for f in b.front]


@needs_data
def test_infeasible_constraint_still_returns_least_violating_solutions():
    result = run_nsga2(BASE, total_ugv=6, plan=PLAN, pop_size=4, generations=1, seed=1, min_arrival=1.5, workers=2)
    assert not result.feasible and result.front                       # 도착률 150% 는 불가능 → 위반이 가장 작은 해


@needs_data
def test_monte_carlo_reports_confidence_intervals():
    spec, genes, _ = decode(encode(ScenarioSpec(start=DEFAULT_START, pois=DEFAULT_POIS, formation=(2, 2, 2), assignment=(2, 0, 1)), Genes()), 6, BASE)
    out = monte_carlo(spec, genes, scales=(0.15,), seeds=(1, 2, 3), workers=2)
    assert out["n"] == 3 and out["arrival_ci95"] >= 0 and out["v2_ci95"] >= 0
    assert out["arrival_p5"] <= out["arrival"]


# ── 최적화 결과 → 서버 프리셋 ────────────────────────────────────────────

def test_optimized_archetypes_replace_reference_presets(tmp_path):
    import json

    front = [
        {"formation": [3, 3, 3], "assignment": [0, 1, 2],
         "genes": {"launch_delay": [0, 1, 0], "dispersion_weight": 0.4, "weather_sensitivity": 0.7,
                   "hold_km": 1.4, "recall_km": 1.8, "resume_km": 1.1}},
        {"formation": [2, 3, 4], "assignment": [2, 1, 0],
         "genes": {"launch_delay": [0, 0, 0], "dispersion_weight": 2.0, "weather_sensitivity": 1.5,
                   "hold_km": 1.2, "recall_km": 1.6, "resume_km": 0.9}},
    ]
    path = tmp_path / "pareto.json"
    path.write_text(json.dumps({"front": front, "archetypes": {"rush": 0, "explore": 1}}), encoding="utf-8")
    loaded = load_optimized(path)
    assert set(loaded) == {"rush", "explore"}                       # 선택된 원형만 덮어쓴다
    assert loaded["rush"]["formation"] == (3, 3, 3) and loaded["rush"]["source"] == "nsga2"
    assert loaded["explore"]["genes"].dispersion_weight == 2.0
    assert loaded["explore"]["genes"].launch_delay == (0, 0, 0)
    assert load_optimized(tmp_path / "missing.json") == {}          # 파일이 없으면 기준 프리셋을 그대로 쓴다


def test_every_server_preset_is_a_valid_scenario():
    for mode, p in MODE_PRESETS.items():
        assert sum(p["formation"]) == 9 and sorted(p["assignment"]) == [0, 1, 2], mode
        assert p["genes"].recall_km > p["genes"].hold_km >= p["genes"].resume_km, mode


@needs_data
def test_validating_many_tactics_in_one_batch_matches_validating_them_one_by_one():
    from app.simulation.optimize import monte_carlo_many, validate_front

    specs = gene_specs()
    xs = [encode(ScenarioSpec(start=DEFAULT_START, pois=DEFAULT_POIS, formation=f, assignment=(2, 0, 1)), Genes())
          for f in ((2, 2, 2), (3, 2, 1))]
    front = [{"x": [float(v) for v in x]} for x in xs]
    validate_front(front, 6, BASE, scales=(0.15,), seeds=(1, 2), workers=2)
    for item, x in zip(front, xs):
        spec, genes, _ = decode(x, 6, BASE, specs)
        alone = monte_carlo(spec, genes, scales=(0.15,), seeds=(1, 2), workers=2)
        assert item["validation"] == alone
    assert len(monte_carlo_many([], scales=(0.15,), seeds=(1,), workers=1)) == 0


def test_archetypes_are_chosen_from_optimization_values_not_validation_values():
    """검증 값으로 고르면, 같은 값으로 성능을 보고할 때 '잘 나온 것만 고른' 낙관 편향이 생긴다."""
    front = [
        {"train": {"v1": 0.30, "v2": 150, "v3": 10}, "validation": {"v1": 0.30, "v2": 400, "v3": 10}},   # 최적화에선 가장 빠름
        {"train": {"v1": 0.60, "v2": 230, "v3": 40}, "validation": {"v1": 0.60, "v2": 230, "v3": 40}},
        {"train": {"v1": 0.52, "v2": 175, "v3": 15}, "validation": {"v1": 0.52, "v2": 100, "v3": 15}},   # 검증에선 가장 빠름
    ]
    assert select_archetypes(front)["rush"] == 0                          # 기본값(train): 검증 값이 좋아 보여도 고르지 않는다
    by_validation = select_archetypes(front, key="validation")      # 균형이 2번(이상점에 가장 가까움)을 먼저 가져가므로 신속은 1번으로 밀린다
    assert by_validation["rush"] != select_archetypes(front)["rush"]   # 선택 기준에 따라 대표 전술이 달라진다

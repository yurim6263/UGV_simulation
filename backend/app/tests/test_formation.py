"""
backend/app/tests/test_formation.py

편성 계산기 테스트. 합성/선택 규칙은 손으로 만든 값으로 정확히 검증하고,
엔진 연결은 작은 시나리오로 확인한다 (합성이 직접 시뮬레이션과 맞는지 포함).
"""

import numpy as np
import pytest
from dataclasses import replace
from types import SimpleNamespace

from app.simulation.batch import Job, run_batch
from app.simulation.formation import (
    MODES, PlanInput, choose, compose, evaluate, mark_pareto, plan_formations,
)
from app.simulation.presets import DEFAULT_POIS, DEFAULT_START, preset

CELLS = 6


def fake(ugv, arrived, v2, sos, overload, seen_cells, interventions=0, valid=36):
    seen = np.zeros(CELLS * CELLS, dtype=bool)
    seen[list(seen_cells)] = True
    return SimpleNamespace(
        metrics={"ugv_total": ugv, "ugv_arrived": arrived, "v2_minutes": v2, "sos_events": sos, "interventions": interventions},
        detail={"seen": seen.reshape(CELLS, CELLS), "overload_turns": list(overload), "valid_cells": valid},
    )


def inp(**kw):
    base = dict(start=DEFAULT_START, targets=DEFAULT_POIS[:2], patrol_sec=(600, 600), duration_min=240, weather_scale=0.3, seeds=(1, 2))
    return PlanInput(**{**base, **kw})


# ── 입력 ─────────────────────────────────────────────────────────────────

def test_formation_candidates_follow_team_count_and_range():
    assert len(PlanInput(DEFAULT_START, DEFAULT_POIS, (600,) * 3, 240, 0.3).formations()) == 27
    assert len(inp().formations()) == 9 and (1, 3) in inp().formations() and (0, 1) not in inp().formations() and (4, 1) not in inp().formations()
    assert inp(targets=DEFAULT_POIS[:1], patrol_sec=(600,)).formations() == [(1,), (2,), (3,)]


def test_cache_key_is_stable_and_changes_with_every_input_that_matters():
    a = inp()
    assert a.cache_key() == inp().cache_key()
    for changed in (inp(weather_scale=0.15), inp(duration_min=180), inp(seeds=(1, 2, 3)), inp(patrol_sec=(600, 1200)),
                    inp(start=(54.47, 18.32)), inp(targets=(DEFAULT_POIS[0], (54.34, 18.36))), inp(max_per_team=2)):
        assert changed.cache_key() != a.cache_key()


# ── 합성 ─────────────────────────────────────────────────────────────────

def test_compose_sums_arrivals_takes_slowest_team_and_unions_coverage_and_overload():
    i = inp(seeds=(1,))
    records = {
        ("balance", 0, 2, 1): fake(ugv=2, arrived=2, v2=100, sos=1, overload=[3, 4], seen_cells=[0, 1, 2, 3], interventions=1),
        ("balance", 1, 1, 1): fake(ugv=1, arrived=0, v2=240, sos=2, overload=[4, 5], seen_cells=[2, 3, 4], interventions=2),
    }
    c = compose(records, i, "balance", (2, 1))
    assert c["total"] == 3 and c["formation"] == [2, 1]
    assert c["arrival"] == pytest.approx(2 / 3, abs=1e-3)               # 도착 합 / UGV 합
    assert c["v2"] == 240                                              # 가장 늦은 제대
    assert c["v1"] == pytest.approx(5 / 36, abs=1e-4)                  # 칸 {0,1,2,3} ∪ {2,3,4} = 5칸 (겹치는 칸은 한 번만)
    assert c["v3"] == 30                                               # 과부하 턴 {3,4,5} = 3턴 x 10분 (겹치는 턴은 한 번만)
    assert c["sos"] == 3 and c["interventions"] == 3


def test_compose_averages_over_seeds_and_reports_spread():
    i = inp(seeds=(1, 2))
    records = {}
    for s, v2 in ((1, 100), (2, 200)):
        records[("balance", 0, 1, s)] = fake(1, 1, v2, 0, [], [0])
        records[("balance", 1, 1, s)] = fake(1, 1, 50, 0, [], [1])
    c = compose(records, i, "balance", (1, 1))
    assert c["v2"] == 150 and c["v2_sd"] == pytest.approx(70.7, abs=0.1) and c["seeds"] == 2


# ── 모드별 선택 ──────────────────────────────────────────────────────────

def cand(formation, arrival=1.0, v1=0.4, v2=200, v3=0, sos=0.0):
    return {"formation": list(formation), "total": sum(formation), "arrival": arrival, "v1": v1, "v2": v2, "v3": v3, "sos": sos}


CANDS = [
    cand((1, 1, 1), v1=0.36, v2=150, sos=3),
    cand((2, 2, 2), v1=0.46, v2=180, v3=5, sos=6),
    cand((3, 3, 3), v1=0.50, v2=200, v3=25, sos=12),
    cand((3, 3, 2), v1=0.495, v2=198, v3=20, sos=10),                  # (3,3,3) 와 수색 차이 0.5%p: 동률권
    cand((1, 1, 2), arrival=0.5, v1=0.60, v2=100),             # 제약(도착률 80%) 미달: 좋아 보여도 고르지 않는다
]


def test_explore_maximizes_coverage_among_feasible_and_prefers_fewer_ugvs_when_tied():
    pick = choose(CANDS, "explore")
    assert pick["formation"] == [3, 3, 2] and pick["constraint_met"]      # 0.50 과 0.495 는 동률 → UGV 8대 < 9대


def test_rush_minimizes_time_among_feasible():
    assert choose(CANDS, "rush")["formation"] == [1, 1, 1]                # 도착률 미달인 (1,1,2) 는 제외


def test_balance_takes_90_percent_of_the_best_coverage_with_the_least_operator_burden():
    pick = choose(CANDS, "balance")
    assert pick["formation"] == [2, 2, 2]                                  # 수색 0.45 이상(최대 0.50 의 90%): (2,2,2) (3,3,2) (3,3,3) 중 과부하가 가장 낮은 것
    assert "90%" in pick["reason"]


def test_balance_ignores_candidates_below_the_coverage_bar_even_if_their_burden_is_lowest():
    assert choose(CANDS, "balance")["formation"] != [1, 1, 1]              # (1,1,1) 은 부담이 가장 낮지만 수색이 0.36 으로 기준 미달


def test_balance_is_not_a_copy_of_explore_when_the_top_candidates_are_close():
    near = [cand((3, 3, 1), v1=0.492, v3=15, sos=13.8), cand((2, 1, 2), v1=0.446, v3=0, sos=8.5), cand((2, 1, 1), v1=0.394, v3=0, sos=7.2)]
    assert choose(near, "explore")["formation"] == [3, 3, 1]
    assert choose(near, "balance")["formation"] == [2, 1, 2]


def test_modes_differ_on_a_realistic_table():
    picks = {m: tuple(choose(CANDS, m)["formation"]) for m in MODES}
    assert len(set(picks.values())) == 3


def test_when_no_candidate_meets_the_arrival_constraint_it_falls_back_and_says_so():
    weak = [cand((1, 1), arrival=0.5, v1=0.3), cand((2, 2), arrival=0.7, v1=0.4), cand((3, 3), arrival=0.7, v1=0.5)]
    pick = choose(weak, "explore")
    assert pick["constraint_met"] is False and "만족하는 편성이 없어" in pick["reason"]
    assert pick["formation"] in ([3, 3], [2, 2]) and pick["formation"] != [1, 1]          # 도착률이 가장 높은 후보들 중에서


def test_pareto_marks_candidates_not_dominated_by_another():
    cs = [cand((1, 1), v1=0.3, v2=100, v3=0), cand((2, 2), v1=0.5, v2=150, v3=0), cand((3, 3), v1=0.4, v2=200, v3=30)]
    mark_pareto(cs)
    assert [c["pareto"] for c in cs] == [True, True, False]               # (3,3) 은 (2,2) 에 모든 면에서 밀린다


# ── 엔진 연결 ────────────────────────────────────────────────────────────

def test_single_target_plan_is_deterministic_and_well_formed():
    i = inp(targets=DEFAULT_POIS[:1], patrol_sec=(600,), seeds=(7,))
    a = plan_formations(i, workers=1)
    b = plan_formations(i, workers=1)
    assert a["modes"] == b["modes"]                                      # 같은 입력 → 같은 결과
    assert a["episodes"] == 3 * 1 * 3 * 1 and a["cache_key"] == i.cache_key()
    for m in MODES:
        cands = a["modes"][m]["candidates"]
        assert [c["formation"] for c in cands] == [[1], [2], [3]]
        assert a["modes"][m]["pick"]["formation"] in [c["formation"] for c in cands]
        assert all(0 <= c["arrival"] <= 1 and 0 <= c["v1"] <= 1 for c in cands)


def test_progress_callback_reports_every_episode():
    seen = []
    i = inp(targets=DEFAULT_POIS[:1], patrol_sec=(600,), seeds=(7,))
    evaluate(i, ("balance",), workers=1, on_progress=lambda done, total: seen.append((done, total)))
    assert seen == [(1, 3), (2, 3), (3, 3)]


def test_composition_matches_direct_simulation_for_coverage_and_arrival():
    """제대 합성이 3제대를 직접 돌린 값과 맞는다 (수색 면적은 잡음이 작아 엄격하게, 나머지는 큰 어긋남이 없는지만)."""
    i = inp(seeds=(11, 12, 13))
    records = evaluate(i, ("balance",), workers=1)
    composed = compose(records, i, "balance", (2, 2))
    spec, genes = preset("balance", weather_scale=0.3, max_turns=24, start=DEFAULT_START, pois=DEFAULT_POIS[:2])
    spec = replace(spec, formation=(2, 2), assignment=(0, 1), dwell_turns=(1, 1))
    direct = run_batch([Job(spec, genes, s) for s in (21, 22, 23)], workers=1)
    d_cov = np.mean([r.metrics["v1_coverage"] for r in direct])
    d_arr = np.mean([r.metrics["arrival_rate"] for r in direct])
    assert abs(composed["v1"] - d_cov) < 0.04
    assert abs(composed["arrival"] - d_arr) < 0.35

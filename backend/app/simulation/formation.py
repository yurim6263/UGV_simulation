"""
backend/app/simulation/formation.py

편성 계산기: 지휘관이 정한 목표(위치)에서 제대마다 UGV 몇 대를 투입할지(1~3대) 시뮬레이션으로 계산한다.

기상과 거리를 따로 계산하지 않는다. 엔진(algo/episode.py)이 위험도 지도와 거리를 이미 반영하므로, 후보 편성을 엔진으로 돌려 비교한다.

계산량을 줄이는 방법 (제대들이 서로 독립이라는 성질을 쓴다)
  제대 하나를 따로 시험한다: "제대 i 가 목표 i 로 UGV n 대를 보낼 때" (제대 3 x n 3 x 시드 S 회).
  엔진에서 제대 사이에 공유되는 것은 난수 순서와 결과 집계뿐이다 (경로 분산 페널티, 운용자, 이동이 제대별이다).
  그래서 편성 (a, b, c) 의 결과는 제대별 결과를 합쳐서 얻는다:
    도착·SOS·개입  = 제대별 합           작전 시간 = 가장 늦게 끝난 제대
    수색 면적      = 수색한 칸의 합집합   운용자 과부하 = 과부하였던 턴의 합집합
  27가지를 전부 직접 돌리는 것보다 수 배 빠르다. 합성이 직접 시뮬레이션과 맞는지는 tests/test_formation.py 가 확인한다.

모드는 "무엇을 우선하나"만 정한다 (choose):
  정밀(explore) 도착률 80% 이상 중 수색 면적 최대      신속(rush) 도착률 80% 이상 중 작전 시간 최소
  균형(balance) 도착률 80% 이상 중 "수색 손해 + 부담(시간·과부하 평균) 손해"가 최소 (손해 = 최선값과의 차이를 범위로 나눈 값)
  차이가 우연 수준(수색 1%p, 시간 5분 이내)이면 UGV 가 적은 편성을 고른다.
모드의 전술 성향(산개, 기상 민감도, 목줄 거리)은 presets.py 의 값을 쓴다 (모드마다 따로 시험한다).

한계: 시뮬레이션 추정이고 시드가 적어(기본 4개) 근소한 차이는 구분되지 않는다. "최적"은 이 추정에서 가장 좋다는 뜻이다.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import time
from dataclasses import dataclass, replace

import numpy as np

from app.simulation.algo.episode import Genes, ScenarioSpec
from app.simulation.batch import Job, run_batch
from app.simulation.presets import MODE_PRESETS, preset

PLANNER_VERSION = 1
MODES = ("balance", "explore", "rush")
MIN_PER_TEAM, MAX_PER_TEAM = 1, 3
MIN_ARRIVAL = 0.8
SEEDS = (1001, 1002, 1003, 1004)
TIE_COVERAGE = 0.01          # 수색 비율 차이가 이 이하면 동률
TIE_MINUTES = 5              # 작전 시간 차이가 이 이하(분)면 동률


@dataclass(frozen=True)
class PlanInput:
    start: tuple
    targets: tuple                      # ((lat, lon), ...) 제대 순서 (목표 i 는 i제대)
    patrol_sec: tuple                   # 목표별 정찰(체류) 시간(초)
    duration_min: int
    weather_scale: float
    seeds: tuple = SEEDS
    min_per_team: int = MIN_PER_TEAM
    max_per_team: int = MAX_PER_TEAM
    min_arrival: float = MIN_ARRIVAL

    @property
    def n_teams(self) -> int:
        return len(self.targets)

    @property
    def max_turns(self) -> int:
        return max(6, min(31, self.duration_min // 10))

    def formations(self) -> list[tuple]:
        return list(itertools.product(range(self.min_per_team, self.max_per_team + 1), repeat=self.n_teams))

    def cache_key(self) -> str:
        """같은 입력이면 같은 키. 계산 결과(편성 후보)를 다시 쓸 수 있는지 판단한다."""
        genes = {m: repr(MODE_PRESETS[m]["genes"]) for m in MODES}
        payload = {
            "v": PLANNER_VERSION, "start": [round(x, 5) for x in self.start],
            "targets": [[round(x, 5) for x in t] for t in self.targets], "patrol": list(self.patrol_sec),
            "duration": self.duration_min, "scale": round(self.weather_scale, 4), "seeds": list(self.seeds),
            "range": [self.min_per_team, self.max_per_team], "min_arrival": self.min_arrival, "genes": genes,
        }
        return hashlib.sha1(json.dumps(payload, sort_keys=True).encode()).hexdigest()


# ── 제대 하나를 따로 시험 ────────────────────────────────────────────────

def team_job(inp: PlanInput, mode: str, team: int, n: int, seed: int) -> Job:
    """제대 team(0부터)이 목표 team 으로 UGV n 대를 보내는 단독 에피소드."""
    spec, genes = preset(mode, weather_scale=inp.weather_scale, max_turns=inp.max_turns, start=inp.start, pois=(inp.targets[team],))
    delays = genes.launch_delay
    spec = replace(spec, formation=(n,), assignment=(0,), dwell_turns=(math.ceil(inp.patrol_sec[team] / 600),))
    genes = replace(genes, launch_delay=(delays[team] if team < len(delays) else 0,))
    return Job(spec, genes, seed * 10 + team)          # 제대마다 다른 난수 (같은 난수를 쓰면 제대 사이에 가짜 상관이 생긴다)


def evaluate(inp: PlanInput, modes=MODES, workers: int | None = None, on_progress=None) -> dict:
    """모든 (모드, 제대, 대수, 시드) 단독 에피소드를 돌려 {(mode, team, n, seed): BatchResult} 를 돌려준다."""
    keys = [(m, t, n, s) for m in modes for t in range(inp.n_teams)
            for n in range(inp.min_per_team, inp.max_per_team + 1) for s in inp.seeds]
    jobs = [team_job(inp, *k) for k in keys]
    results = run_batch(jobs, workers=workers, keep_detail=True, on_progress=on_progress)
    return dict(zip(keys, results))


# ── 합성 ─────────────────────────────────────────────────────────────────

def compose(records: dict, inp: PlanInput, mode: str, formation: tuple) -> dict:
    """제대별 단독 결과를 합쳐 편성 하나의 평균 지표를 만든다 (시드별로 합친 뒤 평균)."""
    per_seed = []
    for s in inp.seeds:
        parts = [records[(mode, t, n, s)] for t, n in enumerate(formation)]
        ugv = sum(p.metrics["ugv_total"] for p in parts)
        seen = np.zeros_like(parts[0].detail["seen"])
        overload: set[int] = set()
        for p in parts:
            seen |= p.detail["seen"]
            overload.update(p.detail["overload_turns"])
        valid = parts[0].detail["valid_cells"]
        per_seed.append({
            "arrival": sum(p.metrics["ugv_arrived"] for p in parts) / ugv,
            "v1": float(seen.sum() / max(1, valid)),
            "v2": max(p.metrics["v2_minutes"] for p in parts),
            "v3": 10 * len(overload),
            "sos": sum(p.metrics["sos_events"] for p in parts),
            "interventions": sum(p.metrics["interventions"] for p in parts),
        })
    mean = lambda k: float(np.mean([x[k] for x in per_seed]))  # noqa: E731
    sd = lambda k: float(np.std([x[k] for x in per_seed], ddof=1)) if len(per_seed) > 1 else 0.0  # noqa: E731
    return {
        "formation": list(formation), "total": sum(formation),
        "arrival": round(mean("arrival"), 3), "v1": round(mean("v1"), 4), "v2": round(mean("v2"), 1), "v3": round(mean("v3"), 1),
        "sos": round(mean("sos"), 1), "interventions": round(mean("interventions"), 1),
        "v1_sd": round(sd("v1"), 4), "v2_sd": round(sd("v2"), 1), "seeds": len(per_seed),
    }


def mark_pareto(cands: list[dict]) -> None:
    """수색 최대, 시간·과부하·UGV 수 최소 기준으로 다른 편성에 모든 면에서 밀리지 않는 후보를 표시한다."""
    def dominates(a, b):
        no_worse = a["v1"] >= b["v1"] and a["v2"] <= b["v2"] and a["v3"] <= b["v3"] and a["total"] <= b["total"]
        better = a["v1"] > b["v1"] or a["v2"] < b["v2"] or a["v3"] < b["v3"] or a["total"] < b["total"]
        return no_worse and better

    for c in cands:
        c["pareto"] = not any(dominates(o, c) for o in cands if o is not c)


# ── 모드별 선택 ──────────────────────────────────────────────────────────

REASON = {
    "explore": "도착률 {a:.0f}% 이상인 {k}개 중 수색 면적이 가장 큰 편성 (동률권 {t}개 중 UGV가 가장 적은 것)",
    "rush": "도착률 {a:.0f}% 이상인 {k}개 중 작전 시간이 가장 짧은 편성 (동률권 {t}개 중 UGV가 가장 적은 것)",
    "balance": "도착률 {a:.0f}% 이상인 {k}개 중 수색 면적의 손해와 부담(작전 시간·운용자 과부하의 평균 손해)의 합이 가장 작은 편성",
}


def choose(cands: list[dict], mode: str, min_arrival: float = MIN_ARRIVAL) -> dict:
    """모드의 우선순위로 편성 하나를 고른다. 도착률 제약을 만족하는 후보가 없으면 도착률이 가장 높은 후보 중에서 고른다."""
    feasible = [c for c in cands if c["arrival"] >= min_arrival]
    met = bool(feasible)
    pool = feasible or [c for c in cands if c["arrival"] == max(x["arrival"] for x in cands)]
    if mode == "explore":
        best = max(c["v1"] for c in pool)
        tied = [c for c in pool if c["v1"] >= best - TIE_COVERAGE]
        pick = min(tied, key=lambda c: (c["total"], c["v2"], -c["v1"]))
    elif mode == "rush":
        best = min(c["v2"] for c in pool)
        tied = [c for c in pool if c["v2"] <= best + TIE_MINUTES]
        pick = min(tied, key=lambda c: (c["total"], -c["v1"]))
    else:
        rng = lambda k: max(1e-9, max(c[k] for c in pool) - min(c[k] for c in pool))  # noqa: E731
        r1, r2, r3 = rng("v1"), rng("v2"), rng("v3")
        v1max, v2min, v3min = max(c["v1"] for c in pool), min(c["v2"] for c in pool), min(c["v3"] for c in pool)
        # 이득(수색)과 부담(시간·운용자 과부하의 평균)을 같은 비중으로 본다. 세 지표를 따로 더하면 부담이 둘이라
        # 작은 편성이 유리해져 균형이 신속과 같은 편성을 고른다.
        regret = lambda c: (v1max - c["v1"]) / r1 + ((c["v2"] - v2min) / r2 + (c["v3"] - v3min) / r3) / 2  # noqa: E731
        tied = pool
        pick = min(pool, key=lambda c: (round(regret(c), 6), c["total"]))
    reason = REASON[mode].format(a=min_arrival * 100, k=len(pool), t=len(tied))
    if not met:
        reason = f"도착률 {min_arrival * 100:.0f}% 이상을 만족하는 편성이 없어 도착률이 가장 높은 편성 중에서 골랐습니다. " + reason
    return {"formation": pick["formation"], "total": pick["total"], "reason": reason, "constraint_met": met}


# ── 진입점 ───────────────────────────────────────────────────────────────

def plan_formations(inp: PlanInput, workers: int | None = None, on_progress=None) -> dict:
    """후보 편성 전체를 평가하고 모드별 추천을 돌려준다 (JSON 으로 저장할 수 있는 dict)."""
    started = time.perf_counter()
    records = evaluate(inp, MODES, workers=workers, on_progress=on_progress)
    out: dict = {}
    for mode in MODES:
        cands = [compose(records, inp, mode, f) for f in inp.formations()]
        mark_pareto(cands)
        out[mode] = {"candidates": cands, "pick": choose(cands, mode, inp.min_arrival)}
    return {
        "version": PLANNER_VERSION, "cache_key": inp.cache_key(), "n_teams": inp.n_teams, "seeds": list(inp.seeds),
        "range": [inp.min_per_team, inp.max_per_team], "min_arrival": inp.min_arrival, "weather_scale": inp.weather_scale,
        "episodes": len(records), "elapsed_sec": round(time.perf_counter() - started, 1), "modes": out,
    }

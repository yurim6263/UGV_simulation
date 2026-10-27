"""
backend/app/simulation/optimize.py

NSGA-II 다목적 전술 최적화 + 몬테카를로 검증.

탐색 변수(유전자)
    편성:   ugv_1, ugv_2 (제대 1, 2 의 UGV 수. 제대 3 은 총수 - 나머지), perm (목표 배정 순열 0~5)
    전술:   dispersion_weight, weather_sensitivity, launch_delay_1~3, hold_km, recall_gap_km
    유전자를 고정(freeze)하면 그 값으로 묶고 나머지만 진화한다 — 지휘관의 의도를 미리 반영하는 방법.

목표 (모두 최소화로 변환)
    V1 수색 면적 비율 (최대화 → 부호 반전), V2 작전 시간(분), V3 운용자 과부하 시간(분)
    각 유전자를 여러 시나리오 강도 x 여러 시드로 평가한 평균을 쓴다(공통 난수: 모든 개체가 같은 시드를 쓴다).
제약
    평균 도착률 >= min_arrival (생존 제약). 제대별 UGV 수 범위는 제약이 아니라 보정(repair)으로 항상 만족시킨다.

검증
    최적화에 쓰지 않은 새 시드로 몬테카를로를 다시 돌려 평균, 95% 신뢰구간, 하위 5%(꼬리 위험)를 낸다.
    같은 시드로 "날씨를 무시하는 기준선"과도 비교한다.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, replace
from typing import Callable

import numpy as np
from pymoo.algorithms.moo.nsga2 import NSGA2
from pymoo.core.callback import Callback
from pymoo.core.problem import Problem
from pymoo.operators.crossover.sbx import SBX
from pymoo.operators.mutation.pm import PM
from pymoo.optimize import minimize

from app.simulation.algo.episode import Genes, ScenarioSpec
from app.simulation.batch import Job, run_batch

PERMUTATIONS = list(itertools.permutations(range(3)))


@dataclass(frozen=True)
class GeneSpec:
    name: str
    low: float
    high: float
    integer: bool = False


def gene_specs(min_per_team: int = 2, max_per_team: int = 5) -> list[GeneSpec]:
    return [
        GeneSpec("ugv_1", min_per_team, max_per_team, True),
        GeneSpec("ugv_2", min_per_team, max_per_team, True),
        GeneSpec("perm", 0, len(PERMUTATIONS) - 1, True),
        GeneSpec("dispersion_weight", 0.0, 3.0),
        GeneSpec("weather_sensitivity", 0.0, 2.0),
        GeneSpec("launch_delay_1", 0, 4, True),
        GeneSpec("launch_delay_2", 0, 4, True),
        GeneSpec("launch_delay_3", 0, 4, True),
        GeneSpec("hold_km", 1.0, 1.6),
        GeneSpec("recall_gap_km", 0.1, 0.6),
    ]


def _repair_formation(u1: int, u2: int, total: int, lo: int, hi: int) -> tuple[int, int, int]:
    """제대 1, 2 의 UGV 수를 조정해 제3제대 수가 [lo, hi] 안에 들어오게 한다 (항상 유효한 편성)."""
    if not 3 * lo <= total <= 3 * hi:
        raise ValueError(f"총 UGV {total} 대는 제대당 {lo}~{hi}대로 편성할 수 없습니다.")
    u1, u2 = min(max(u1, lo), hi), min(max(u2, lo), hi)
    while total - u1 - u2 < lo:
        if u1 >= u2 and u1 > lo:
            u1 -= 1
        else:
            u2 -= 1
    while total - u1 - u2 > hi:
        if u1 <= u2 and u1 < hi:
            u1 += 1
        else:
            u2 += 1
    return u1, u2, total - u1 - u2


def decode(x, total_ugv: int, base: ScenarioSpec, specs: list[GeneSpec] | None = None,
           frozen: dict | None = None) -> tuple[ScenarioSpec, Genes, dict]:
    """탐색 벡터 → (시나리오, 유전자, 사람이 읽는 값). 고정된 유전자는 그 값으로 덮어쓴다."""
    specs = specs or gene_specs()
    vals = {g.name: float(v) for g, v in zip(specs, x)}
    vals.update(frozen or {})
    for g in specs:
        if g.integer:
            vals[g.name] = int(round(vals[g.name]))
    ugv_1, ugv_2, ugv_3 = _repair_formation(vals["ugv_1"], vals["ugv_2"], total_ugv, int(specs[0].low), int(specs[0].high))
    vals.update(ugv_1=ugv_1, ugv_2=ugv_2, ugv_3=ugv_3)
    formation = (ugv_1, ugv_2, ugv_3)
    hold = vals["hold_km"]
    genes = Genes(
        launch_delay=(vals["launch_delay_1"], vals["launch_delay_2"], vals["launch_delay_3"]),
        dispersion_weight=vals["dispersion_weight"],
        weather_sensitivity=vals["weather_sensitivity"],
        hold_km=hold,
        recall_km=hold + vals["recall_gap_km"],
        resume_km=max(0.5, hold - 0.3),
    )
    spec = replace(base, formation=formation, assignment=PERMUTATIONS[vals["perm"]])
    return spec, genes, vals


def encode(spec: ScenarioSpec, genes: Genes, specs: list[GeneSpec] | None = None) -> np.ndarray:
    """프리셋(편성+유전자) → 탐색 벡터 (초기 개체로 심을 때 쓴다)."""
    specs = specs or gene_specs()
    vals = {
        "ugv_1": spec.formation[0], "ugv_2": spec.formation[1], "perm": PERMUTATIONS.index(tuple(spec.assignment)),
        "dispersion_weight": genes.dispersion_weight, "weather_sensitivity": genes.weather_sensitivity,
        "launch_delay_1": genes.launch_delay[0], "launch_delay_2": genes.launch_delay[1], "launch_delay_3": genes.launch_delay[2],
        "hold_km": genes.hold_km, "recall_gap_km": genes.recall_km - genes.hold_km,
    }
    return np.array([float(np.clip(vals[g.name], g.low, g.high)) for g in specs])


@dataclass(frozen=True)
class EvalPlan:
    """한 개체를 평가하는 방법: 시나리오 강도 x 시드 (공통 난수)."""
    scales: tuple = (0.2, 0.3, 0.4)
    seeds: tuple = (101, 102)
    max_turns: int = 24

    @property
    def size(self) -> int:
        return len(self.scales) * len(self.seeds)


def aggregate(metrics: list[dict]) -> dict:
    """에피소드 지표 목록 → 평균과 꼬리 위험."""
    arr = lambda k: np.array([m[k] for m in metrics], dtype=float)
    arrival = arr("arrival_rate")
    return {
        "n": len(metrics),
        "arrival": float(arrival.mean()),
        "arrival_p5": float(np.percentile(arrival, 5)),          # 하위 5%: 최악의 경우에도 도착하는가
        "completed": float(np.mean([m["completed"] for m in metrics])),
        "v1": float(arr("v1_coverage").mean()),
        "v2": float(arr("v2_minutes").mean()),
        "v2_p95": float(np.percentile(arr("v2_minutes"), 95)),
        "v3": float(arr("v3_overload_minutes").mean()),
        "sos": float(arr("sos_events").mean()),
    }


class TacticalProblem(Problem):
    """pymoo 문제 정의. 한 세대의 모든 개체 x 모든 시나리오를 한 번에 병렬 실행한다."""

    def __init__(self, base: ScenarioSpec, total_ugv: int, plan: EvalPlan, min_arrival: float = 0.8,
                 frozen: dict | None = None, workers: int | None = None, min_per_team: int = 2, max_per_team: int = 5):
        self.base, self.total_ugv, self.plan = base, total_ugv, plan
        self.min_arrival, self.frozen, self.workers = min_arrival, dict(frozen or {}), workers
        self.min_per_team, self.max_per_team = min_per_team, max_per_team
        self.specs = gene_specs(min_per_team, max_per_team)
        self.archive: list[dict] = []          # 평가한 모든 개체 (탈락한 개체의 분포를 그릴 때 쓴다)
        xl = np.array([self.frozen.get(g.name, g.low) for g in self.specs], dtype=float)
        xu = np.array([self.frozen.get(g.name, g.high) for g in self.specs], dtype=float)
        super().__init__(n_var=len(self.specs), n_obj=3, n_ieq_constr=1, xl=xl, xu=xu)

    def _jobs_for(self, x) -> list[Job]:
        spec, genes, _ = decode(x, self.total_ugv, self.base, self.specs, self.frozen)
        return [Job(replace(spec, weather_scale=s, max_turns=self.plan.max_turns), genes, seed)
                for s in self.plan.scales for seed in self.plan.seeds]

    def _evaluate(self, X, out, *args, **kwargs):
        jobs = [j for x in X for j in self._jobs_for(x)]
        results = run_batch(jobs, workers=self.workers)
        per = self.plan.size
        F, G = [], []
        for i, x in enumerate(X):
            agg = aggregate([r.metrics for r in results[i * per:(i + 1) * per]])
            F.append([-agg["v1"], agg["v2"], agg["v3"]])
            self.archive.append({"v1": agg["v1"], "v2": agg["v2"], "v3": agg["v3"], "arrival": agg["arrival"],
                                 "feasible": agg["arrival"] >= self.min_arrival})
            G.append([self.min_arrival - agg["arrival"]])                      # 평균 도착률 >= min_arrival
        out["F"], out["G"] = np.array(F), np.array(G)


class _Track(Callback):
    def __init__(self, on_gen: Callable | None = None):
        super().__init__()
        self.rows: list[dict] = []
        self.on_gen = on_gen

    def notify(self, algorithm):
        F, CV = algorithm.pop.get("F"), algorithm.pop.get("CV")[:, 0]
        feas = CV <= 0
        row = {"gen": int(algorithm.n_gen), "evals": int(algorithm.evaluator.n_eval), "feasible": int(feas.sum()), "pop": len(F)}
        if feas.any():
            row.update(best_v1=float(-F[feas, 0].min()), best_v2=float(F[feas, 1].min()), best_v3=float(F[feas, 2].min()))
        self.rows.append(row)
        if self.on_gen:
            self.on_gen(row)


@dataclass
class OptimizationResult:
    front: list[dict]              # 비지배 해 (유전자 + 최적화 중 평가값)
    history: list[dict]            # 세대별 진행
    feasible: bool
    archive: list[dict] | None = None   # 평가한 모든 개체의 목표값


def run_nsga2(base: ScenarioSpec, total_ugv: int = 9, plan: EvalPlan | None = None, pop_size: int = 20,
              generations: int = 10, seed: int = 1, min_arrival: float = 0.8, frozen: dict | None = None,
              workers: int | None = None, initial: list[np.ndarray] | None = None,
              on_gen: Callable | None = None) -> OptimizationResult:
    plan = plan or EvalPlan()
    problem = TacticalProblem(base, total_ugv, plan, min_arrival, frozen, workers)
    rng = np.random.default_rng(seed)
    random_x = rng.uniform(problem.xl, problem.xu, size=(pop_size, problem.n_var))
    seeds = [np.clip(x, problem.xl, problem.xu) for x in (initial or [])][:pop_size]
    sampling = np.vstack([*seeds, random_x[: pop_size - len(seeds)]]) if seeds else random_x
    algorithm = NSGA2(
        pop_size=pop_size, sampling=sampling,
        crossover=SBX(prob=0.9, eta=15), mutation=PM(eta=20), eliminate_duplicates=True,
    )
    track = _Track(on_gen)
    res = minimize(problem, algorithm, ("n_gen", generations), seed=seed, callback=track, verbose=False)

    feasible = res.X is not None
    if feasible:
        X, F = np.atleast_2d(res.X), np.atleast_2d(res.F)
    else:                                       # 제약을 만족하는 해가 없으면 위반이 가장 작은 개체들을 돌려준다
        pop = res.pop
        order = np.argsort(pop.get("CV")[:, 0])[: max(3, pop_size // 4)]
        X, F = pop.get("X")[order], pop.get("F")[order]

    front, seen = [], set()
    for x, f in zip(X, F):
        spec, genes, vals = decode(x, total_ugv, base, problem.specs, problem.frozen)
        key = (spec.formation, spec.assignment, genes)
        if key in seen:
            continue
        seen.add(key)
        front.append({"x": [float(v) for v in x], "values": vals, "train": {"v1": float(-f[0]), "v2": float(f[1]), "v3": float(f[2])}})
    return OptimizationResult(front=front, history=track.rows, feasible=feasible, archive=problem.archive)


# ── 몬테카를로 검증 ─────────────────────────────────────────────────────

def _ci95(values: np.ndarray) -> float:
    return float(1.96 * values.std(ddof=1) / math.sqrt(len(values))) if len(values) > 1 else 0.0


def _mc_jobs(spec: ScenarioSpec, genes: Genes, scales: tuple, seeds: tuple) -> list[Job]:
    return [Job(replace(spec, weather_scale=s), genes, seed) for s in scales for seed in seeds]


def summarize(metrics: list[dict]) -> dict:
    """에피소드 지표 목록 → 평균, 95% 신뢰구간, 하위 5%."""
    out = aggregate(metrics)
    for key, name in (("arrival_rate", "arrival"), ("v1_coverage", "v1"), ("v2_minutes", "v2"), ("v3_overload_minutes", "v3")):
        values = np.array([m[key] for m in metrics], dtype=float)
        out[f"{name}_ci95"] = _ci95(values)
    return out


def monte_carlo_many(tactics: list[tuple[ScenarioSpec, Genes]], scales: tuple, seeds: tuple,
                     workers: int | None = None) -> list[dict]:
    """여러 전술을 한 번의 배치로 검증한다 (전술마다 프로세스 풀을 새로 만드는 비용과 위험을 피한다)."""
    per = len(scales) * len(seeds)
    jobs = [j for spec, genes in tactics for j in _mc_jobs(spec, genes, scales, seeds)]
    results = run_batch(jobs, workers=workers)
    return [summarize([r.metrics for r in results[i * per:(i + 1) * per]]) for i in range(len(tactics))]


def monte_carlo(spec: ScenarioSpec, genes: Genes, scales: tuple, seeds: tuple, workers: int | None = None) -> dict:
    """한 전술(편성+유전자)을 새 시드로 반복 실행해 평균, 95% 신뢰구간, 하위 5% 를 낸다."""
    return monte_carlo_many([(spec, genes)], scales, seeds, workers)[0]


def validate_front(front: list[dict], total_ugv: int, base: ScenarioSpec, scales: tuple, seeds: tuple,
                   frozen: dict | None = None, workers: int | None = None,
                   on_item: Callable | None = None) -> list[dict]:
    specs = gene_specs()
    tactics = [decode(item["x"], total_ugv, base, specs, frozen)[:2] for item in front]
    for item, summary in zip(front, monte_carlo_many(tactics, scales, seeds, workers)):
        item["validation"] = summary
    if on_item:
        on_item(len(front), len(front))
    return front


# ── 대표 전술(원형) 선택 ─────────────────────────────────────────────────

def select_archetypes(front: list[dict], key: str = "train") -> dict[str, int]:
    """파레토 해에서 신속 / 정밀 / 균형 원형의 인덱스를 고른다.

    신속(rush)   : 작전 시간(v2)이 가장 짧은 해
    정밀(explore): 수색 면적(v1)이 가장 큰 해
    균형(balance): 세 목표를 정규화했을 때 이상점(v1 최대, v2·v3 최소)에 가장 가까운 해 (무릎점)
    같은 해가 중복 선택되지 않도록 뒤 순위로 넘어간다.

    key 는 선택에 쓰는 값이다. 기본값은 최적화 때의 평가값(train)이며, 검증 값(validation)으로 고르면 같은 값으로
    성능을 보고할 때 낙관적으로 편향된다 (여러 후보 중 잘 나온 것을 고르는 효과).
    """
    if not front:
        return {}
    v = np.array([[f[key]["v1"], f[key]["v2"], f[key]["v3"]] for f in front], dtype=float)
    span = np.where(np.ptp(v, axis=0) == 0, 1.0, np.ptp(v, axis=0))
    norm = (v - v.min(axis=0)) / span                        # 0~1
    ideal_dist = np.sqrt(((1 - norm[:, 0]) ** 2) + (norm[:, 1] ** 2) + (norm[:, 2] ** 2))
    rankings = {
        "rush": np.lexsort((-v[:, 0], v[:, 1])),             # v2 오름차순, 동률이면 v1 큰 순
        "explore": np.lexsort((v[:, 1], -v[:, 0])),          # v1 내림차순
        "balance": np.argsort(ideal_dist),
    }
    chosen: dict[str, int] = {}
    for mode in ("balance", "rush", "explore"):              # 무릎점을 먼저 확정
        for idx in rankings[mode]:
            if int(idx) not in chosen.values() or len(front) < 3:
                chosen[mode] = int(idx)
                break
    return chosen

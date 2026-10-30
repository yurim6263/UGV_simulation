"""
backend/scripts/run_nsga2.py

NSGA-II 로 전술(편성 + 유전자)을 최적화하고, 새 시드로 몬테카를로 검증해 파레토 결과를 저장한다.

    python backend/scripts/run_nsga2.py --pop 20 --gens 10 --out backend/data/optimization/pareto.json

결과(pareto.json)
    front        파레토 해 (유전자, 최적화 중 평가값, 새 시드 검증값: 평균/95% 신뢰구간/하위 5%)
    archetypes   신속 / 정밀 / 균형 원형으로 뽑힌 front 인덱스
    references   비교 대상: 팀원 기준 프리셋 3종, 날씨를 무시하는 기준선 (같은 검증 시드)
    archive      평가한 모든 개체의 목표값 (탈락한 개체의 분포)
    history      세대별 진행
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")   # 설정 import 용 (DB 는 사용하지 않음)
os.environ.setdefault("JWT_SECRET_KEY", "script-only")

from app.simulation.algo.episode import Genes, ScenarioSpec  # noqa: E402
from app.simulation.batch import default_workers  # noqa: E402
from app.simulation.optimize import (  # noqa: E402
    EvalPlan, OptimizationResult, decode, encode, gene_specs, monte_carlo_many, run_nsga2, select_archetypes,
    validate_front,
)
from app.simulation.presets import DEFAULT_POIS, DEFAULT_START, REFERENCE_PRESETS  # noqa: E402


def floats(text: str) -> tuple:
    return tuple(float(v) for v in text.split(","))


def ints(text: str) -> tuple:
    return tuple(int(v) for v in text.split(","))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=ROOT / "backend" / "data" / "optimization" / "pareto.json")
    ap.add_argument("--total-ugv", type=int, default=9)
    ap.add_argument("--pop", type=int, default=20)
    ap.add_argument("--gens", type=int, default=10)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--scales", type=floats, default=(0.2, 0.3, 0.4), help="최적화에 쓰는 시나리오 강도")
    ap.add_argument("--train-seeds", type=ints, default=(101, 102))
    ap.add_argument("--val-seeds", type=int, default=15, help="검증에 쓰는 새 시드 개수 (최적화에 쓰지 않은 값)")
    ap.add_argument("--min-arrival", type=float, default=0.8)
    ap.add_argument("--max-turns", type=int, default=24)
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--resume", action="store_true", help="최적화 중간 저장(<out>.stage1.json)이 있으면 최적화를 건너뛰고 검증부터 이어서 한다")
    args = ap.parse_args()

    workers = args.workers or default_workers()
    base = ScenarioSpec(start=DEFAULT_START, pois=DEFAULT_POIS, max_turns=args.max_turns)
    plan = EvalPlan(scales=args.scales, seeds=args.train_seeds, max_turns=args.max_turns)
    val_seeds = tuple(range(1000, 1000 + args.val_seeds))     # 최적화에 쓰지 않은 시드
    t0 = time.time()

    def log(msg: str) -> None:
        print(f"[{time.time() - t0:7.1f}s] {msg}", flush=True)

    # 팀원 기준 프리셋을 초기 개체로 심는다 (처음부터 비교 대상보다 나쁘지 않게)
    initial = [encode(replace(base, formation=p["formation"], assignment=p["assignment"]), p["genes"]) for p in REFERENCE_PRESETS.values()]
    stage1 = args.out.with_suffix(".stage1.json")
    if args.resume and stage1.exists():
        saved = json.loads(stage1.read_text(encoding="utf-8"))
        result = OptimizationResult(front=saved["front"], history=saved["history"], feasible=saved["feasible"], archive=saved["archive"])
        log(f"중간 저장에서 이어하기: 파레토 해 {len(result.front)}개 (최적화 건너뜀)")
    else:
        log(f"NSGA-II 시작: 개체 {args.pop}, {args.gens}세대, 시나리오 {args.scales} x 시드 {args.train_seeds} "
            f"(개체당 {plan.size}회), 워커 {workers}")
        result = run_nsga2(
            base, total_ugv=args.total_ugv, plan=plan, pop_size=args.pop, generations=args.gens, seed=args.seed,
            min_arrival=args.min_arrival, workers=workers, initial=initial,
            on_gen=lambda r: log(f"세대 {r['gen']:2d} 평가 {r['evals']:4d}회 | 만족 {r['feasible']}/{r['pop']} | "
                                 f"최고 V1 {r.get('best_v1', float('nan')):.3f} 최단 V2 {r.get('best_v2', float('nan')):.0f}분 "
                                 f"최소 V3 {r.get('best_v3', float('nan')):.0f}분"),
        )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        stage1.write_text(json.dumps({"front": result.front, "history": result.history, "feasible": result.feasible,
                                      "archive": result.archive}, ensure_ascii=False), encoding="utf-8")
        log(f"최적화 중간 저장: {stage1.name} (검증이 실패해도 --resume 으로 이어서 할 수 있다)")
    log(f"파레토 해 {len(result.front)}개 (제약 만족: {result.feasible})")

    log(f"몬테카를로 검증: 새 시드 {len(val_seeds)}개 x 강도 {len(args.scales)}개")
    validate_front(result.front, args.total_ugv, base, args.scales, val_seeds, workers=workers,
                   on_item=lambda i, n: log(f"  파레토 해 {n}개 검증 완료"))
    # 대표 전술은 최적화 때의 값(train)으로 고른다. 검증 값으로 고르면 '잘 나온 것만 고른' 편향이 생긴다.
    archetypes = select_archetypes(result.front, key="train")

    names, tactics = [], []
    for name, p in REFERENCE_PRESETS.items():
        names.append(f"reference_{name}")
        tactics.append((replace(base, formation=p["formation"], assignment=p["assignment"]), p["genes"]))
    p = REFERENCE_PRESETS["balance"]                        # 날씨를 무시하고 경로를 분산하지도 않는 기준선
    names.append("weather_blind")
    tactics.append((replace(base, formation=p["formation"], assignment=p["assignment"]),
                    Genes(weather_sensitivity=0.0, dispersion_weight=0.0)))
    log(f"비교 대상 {len(tactics)}개 검증")
    refs = dict(zip(names, monte_carlo_many(tactics, args.scales, val_seeds, workers)))

    specs = gene_specs()
    for item in result.front:
        spec, genes, _ = decode(item["x"], args.total_ugv, base, specs)
        item["formation"], item["assignment"] = list(spec.formation), list(spec.assignment)
        item["genes"] = {"launch_delay": list(genes.launch_delay), "dispersion_weight": genes.dispersion_weight,
                         "weather_sensitivity": genes.weather_sensitivity, "hold_km": genes.hold_km,
                         "recall_km": genes.recall_km, "resume_km": genes.resume_km}

    out = {
        "meta": {
            "created": datetime.now().isoformat(timespec="seconds"), "pop": args.pop, "gens": args.gens, "seed": args.seed,
            "scales": list(args.scales), "train_seeds": list(args.train_seeds), "val_seeds": list(val_seeds),
            "min_arrival": args.min_arrival, "total_ugv": args.total_ugv, "max_turns": args.max_turns,
            "elapsed_sec": round(time.time() - t0), "feasible": result.feasible,
            "archetype_selection": "train",
            "note": ("대표 전술(신속/정밀/균형)은 최적화 때의 평가값으로 골랐고, front.validation 은 최적화에 쓰지 않은 새 시드의 "
                     "몬테카를로 결과(평균, 95% 신뢰구간, 하위 5%)다. 선택에 쓰지 않은 데이터로 보고하므로 '잘 나온 것만 고른' 편향이 없다."),
        },
        "front": result.front, "archetypes": archetypes, "references": refs,
        "archive": result.archive, "history": result.history,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"저장: {args.out}")
    for mode, idx in archetypes.items():
        v = result.front[idx]["validation"]
        log(f"  {mode:8s} 편성 {result.front[idx]['formation']} 도착률 {v['arrival']:.3f}±{v['arrival_ci95']:.3f} "
            f"V1 {v['v1']:.3f} V2 {v['v2']:.0f}분 V3 {v['v3']:.1f}분")
    for name, v in refs.items():
        log(f"  {name:20s} 도착률 {v['arrival']:.3f}±{v['arrival_ci95']:.3f} V1 {v['v1']:.3f} V2 {v['v2']:.0f}분 V3 {v['v3']:.1f}분")


if __name__ == "__main__":
    main()

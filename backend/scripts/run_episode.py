"""
backend/scripts/run_episode.py

엔진(run_episode)으로 모드별 시뮬레이션을 돌려 프론트 재생 데이터로 저장한다.
팀원 기록(export_replay.py)과 같은 형식이라 화면에서 "엔진 실행" 데이터로 바로 볼 수 있다.

사용 예 (프로젝트 루트에서):
    python backend/scripts/run_episode.py --out frontend_js/static/replay_engine --scale moderate --seed 1
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")   # 설정 import 용 (DB 는 사용하지 않음)
os.environ.setdefault("JWT_SECRET_KEY", "script-only")

from app.simulation.algo.environment import Environment  # noqa: E402
from app.simulation.algo.episode import run_episode  # noqa: E402
from app.simulation.algo.sim_config import SimAlgoConfig  # noqa: E402
from app.simulation.presets import DEFAULT_POIS, DEFAULT_START, WEATHER_SCALES, preset  # noqa: E402
from app.simulation.replay import MODES, OVERLAY_COLUMNS, build_mode, grid_bounds, log_to_frame, overlay_png  # noqa: E402

KIND_OF = {"total": "total", "mobility": "mob", "sensor": "sen"}


def export_overlays(env: Environment, turns: int, scale: float, out: Path) -> None:
    """엔진이 보는 실황 레이어를 턴별 G/A/R PNG 로 저장 (등급 기준은 전 턴 공통 30/70 분위수)."""
    start = env.start_time
    for name, kind in KIND_OF.items():
        grids = [np.clip(env.latest_actual_at(start + timedelta(minutes=10 * t), kind) * scale, 0, 1) for t in range(turns)]
        lo, hi = np.percentile(np.concatenate([g[np.isfinite(g)] for g in grids]), [30, 70])
        (out / "overlay" / name).mkdir(parents=True, exist_ok=True)
        for t, g in enumerate(grids):
            overlay_png(g, lo, hi).save(out / "overlay" / name / f"{t}.png", optimize=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--scale", default="moderate", help="clear | moderate | severe 또는 0~1 숫자")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--turns", type=int, default=24)
    args = ap.parse_args()

    scale = WEATHER_SCALES.get(args.scale)
    if scale is None:
        scale = float(args.scale)
    args.out.mkdir(parents=True, exist_ok=True)

    env = Environment(SimAlgoConfig())
    env.load_base_layer()
    env.load_all_data()

    max_turns = args.turns
    for mode, label in MODES.items():
        spec, genes = preset(mode, weather_scale=scale, max_turns=max_turns)
        t0 = time.time()
        result = run_episode(env, spec, genes, seed=args.seed)
        data = build_mode(log_to_frame(result.log), mode, label, result.poi_cells)
        data["engine_metrics"] = result.metrics          # V1~V3 포함 (재생 화면은 kpi 만 사용)
        (args.out / f"{mode}.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        m = result.metrics
        print(f"{mode:8s} {time.time() - t0:4.1f}s 완료={m['completed']} 도착={m['ugv_arrived']}/{m['ugv_total']} "
              f"SOS={m['sos_events']} 개입={m['interventions']} V1={m['v1_coverage']} V2={m['v2_minutes']}분 V3={m['v3_overload_minutes']}분")

    export_overlays(env, max_turns, scale, args.out)
    meta = SimAlgoConfig.meta()
    scenario = {
        "case": f"엔진 실행 · 그단스크 2023-06-30 22:00 · 강도 {args.scale} (시드 {args.seed})",
        "turn_minutes": 10,
        "turns": max_turns,
        "bounds": grid_bounds(meta.lat, meta.lon),
        "start": list(DEFAULT_START),
        "pois": [{"id": i + 1, "lat": p[0], "lon": p[1]} for i, p in enumerate(DEFAULT_POIS)],
        "modes": [{"key": k, "label": v} for k, v in MODES.items()],
        "overlays": [{"key": "total", "label": "종합 위험도"},
                     {"key": "mobility", "label": "기동성 위험도"},
                     {"key": "sensor", "label": "센서 위험도"}],
    }
    (args.out / "scenario.json").write_text(json.dumps(scenario, ensure_ascii=False, indent=1), encoding="utf-8")
    print("→", args.out)


if __name__ == "__main__":
    main()

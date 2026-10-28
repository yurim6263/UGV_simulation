"""
backend/scripts/precompute_formation.py

기본 목표(팀원 시나리오의 정찰지 3곳)에 대한 편성 계산을 미리 해서 backend/data/formation/default_plan.json 에 저장한다.
화면의 기본 입력값(목표 3곳, 정찰 30분, 보유 UGV 9대, 240분)과 같은 입력이면 서버가 이 결과를 바로 쓴다 (계산 약 1분 절약).

입력(출발지, 목표, 정찰 시간, 날씨 강도, 시드, 모드 전술 등)이 하나라도 다르면 키가 달라져 이 파일을 쓰지 않고 새로 계산한다.
시뮬레이션 엔진, 모드 전술(presets), 계산기 버전이 바뀌면 이 스크립트를 다시 실행해야 한다.

    cd backend
    python scripts/precompute_formation.py [--scale moderate] [--workers 4]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

OUT = BACKEND / "data" / "formation" / "default_plan.json"


def main() -> None:
    import os

    os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")           # 설정 객체가 요구하는 값 (DB 는 쓰지 않는다)
    from app.simulation.formation import plan_formations, plan_input_for
    from app.simulation.presets import DEFAULT_POIS, DEFAULT_START, WEATHER_SCALES

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scale", default="moderate", help="clear | moderate | severe 또는 0~1 숫자 (서버의 SIM_WEATHER_SCALE 과 같게)")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    scale = WEATHER_SCALES.get(args.scale)
    if scale is None:
        scale = float(args.scale)

    mission = {"departure_lat": DEFAULT_START[0], "departure_lon": DEFAULT_START[1], "targets": list(DEFAULT_POIS),
               "patrol_sec": [1800, 1800, 1800], "duration_min": 240, "total_ugv": 9}      # 화면의 기본값 (launchMission)
    inp = plan_input_for(mission, scale)
    print(f"계산 중... (에피소드 {inp.n_teams * (inp.max_per_team - inp.min_per_team + 1) * len(inp.seeds) * 3}개, 작업자 {args.workers})", flush=True)
    plan = plan_formations(inp, workers=args.workers, on_progress=lambda d, t: print(f"\r  {d}/{t}", end="", flush=True))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(plan, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"\n완료 {plan['elapsed_sec']}초 → {OUT}")
    for mode, label in (("explore", "정밀"), ("rush", "신속"), ("balance", "균형")):
        pick = plan["modes"][mode]["pick"]
        print(f"  {label}: {pick['formation']} (합 {pick['total']}대)")


if __name__ == "__main__":
    main()

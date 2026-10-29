"""
backend/scripts/build_ltwr_layers.py

시나리오 날짜의 위험도(LTWR) 실황 31장과 예보 54장을 만든다 (기존 map_20km/dynamic 과 같은 형식, 전체 12,321칸).

    cd backend
    python scripts/build_ltwr_layers.py [--start 2022-08-20T22:00] [--out data/map_20km_rebuilt/dynamic]

  실황 : 시작 시각부터 5시간(10분 간격 31장). ERA5-Land 시간별 값에서 위험도를 계산하고 10분 간격으로 선형 보간한다.
  예보 : 시작, +1시간, +2시간에 발표한 3회, 발표마다 +0~170분(10분 간격 18장). 발표 시각의 값은 실황(ERA5)이고 이후 1~3시간은
         직접 학습한 ConvLSTM(data/weather/convlstm.pt)이 예측한 값이다. 예보는 실제 미래값을 쓰지 않는다.
  필요: ERA5-Land 2018~2022(WEATHER_ERA5_DIR, 첫 실행은 읽는 데 몇 분), 정적 격자(scripts/build_static_grid.py), 학습된 ConvLSTM.
위험도 계산식과 가정은 app/weather/ltwr.py 의 머리말 참고.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from app.weather import ltwr  # noqa: E402
from app.weather.dataset import load_region_cached  # noqa: E402
from app.weather.forecast_model import Forecaster  # noqa: E402

STATIC = BACKEND / "data" / "map_20km_rebuilt" / "static" / "Test_sim_input_200m_bbox_20km.parquet"


def stamp(t: datetime) -> str:
    return t.strftime("%Y%m%d_%H%M")


def write(layer: dict, terrain: ltwr.Terrain, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ltwr.to_frame(layer, terrain).astype({"normalized_c_total": "float32", "c_mob_prime": "float32", "c_sen_prime": "float32"}).to_parquet(path, index=False, compression="zstd")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", default="2022-08-20T22:00", help="시나리오 시작 시각 (UTC, 정시)")
    ap.add_argument("--out", default=str(BACKEND / "data" / "map_20km_rebuilt" / "dynamic"))
    ap.add_argument("--hours", type=int, default=5, help="실황 길이(시간). 10분 간격 hours*6+1 장")
    ap.add_argument("--forecast-issues", type=int, default=3)
    args = ap.parse_args()

    start = datetime.fromisoformat(args.start)
    out = Path(args.out)
    reg = load_region_cached()
    terrain = ltwr.Terrain(pd.read_parquet(STATIC))
    rs = ltwr.GridResampler(reg.lat, reg.lon, reg.land, terrain)
    k0 = reg.index_of(np.datetime64(start, "h"))

    # ── 실황 ──
    lo = k0 - 4                                                   # 안개의 wet_3h 를 위해 앞 몇 시간
    fields = ltwr.coarse_fields(reg.data[lo:k0 + args.hours + 1])
    hourly = ltwr.hourly_layers({n: v[k0 - lo:] for n, v in fields.items()}, rs, terrain)
    actual = ltwr.interpolate_minutes(hourly)
    for i, layer in enumerate(actual):
        write(layer, terrain, out / "actual" / f"sim_cost_map_{stamp(start + timedelta(minutes=10 * i))}.parquet")
    print(f"실황 {len(actual)}장: {stamp(start)} ~ {stamp(start + timedelta(minutes=10 * (len(actual) - 1)))}")

    # ── 예보 ──
    fc = Forecaster()
    summary = []
    for j in range(args.forecast_issues):
        issue = start + timedelta(hours=j)
        k = reg.index_of(np.datetime64(issue, "h"))
        pred = fc.predict(reg, np.datetime64(issue, "h"))         # (3, C, H, W)
        frames = np.concatenate([reg.data[k - 2:k + 1], pred])    # 발표 직전 2시간 + 발표 시각(실황) + 예측 3시간
        f = ltwr.coarse_fields(frames)
        layers = ltwr.hourly_layers({n: v[2:] for n, v in f.items()}, rs, terrain)     # 발표 시각 ~ +3시간 (4개)
        mins = ltwr.interpolate_minutes(layers, count=18)
        for i, layer in enumerate(mins):
            write(layer, terrain, out / "forecast" / stamp(issue) / f"sim_cost_map_{stamp(issue + timedelta(minutes=10 * i))}.parquet")
        summary.append({"issue": stamp(issue), "files": len(mins), "total_mean_first_last": [round(float(mins[0]["total"].mean()), 3), round(float(mins[-1]["total"].mean()), 3)]})
        print(f"예보 발표 {stamp(issue)}: {len(mins)}장")
    meta = {"generator": "scripts/build_ltwr_layers.py", "start_utc": args.start, "created": datetime.now().isoformat(timespec="seconds"),
            "weather": "ERA5-Land hourly 0.1deg (actual), ConvLSTM data/weather/convlstm.pt (forecast leads 1-3h)",
            "cells": int(len(terrain.static)), "forecast": summary,
            "note": "팀 원본 LTWR 생성 코드가 없어 app/weather/ltwr.py 의 우리 정의로 만든 값이다. 팀 결과보고서의 수치와 같지 않다."}
    (out / "README.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()

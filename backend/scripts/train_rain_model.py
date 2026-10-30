"""
backend/scripts/train_rain_model.py

ERA5-Land 로 강수 1~3시간 후 예측 모델(XGBoost)을 학습하고 지속성 기준선과 비교한다.

    python backend/scripts/train_rain_model.py --era5-dir "<final_project>/ERA5_기상데이터_자료/ERA5_land"

처음 실행은 월별 파일 60개를 읽어 약 3분이 걸리고, 결과(지역 강수)를 backend/data/weather/cache 에 저장해 다음부터는 몇 초다.
산출물: backend/data/weather/rain_model_metrics.json, docs/weather_model_report.md (make_weather_report 로직 포함)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.weather.era5 import compare_deaccumulation, load_region, rain_rate_mm  # noqa: E402
from app.weather.rain_model import (  # noqa: E402
    THRESHOLDS, bootstrap_csi, build_split, climatology, daily_counts, evaluate, persistence, predict_xgb, train_xgb,
)

# 그단스크 작전 지역 주변 (0.1° 격자). 육지 격자만 쓴다 (ERA5-Land 는 바다가 비어 있다).
LAT, LON = (53.9, 54.9), (17.9, 19.0)
TRAIN_END, VAL_END = "2022-01-01T00:00", "2022-07-01T00:00"     # 예측 대상 시각 기준 분할
CACHE = ROOT / "backend" / "data" / "weather" / "cache" / "rain_gdansk.npz"
OUT_JSON = ROOT / "backend" / "data" / "weather" / "rain_model_metrics.json"


def load_rain(era5_dir: Path) -> tuple[np.ndarray, np.ndarray, dict]:
    """(rain mm/h (T, 육지셀), 시각 (T,), 전처리 비교 통계). 캐시가 있으면 그것을 쓴다."""
    if CACHE.exists():
        z = np.load(CACHE, allow_pickle=False)
        return z["rain"], z["times"].astype("datetime64[h]"), json.loads(str(z["deacc"]))
    t0 = time.time()
    ds = load_region(era5_dir, lat=LAT, lon=LON, variables=("tp",))
    tp, times = ds.tp.values, ds.valid_time.values.astype("datetime64[h]")
    land = ~np.isnan(tp[1:]).any(axis=0)                           # 한 번이라도 NaN 이면 바다
    deacc = compare_deaccumulation(tp[:, land], times)
    deacc["land_cells"], deacc["total_cells"] = int(land.sum()), int(land.size)
    rain = rain_rate_mm(tp, times)[:, land]
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(CACHE, rain=rain, times=times.astype("datetime64[h]").astype(np.int64), deacc=json.dumps(deacc))
    print(f"ERA5 로드 {time.time() - t0:.0f}s, 육지 격자 {land.sum()}/{land.size} → 캐시 저장")
    return rain, times, deacc


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--era5-dir", type=Path, required=True)
    ap.add_argument("--horizons", default="1,2,3")
    ap.add_argument("--train-frac", type=float, default=0.4, help="학습 표본 비율 (메모리 절약, 분포는 유지)")
    ap.add_argument("--rounds", type=int, default=600)
    args = ap.parse_args()

    rain, times, deacc = load_rain(args.era5_dir)
    print(f"강수 자료 {rain.shape} (시간 x 육지 격자), {times[0]} ~ {times[-1]}")
    results = {"region": {"lat": LAT, "lon": LON, "cells": int(rain.shape[1])}, "deaccumulation": deacc,
               "split": {"train": f"< {TRAIN_END}", "val": f"{TRAIN_END} ~ {VAL_END}", "test": f">= {VAL_END}"}, "horizons": {}}

    for h in [int(v) for v in args.horizons.split(",")]:
        t0 = time.time()
        train = build_split(rain, times, h, "2018-01-02T00:00", TRAIN_END, keep_frac=args.train_frac, seed=h)
        val = build_split(rain, times, h, TRAIN_END, VAL_END, keep_frac=0.5, seed=h)
        test = build_split(rain, times, h, VAL_END, "2023-01-01T00:00")
        booster = train_xgb(train, val, rounds=args.rounds)
        preds = {"xgboost": predict_xgb(booster, test), "persistence": persistence(test), "climatology": climatology(train, len(test))}
        entry = {"samples": {"train": len(train), "val": len(val), "test": len(test)}, "best_iteration": int(booster.best_iteration),
                 "models": {name: evaluate(test, p) for name, p in preds.items()}, "xgb_vs_persistence": {}}
        for thr in THRESHOLDS:
            _, cx = daily_counts(test, preds["xgboost"], thr)
            _, cp = daily_counts(test, preds["persistence"], thr)
            entry["xgb_vs_persistence"][str(thr)] = bootstrap_csi(cx, cp, n_boot=1000)
        imp = booster.get_score(importance_type="gain")
        entry["feature_gain"] = {k: round(float(v), 4) for k, v in sorted(imp.items(), key=lambda kv: -kv[1])[:6]}
        results["horizons"][str(h)] = entry
        m = entry["models"]
        print(f"[{h}h] {time.time() - t0:3.0f}s  MAE xgb {m['xgboost']['mae']:.4f} persist {m['persistence']['mae']:.4f} clim {m['climatology']['mae']:.4f} | "
              f"CSI@0.1 xgb {m['xgboost']['thr_0.1']['csi']:.3f} persist {m['persistence']['thr_0.1']['csi']:.3f}")

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print("저장:", OUT_JSON)


if __name__ == "__main__":
    main()

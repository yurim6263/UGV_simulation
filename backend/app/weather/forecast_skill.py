"""
backend/app/weather/forecast_skill.py

저장소의 위험도 예보(forecast/) 를 같은 시각의 실황(actual/) 과 비교해 예보 시간(리드타임)별 오차를 낸다.

기준선은 지속성(persistence): "예보 발표 시각의 실황을 그대로 유지". 예보가 지속성보다 나을 때만 의미가 있다.
    skill = 1 - MAE(예보) / MAE(지속성)      (양수면 예보가 낫다, 0 이면 같고, 음수면 지속성보다 나쁘다)

동적 파일은 경로 버퍼 안의 셀만 담으므로 예보와 실황이 모두 값을 가진 셀만 비교한다.
"""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from app.simulation.algo.environment import parse_stamp

COLUMNS = {"total": "normalized_c_total", "mobility": "c_mob_prime", "sensor": "c_sen_prime"}
STEP_MIN = 10


def _grid(path: Path, column: str) -> pd.Series:
    df = pd.read_parquet(path, columns=["cell_id", column])
    return df.set_index("cell_id")[column]


def _stamp(name: str) -> str:
    return re.findall(r"\d{8}_\d{4}", name)[-1]


def index_files(dynamic_dir: Path) -> tuple[dict, dict]:
    """(실황 {시각: 파일}, 예보 {모델시각: {목표시각: 파일}})"""
    actual = {parse_stamp(_stamp(f.name)): f for f in (dynamic_dir / "actual").glob("*.parquet")}
    forecast: dict = {}
    for d in sorted((dynamic_dir / "forecast").iterdir()):
        if d.is_dir():
            forecast[parse_stamp(d.name)] = {parse_stamp(_stamp(f.name)): f for f in d.glob("*.parquet")}
    return actual, forecast


def skill_by_lead(dynamic_dir: Path, kind: str = "total") -> dict:
    """리드타임(0~170분)별 평균 오차. 모델 시각마다 계산한 뒤 평균하고, 모델별 값도 돌려준다."""
    col = COLUMNS[kind]
    actual, forecast = index_files(Path(dynamic_dir))
    cache: dict = {}

    def actual_at(t):
        if t not in cache:
            cache[t] = _grid(actual[t], col)
        return cache[t]

    rows, per_model = [], {}
    for model_t, targets in sorted(forecast.items()):
        if model_t not in actual:
            continue
        base = actual_at(model_t)                                  # 지속성: 발표 시각의 실황을 유지
        for k in range(0, 18):
            target_t = model_t + timedelta(minutes=k * STEP_MIN)
            if target_t not in targets or target_t not in actual:
                continue
            truth, fc = actual_at(target_t), _grid(targets[target_t], col)
            both = truth.index.intersection(fc.index).intersection(base.index)
            t, f, b = truth[both].to_numpy(float), fc[both].to_numpy(float), base[both].to_numpy(float)
            ok = np.isfinite(t) & np.isfinite(f) & np.isfinite(b)
            if not ok.any():
                continue
            t, f, b = t[ok], f[ok], b[ok]
            mae_f, mae_p = float(np.abs(f - t).mean()), float(np.abs(b - t).mean())
            rows.append({
                "model_time": model_t.isoformat(timespec="minutes"), "lead_min": k * STEP_MIN, "cells": int(ok.sum()),
                "mae_forecast": mae_f, "mae_persistence": mae_p,
                "bias_forecast": float((f - t).mean()), "rmse_forecast": float(np.sqrt(((f - t) ** 2).mean())),
                "skill": (1 - mae_f / mae_p) if mae_p > 1e-9 else float("nan"),
            })
    df = pd.DataFrame(rows)
    if df.empty:
        raise ValueError(f"비교할 예보/실황 쌍이 없습니다: {dynamic_dir}")
    for model_t, g in df.groupby("model_time"):
        per_model[model_t] = g.drop(columns="model_time").round(5).to_dict("records")
    by_lead = (df.groupby("lead_min")[["mae_forecast", "mae_persistence", "bias_forecast", "rmse_forecast", "skill"]].mean()
               .round(5).reset_index().to_dict("records"))
    return {"kind": kind, "models": sorted(per_model), "by_lead": by_lead, "per_model": per_model,
            "mean_skill": float(df["skill"].mean()), "share_leads_better_than_persistence": float((df["skill"] > 0).mean())}

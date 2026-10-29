"""
backend/app/weather/fog.py

안개(저시정) 가능성 proxy. ERA5-Land 에는 시정/안개 변수가 없어서, 팀 노트북(`xgb_fogProb_1h_ahead.ipynb`)의 규칙을 그대로 옮겼다.

  ΔT = max(T2m - Td2m, 0) [°C],  U = 10m 풍속 [m/s],  wet_3h = 최근 3시간 강수 합이 0.2mm 이상이면 1
  z  = 2.2 (2.0 - ΔT) + 1.2 (3.0 - U) + 0.8 wet_3h        (-15 ~ 15 로 자름)
  fog_prob = 1 / (1 + exp(-z))
  vis_class: 2(낮음, 0.5km 미만 proxy) = (ΔT<=1 & U<=2) | (ΔT<=0.7 & U<=4),  1(중간, 2km 미만 proxy) = (ΔT<=2 & U<=4) | (ΔT<=1.5 & U<=6), 아니면 0

계수는 팀 노트북의 "초기값(튜닝 대상)"이고 관측 시정으로 보정하지 않았다. 안개에는 강하고 연무/먼지에는 약한 proxy 다.
"""

from __future__ import annotations

import numpy as np

DT0, U0 = 2.0, 3.0
WET_RAIN_3H_MM = 0.2


def wet_3h(rain_mmph: np.ndarray, axis: int = 0) -> np.ndarray:
    """시간 축(axis)을 따라 직전 3시간(자기 포함) 강수 합이 0.2mm 이상이면 1. 앞의 두 시각은 있는 만큼만 더한다 (팀: rolling(3, min_periods=1))."""
    r = np.moveaxis(np.nan_to_num(rain_mmph, nan=0.0), axis, 0)
    out = r.copy()
    out[1:] += r[:-1]
    out[2:] += r[:-2]
    return np.moveaxis((out >= WET_RAIN_3H_MM).astype("float32"), 0, axis)


def fog_probability(t2m_k: np.ndarray, d2m_k: np.ndarray, wind_ms: np.ndarray, wet: np.ndarray | float = 0.0) -> np.ndarray:
    d_t = np.maximum(t2m_k - d2m_k, 0.0)
    z = np.clip(2.2 * (DT0 - d_t) + 1.2 * (U0 - wind_ms) + 0.8 * wet, -15, 15)
    return (1.0 / (1.0 + np.exp(-z))).astype("float32")


def vis_class(t2m_k: np.ndarray, d2m_k: np.ndarray, wind_ms: np.ndarray) -> np.ndarray:
    d_t = np.maximum(t2m_k - d2m_k, 0.0)
    low = ((d_t <= 1.0) & (wind_ms <= 2.0)) | ((d_t <= 0.7) & (wind_ms <= 4.0))
    med = ((d_t <= 2.0) & (wind_ms <= 4.0)) | ((d_t <= 1.5) & (wind_ms <= 6.0))
    return np.where(low, 2, np.where(med, 1, 0)).astype("int8")

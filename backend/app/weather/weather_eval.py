"""
backend/app/weather/weather_eval.py

ConvLSTM 예측을 기준선(지속성, 기후값)과 같은 시험 구간 창으로 비교한다. 팀 분석(`docs/weather_model_report.md`)과 같은 원칙:
평균 오차만 보지 않고 일 단위 블록 부트스트랩으로 차이의 95% 구간을 내서 "단정 불가"를 구분한다.

지표(육지 칸): 강수 MAE/RMSE/CSI@0.1·1.0, 기온·이슬점·풍속·토양수분 MAE, 안개 확률(팀 노트북 식, app/weather/fog.py) MAE/CSI@0.5.
  - 안개 확률은 t2m, d2m, 풍속, 최근 3시간 강수(wet_3h)에서 구한 파생값이다. 최근 2시간의 강수는 관측값을 쓰고 이후는 각 방법의 예측값을 쓴다.
    ERA5-Land 에는 시정이 없어 관측 대비 검증이 아니라 "ERA5 값으로 계산한 안개 확률"을 맞힌 정도다.
"""

from __future__ import annotations

import numpy as np

from app.weather.dataset import CHANNELS, HORIZON
from app.weather.fog import fog_probability


def derived(x: np.ndarray, rain_hist: np.ndarray) -> dict[str, np.ndarray]:
    """x (N, F, C, H, W) 물리값, rain_hist (N, 2, H, W) 예측 직전 2시간의 관측 강수 → 평가 변수들"""
    g = lambda name: x[:, :, CHANNELS.index(name), :, :]  # noqa: E731
    rain = g("rain")
    seq = np.concatenate([np.nan_to_num(rain_hist), np.nan_to_num(rain)], axis=1)                   # (N, 2+F, H, W)
    wet = ((seq[:, :-2] + seq[:, 1:-1] + seq[:, 2:]) >= 0.2).astype("float32")                      # 각 예측 시각의 최근 3시간 (자기 포함)
    wind = np.hypot(g("u10"), g("v10"))
    return {"rain": rain, "t2m": g("t2m"), "d2m": g("d2m"), "wind": wind, "swvl1": g("swvl1"), "fog": fog_probability(g("t2m"), g("d2m"), wind, wet)}


def window_errors(pred: dict, truth: dict, land: np.ndarray) -> dict:
    """창마다 육지 칸 평균 절대오차/제곱오차. pred, truth: {변수: (N, F, H, W)} → {변수: {'mae': (N,F), 'mse': (N,F)}}"""
    out = {}
    for k in truth:
        d = (pred[k] - truth[k])[..., land]
        out[k] = {"mae": np.abs(d).mean(-1), "mse": (d ** 2).mean(-1)}
    return out


def csi(pred: np.ndarray, truth: np.ndarray, thr: float, land: np.ndarray) -> np.ndarray:
    """(N, F, H, W) → 시간(F)별 CSI"""
    p, t = pred[..., land] >= thr, truth[..., land] >= thr
    hits, miss, fa = (p & t).sum((0, 2)), (~p & t).sum((0, 2)), (p & ~t).sum((0, 2))
    return hits / np.maximum(hits + miss + fa, 1)


def block_bootstrap_diff(err_a: np.ndarray, err_b: np.ndarray, day_of_window: np.ndarray, n: int = 1000, seed: int = 0) -> tuple[float, float, float]:
    """창별 오차 err_a - err_b 의 평균과 95% 구간 (같은 날의 창을 한 덩어리로 다시 뽑는다)."""
    diff = err_a - err_b
    days = np.unique(day_of_window)
    sums = {d: (diff[day_of_window == d].sum(), int((day_of_window == d).sum())) for d in days}
    rng = np.random.default_rng(seed)
    means = np.empty(n)
    for i in range(n):
        pick = rng.choice(days, size=len(days), replace=True)
        s = sum(sums[d][0] for d in pick)
        c = sum(sums[d][1] for d in pick)
        means[i] = s / c
    return float(diff.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def verdict(lo: float, hi: float) -> str:
    """오차 차이(모델 - 기준선)의 95% 구간으로 판정. 음수면 모델 오차가 작다."""
    return "모델 우세(뚜렷)" if hi < 0 else "기준선 우세(뚜렷)" if lo > 0 else "단정 불가"

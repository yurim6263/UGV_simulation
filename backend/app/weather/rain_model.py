"""
backend/app/weather/rain_model.py

강수 1~3시간 후 예측: 데이터 셋 구성, 기준선, XGBoost, 평가(기준선 대비 차이의 신뢰구간 포함).

팀원 XGBoost 노트북(`xgb_rain_1h_ahead_tailaware`)의 설정을 따른다: 최근 12시간 강수 + 계절성(연중 일) 특징.
달라진 점: (1) 강수량 전처리를 올바른 규칙으로(era5.py), (2) 시각(시) 특징 추가, (3) 3시간 후까지 예측 수평선별 모델,
(4) 지속성(persistence) 기준선과의 차이를 일 단위 블록 부트스트랩 신뢰구간으로 판정.

데이터 누수 방지: 분할은 "예측 대상 시각" 기준(학습 < 2022-01 ≤ 검증 < 2022-07 ≤ 시험). 입력(지연 값)은 항상
예측 시점(t) 이하이고, 대상은 t+h 이다.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

N_LAGS = 12
FEATURE_NAMES = [f"lag_{k}" for k in range(N_LAGS)] + ["doy_sin", "doy_cos", "hour_sin", "hour_cos"]
THRESHOLDS = (0.1, 0.5, 1.0)          # mm/h — 비가 온다고 보는 기준


def time_features(times: np.ndarray) -> np.ndarray:
    """(n,) datetime64 → (n, 4): 연중 일, 시각(시)의 sin/cos."""
    t = times.astype("datetime64[h]")
    day = t.astype("datetime64[D]")
    hour = (t - day).astype(int)
    doy = (day - day.astype("datetime64[Y]")).astype(int)
    a, b = 2 * np.pi * doy / 366.0, 2 * np.pi * hour / 24.0
    return np.stack([np.sin(a), np.cos(a), np.sin(b), np.cos(b)], axis=1).astype(np.float32)


@dataclass
class Split:
    X: np.ndarray
    y: np.ndarray
    day: np.ndarray        # (n,) 예측 대상이 속한 날 (블록 부트스트랩의 블록)

    def __len__(self) -> int:
        return len(self.y)


def build_split(rain: np.ndarray, times: np.ndarray, horizon: int, target_start, target_end,
                keep_frac: float = 1.0, seed: int = 0, chunk_hours: int = 2000) -> Split:
    """예측 대상 시각이 [target_start, target_end) 인 표본. rain: (T, C) mm/h, NaN 은 건너뛴다."""
    T, C = rain.shape
    tgt_time = times.astype("datetime64[h]")
    lo = int(np.searchsorted(tgt_time, np.datetime64(target_start, "h"), side="left"))
    hi = int(np.searchsorted(tgt_time, np.datetime64(target_end, "h"), side="left"))
    tg_all = np.arange(max(lo, N_LAGS + horizon), min(hi, T))
    rng = np.random.default_rng(seed)

    Xs, ys, days = [], [], []
    for chunk in np.array_split(tg_all, max(1, len(tg_all) // chunk_hours)):    # 구간별로 만들며 바로 줄여 메모리를 아낀다
        if len(chunk) == 0:
            continue
        org = chunk - horizon                                # 예측을 하는 시점 t. 대상은 t + horizon
        lags = np.stack([rain[org - k] for k in range(N_LAGS)], axis=2)               # (n, C, 12)  lag_0 = 지금
        feats = np.repeat(time_features(times[org])[:, None, :], C, axis=1)           # (n, C, 4)
        X = np.concatenate([lags, feats], axis=2).reshape(-1, len(FEATURE_NAMES))
        y = rain[chunk].reshape(-1)
        day = np.repeat(times[chunk].astype("datetime64[D]").astype(np.int64), C)
        ok = np.isfinite(X).all(axis=1) & np.isfinite(y)
        if keep_frac < 1.0:                                  # 무작위 부분 표본 (분포를 바꾸지 않는다)
            ok &= rng.random(len(y)) < keep_frac
        Xs.append(X[ok]); ys.append(y[ok]); days.append(day[ok])
    if not Xs:
        return Split(np.zeros((0, len(FEATURE_NAMES)), np.float32), np.zeros(0, np.float32), np.zeros(0, np.int64))
    return Split(np.concatenate(Xs), np.concatenate(ys), np.concatenate(days))


# ── 기준선 ───────────────────────────────────────────────────────────────

def persistence(split: Split) -> np.ndarray:
    """지속성: h 시간 뒤 강수 = 지금(lag_0) 강수."""
    return split.X[:, 0]


def climatology(train: Split, n: int) -> np.ndarray:
    return np.full(n, float(train.y.mean()), dtype=np.float32)


# ── 평가 ─────────────────────────────────────────────────────────────────

def contingency(y: np.ndarray, pred: np.ndarray, thr: float) -> tuple[int, int, int]:
    obs, fc = y >= thr, pred >= thr
    return int((obs & fc).sum()), int((obs & ~fc).sum()), int((~obs & fc).sum())    # 적중, 놓침, 헛경보


def scores(hits: float, misses: float, false_alarms: float) -> dict:
    div = lambda a, b: float(a / b) if b else float("nan")
    return {"pod": div(hits, hits + misses), "far": div(false_alarms, hits + false_alarms),
            "csi": div(hits, hits + misses + false_alarms)}


def evaluate(split: Split, pred: np.ndarray) -> dict:
    y = split.y
    out = {"n": len(y), "mae": float(np.abs(pred - y).mean()), "rmse": float(np.sqrt(((pred - y) ** 2).mean())),
           "bias": float((pred - y).mean())}
    for thr in THRESHOLDS:
        out[f"thr_{thr}"] = {**scores(*contingency(y, pred, thr)), "obs_rate": float((y >= thr).mean())}
    heavy = y >= np.percentile(y, 99)                                      # 상위 1% (꼬리)
    out["tail_top1pct"] = {"threshold_mmph": float(np.percentile(y, 99)),
                           "mae": float(np.abs(pred[heavy] - y[heavy]).mean()) if heavy.any() else float("nan")}
    return out


def daily_counts(split: Split, pred: np.ndarray, thr: float) -> tuple[np.ndarray, np.ndarray]:
    """일 단위 (적중, 놓침, 헛경보) 개수 → (일 목록, (일수, 3)). 블록 부트스트랩 입력."""
    days, inv = np.unique(split.day, return_inverse=True)
    obs, fc = split.y >= thr, pred >= thr
    counts = np.zeros((len(days), 3), dtype=np.int64)
    for j, mask in enumerate((obs & fc, obs & ~fc, ~obs & fc)):
        counts[:, j] = np.bincount(inv, weights=mask, minlength=len(days))
    return days, counts


def bootstrap_csi(counts_a: np.ndarray, counts_b: np.ndarray, n_boot: int = 1000, seed: int = 0) -> dict:
    """같은 날짜를 다시 뽑아(블록 부트스트랩) 모델 A, B 의 CSI 와 A−B 의 95% 구간을 낸다.
    같은 날씨 사례를 함께 뽑으므로 두 모델의 차이를 짝지어 비교한다."""
    rng = np.random.default_rng(seed)
    n = len(counts_a)
    idx = rng.integers(0, n, size=(n_boot, n))
    csi = lambda c: c[..., 0].sum(-1) / np.maximum(c.sum(-1).sum(-1), 1)
    a, b = csi(counts_a[idx]), csi(counts_b[idx])
    pct = lambda v: [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]
    d = a - b
    return {"a": pct(a), "b": pct(b), "diff": pct(d), "diff_mean": float(d.mean()),
            "a_better_significant": bool(np.percentile(d, 2.5) > 0), "b_better_significant": bool(np.percentile(d, 97.5) < 0)}


# ── 학습 ─────────────────────────────────────────────────────────────────

XGB_PARAMS = {
    "objective": "reg:squarederror", "eval_metric": "rmse", "tree_method": "hist", "eta": 0.05, "max_depth": 6,
    "min_child_weight": 3, "subsample": 0.8, "colsample_bytree": 0.8, "lambda": 1.0, "nthread": 8, "seed": 777,
}


def train_xgb(train: Split, val: Split, rounds: int = 600, early_stopping: int = 30, params: dict | None = None):
    import xgboost as xgb

    dtrain = xgb.DMatrix(train.X, label=train.y, feature_names=FEATURE_NAMES)
    dval = xgb.DMatrix(val.X, label=val.y, feature_names=FEATURE_NAMES)
    booster = xgb.train({**XGB_PARAMS, **(params or {})}, dtrain, num_boost_round=rounds,
                        evals=[(dval, "val")], early_stopping_rounds=early_stopping, verbose_eval=False)
    return booster


def predict_xgb(booster, split: Split) -> np.ndarray:
    import xgboost as xgb

    best = booster.best_iteration + 1 if hasattr(booster, "best_iteration") else None
    pred = booster.predict(xgb.DMatrix(split.X, feature_names=FEATURE_NAMES), iteration_range=(0, best) if best else (0, 0))
    return np.maximum(pred, 0.0).astype(np.float32)          # 강수는 음수일 수 없다

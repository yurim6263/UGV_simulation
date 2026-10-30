"""
backend/app/weather/dataset.py

ConvLSTM 기상 예측용 학습 자료: ERA5-Land 시간별(2018~2022) → (시간, 채널, 위도, 경도) 텐서.

채널(물리량): rain(mm/h, 누적 tp 를 푼 값), t2m(K), d2m(K), u10, v10(m/s), swvl1(m3/m3), sde(m, 적설 깊이)
  - 안개/시정은 ERA5-Land 에 없어서 예측하지 않는다. t2m, d2m, 바람 예측값에서 위험도 쪽이 추정한다 (scenario_index.fog 와 같은 규칙).
분할(시간 순, 팀 기상 분석과 같다): 학습 < 2022-01-01, 검증 2022-01-01 ~ 2022-07-01, 시험 >= 2022-07-01.
  → 시나리오(2022-08-20 22:00~)는 시험 구간이라 모델이 학습에도 검증에도 쓰지 않은 기간이다.

경로에 한글이 있으면 netCDF4 가 못 열어서 era5.open_month 가 ASCII 임시 경로로 복사해 읽는다.
원본(약 1.3GB, 월별 60개)은 저장소에 없다: 환경변수 WEATHER_ERA5_DIR (기본: final_project/ERA5_기상데이터_자료/ERA5_land).
읽은 결과는 backend/data/weather/cache/convlstm_region.npz 로 저장한다 (git 제외, 다시 만들 수 있다).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.weather.era5 import load_region, rain_rate_mm

BACKEND = Path(__file__).resolve().parents[2]
CACHE = BACKEND / "data" / "weather" / "cache" / "convlstm_region.npz"
CHANNELS = ("rain", "t2m", "d2m", "u10", "v10", "swvl1", "sde")
LAT_RANGE, LON_RANGE = (53.9, 54.9), (17.9, 19.0)       # 작전 구역(54.3~54.5N, 18.3~18.6E)을 가운데 두고 주변을 포함
TRAIN_END, VAL_END = np.datetime64("2022-01-01T00:00"), np.datetime64("2022-07-01T00:00")
LOOKBACK, HORIZON = 12, 3                                  # 지난 12시간을 보고 1~3시간 뒤를 예측한다 (팀 설계와 같은 길이)


def era5_dir() -> Path:
    default = BACKEND.parents[2] / "ERA5_기상데이터_자료" / "ERA5_land"
    return Path(os.getenv("WEATHER_ERA5_DIR") or default)


@dataclass
class Region:
    times: np.ndarray            # (T,) datetime64[h]
    lat: np.ndarray
    lon: np.ndarray
    data: np.ndarray             # (T, C, H, W) float32, 바다 칸은 NaN
    land: np.ndarray             # (H, W) bool

    def index_of(self, t) -> int:
        k = int(np.searchsorted(self.times, np.datetime64(t, "h")))
        if k >= len(self.times) or self.times[k] != np.datetime64(t, "h"):
            raise KeyError(f"자료에 없는 시각: {t}")
        return k


def build_region(directory: Path | None = None) -> Region:
    ds = load_region(directory or era5_dir(), LAT_RANGE, LON_RANGE, variables=("tp", "t2m", "d2m", "u10", "v10", "swvl1", "sde"))
    times = ds.valid_time.values.astype("datetime64[h]")
    get = lambda v: ds[v].transpose("valid_time", "latitude", "longitude").values.astype("float32")  # noqa: E731
    rain = rain_rate_mm(get("tp"), ds.valid_time.values)
    rain[0] = rain[1]                                       # 첫 시각은 앞 값이 없다
    sde = np.nan_to_num(get("sde"), nan=0.0) * np.isfinite(get("t2m"))     # 눈이 없으면 0 (바다는 아래에서 NaN 처리)
    data = np.stack([rain, get("t2m"), get("d2m"), get("u10"), get("v10"), get("swvl1"), sde], axis=1).astype("float32")
    land = np.isfinite(data[0, 1])
    data[:, :, ~land] = np.nan
    return Region(times, ds.latitude.values.astype(float), ds.longitude.values.astype(float), data, land)


def load_region_cached(rebuild: bool = False) -> Region:
    if CACHE.exists() and not rebuild:
        z = np.load(CACHE, allow_pickle=False)
        return Region(z["times"], z["lat"], z["lon"], z["data"], z["land"])
    reg = build_region()
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(CACHE, times=reg.times, lat=reg.lat, lon=reg.lon, data=reg.data, land=reg.land)
    return reg


def split_of(times: np.ndarray, t_index: int) -> str:
    """예측 대상이 아니라 '입력의 마지막 시각'(예측을 낸 시각) 기준이 아니라, 가장 먼 예측 시각(t+HORIZON)으로 나눈다 (경계에서 누수가 없도록)."""
    t = times[t_index + HORIZON]
    return "train" if t < TRAIN_END else "val" if t < VAL_END else "test"


def time_features(times: np.ndarray) -> np.ndarray:
    """(T, 4) 시각 sin/cos, 연중 일 sin/cos (UTC)."""
    h = (times - times.astype("datetime64[D]")).astype("timedelta64[h]").astype(int)
    doy = (times.astype("datetime64[D]") - times.astype("datetime64[Y]")).astype(int)
    return np.stack([np.sin(2 * np.pi * h / 24), np.cos(2 * np.pi * h / 24), np.sin(2 * np.pi * doy / 365.25), np.cos(2 * np.pi * doy / 365.25)], axis=1).astype("float32")


class Normalizer:
    """채널별 변환과 표준화. 강수는 log1p(mm/h) 로 바꾼 뒤 표준화한다 (꼬리가 길어서). 통계는 학습 구간에서만 구한다."""

    def __init__(self, mean: np.ndarray, std: np.ndarray):
        self.mean, self.std = mean.astype("float32"), np.maximum(std, 1e-6).astype("float32")

    @staticmethod
    def transform(x: np.ndarray) -> np.ndarray:
        x = x.copy()
        x[:, 0] = np.log1p(np.maximum(x[:, 0], 0.0))
        return x

    @classmethod
    def fit(cls, data: np.ndarray, train_hours: int) -> "Normalizer":
        x = cls.transform(data[:train_hours])
        return cls(np.nanmean(x, axis=(0, 2, 3)), np.nanstd(x, axis=(0, 2, 3)))

    def encode(self, data: np.ndarray) -> np.ndarray:
        x = (self.transform(data) - self.mean[None, :, None, None]) / self.std[None, :, None, None]
        return np.nan_to_num(x, nan=0.0).astype("float32")

    def decode(self, z: np.ndarray) -> np.ndarray:
        x = z * self.std[..., :, None, None] + self.mean[..., :, None, None]
        x[..., 0, :, :] = np.maximum(np.expm1(x[..., 0, :, :]), 0.0)
        x[..., 5, :, :] = np.clip(x[..., 5, :, :], 0.0, 1.0)             # 토양수분
        x[..., 6, :, :] = np.maximum(x[..., 6, :, :], 0.0)               # 적설
        return x

    def to_dict(self) -> dict:
        return {"mean": self.mean.tolist(), "std": self.std.tolist(), "channels": list(CHANNELS)}


def window_starts(times: np.ndarray, which: str) -> np.ndarray:
    """입력 12시간 + 예측 3시간 창의 시작 인덱스 중 분할(which)에 속하는 것. 시간축이 연속(1시간 간격)이라고 가정한다."""
    n = len(times) - LOOKBACK - HORIZON + 1
    ok = [s for s in range(n) if split_of(times, s + LOOKBACK - 1) == which]
    return np.array(ok, dtype=int)

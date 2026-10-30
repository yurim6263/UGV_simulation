"""
backend/app/weather/era5.py

ERA5-Land 월별 NetCDF 로더와 강수량(tp) 전처리.

주의 1) 경로에 한글이 있으면 netCDF4 가 파일을 열지 못한다(`[Errno 22] Invalid argument`).
        ASCII 임시 경로로 복사해서 연다 (파일당 약 20MB).
주의 2) ERA5-Land 의 tp 는 "UTC 0시부터의 누적값"이다. 값이 하루 안에서 늘어나다가 UTC 01시에 초기화된다
        (00시 값은 전날 24시간 합계). 한 시간 강수량 = 누적값의 차이이며, 초기화는 01시에만 일어난다.
        그 외 시각에 누적값이 아주 조금 줄어드는 것은 부동소수점 오차이므로 0 으로 둔다.
"""

from __future__ import annotations

import glob
import os
import shutil
import tempfile
from pathlib import Path

import numpy as np
import xarray as xr

VARIABLES = ("tp", "t2m", "d2m", "u10", "v10", "swvl1", "sde")


def list_month_files(directory: str | Path) -> list[Path]:
    """ERA5_land_YYYY_MM.nc 월별 파일 (연간 합본 *_all.nc 는 제외)."""
    files = sorted(Path(p) for p in glob.glob(str(Path(directory) / "ERA5_land_????_??.nc")))
    if not files:
        raise FileNotFoundError(f"ERA5 월별 파일이 없습니다: {directory}")
    return files


def open_month(path: str | Path, variables=VARIABLES, lat=None, lon=None) -> xr.Dataset:
    """월별 파일 하나를 메모리로 읽는다. lat/lon 은 (최소, 최대) 범위로 자른다."""
    tmp = os.path.join(tempfile.gettempdir(), f"era5_{os.getpid()}_{Path(path).name}")
    shutil.copy(path, tmp)
    try:
        with xr.open_dataset(tmp) as ds:
            ds = ds[list(variables)]
            if lat is not None:
                ds = ds.sel(latitude=slice(lat[1], lat[0]))           # 위도는 큰 값부터 정렬되어 있다
            if lon is not None:
                ds = ds.sel(longitude=slice(lon[0], lon[1]))
            return ds.astype("float32").load()
    finally:
        os.remove(tmp)


def load_region(directory: str | Path, lat: tuple[float, float], lon: tuple[float, float],
                variables=VARIABLES, years: tuple[int, int] | None = None) -> xr.Dataset:
    """여러 달을 이어 붙인 지역 데이터 (valid_time 으로 정렬). 달마다 지역을 먼저 잘라 메모리를 아낀다."""
    parts = []
    for f in list_month_files(directory):
        year = int(f.stem.split("_")[2])
        if years and not (years[0] <= year <= years[1]):
            continue
        parts.append(open_month(f, variables, lat, lon))
    ds = xr.concat(parts, dim="valid_time").sortby("valid_time")
    assert_hourly(ds.valid_time.values)
    return ds


def assert_hourly(times: np.ndarray) -> None:
    """시간축이 빠짐없이 1시간 간격인지 확인한다 (빠지면 지연(lag) 특징이 잘못된다)."""
    gaps = np.diff(times) != np.timedelta64(1, "h")
    if gaps.any():
        i = int(np.argmax(gaps))
        raise ValueError(f"시간축이 연속되지 않습니다: {times[i]} -> {times[i + 1]} (끊김 {int(gaps.sum())}곳)")


def rain_rate_mm(tp_m: np.ndarray, times: np.ndarray) -> np.ndarray:
    """누적 강수 tp(m, 시간 x ...) → 시간당 강수량(mm/h). 첫 시각은 앞 값이 없어 NaN.

    초기화는 UTC 01시에만 일어난다고 본다. 그 외에 누적값이 줄어든 것은 부동소수점 오차이므로 0 으로 둔다.
    """
    hours = (times.astype("datetime64[h]") - times.astype("datetime64[D]")).astype(int)
    out = np.empty_like(tp_m, dtype=np.float32)
    out[0] = np.nan
    diff = tp_m[1:] - tp_m[:-1]
    reset = (hours[1:] == 1).reshape((-1,) + (1,) * (tp_m.ndim - 1))
    out[1:] = np.where(reset, tp_m[1:], np.maximum(diff, 0.0)) * 1000.0
    return out


def rain_rate_team_rule_mm(tp_m: np.ndarray) -> np.ndarray:
    """팀원 노트북의 규칙(`diff >= 0 이면 diff, 아니면 그 시각의 누적값`) — 비교용. 첫 시각은 NaN."""
    out = np.empty_like(tp_m, dtype=np.float32)
    out[0] = np.nan
    diff = tp_m[1:] - tp_m[:-1]
    out[1:] = np.where(diff >= 0, diff, tp_m[1:]) * 1000.0
    return np.maximum(out, 0.0)


def compare_deaccumulation(tp_m: np.ndarray, times: np.ndarray) -> dict:
    """두 규칙의 차이를 요약한다 (어느 쪽이 맞는지는 초기화 시각과 물리 한계로 판단)."""
    right = rain_rate_mm(tp_m, times)
    team = rain_rate_team_rule_mm(tp_m)
    valid = ~np.isnan(right)
    d = (team - right)[valid]
    spurious = d > 0.01                       # 팀 규칙이 0.01mm/h 넘게 더 크게 만든 시각
    hours = (times.astype("datetime64[h]") - times.astype("datetime64[D]")).astype(int)
    not_reset_hour = np.broadcast_to((hours != 1).reshape((-1,) + (1,) * (tp_m.ndim - 1)), tp_m.shape)[valid]
    return {
        "samples": int(valid.sum()),
        "spurious_hours": int(spurious.sum()),
        "spurious_share_pct": round(100 * float(spurious.mean()), 3),
        "spurious_outside_reset_hour": int((spurious & not_reset_hour).sum()),
        "max_mmph_team_rule": round(float(np.nanmax(team)), 3),
        "max_mmph_correct": round(float(np.nanmax(right)), 3),
        "total_mm_team_rule": round(float(np.nansum(team)), 1),
        "total_mm_correct": round(float(np.nansum(right)), 1),
        "hours_over_10mmph_team_rule": int((team[valid] > 10).sum()),
        "hours_over_10mmph_correct": int((right[valid] > 10).sum()),
    }

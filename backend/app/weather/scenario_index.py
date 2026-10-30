"""
backend/app/weather/scenario_index.py

"기상 악영향" 지표: 강수, 안개 가능성, 토양수분, 바람을 하나(0~1)로 합쳐 지도에 올린다.
원시 기상은 ERA5-Land(0.1°, 시간별)에서 온다. 위험도 격자(`normalized_c_total` 등)에는 원시 기상 값이 없다.

이 지표는 **측정값이 아니라 가정이 들어간 추정**이다. 화면과 문서에 같은 한계를 적는다.
  - 가중치(WEIGHTS)와 풍속 기준(WIND_FULL_MS)은 근거 없는 가정값이다 (보정하지 않았다). 강수/토양수분은 LTWR 과 같은 곡선(app/weather/curves.py)을 쓴다.
  - 안개/시정은 ERA5-Land 에 없다. 팀 노트북의 로지스틱 식(app/weather/fog.py: 이슬점 차, 풍속, 최근 3시간 강수)으로 안개 확률을 추정한다.
  - ERA5-Land 는 0.1°(약 11km x 6km) 격자라 20km 작전 구역에 2~4칸이다. 작전 구역 격자(200m)로는 선형 보간한 값이며,
    보간은 정보를 늘리지 않는다 (거친 값이 부드럽게 보일 뿐이다). 바다 칸은 ERA5-Land 에 값이 없어 가장 가까운 육지 값으로 채운다.
  - 지형의 영향은 들어 있지 않다 (순수 기상). 위험도(c_mob/c_sen)와의 관계는 `scripts/check_weather_alignment.py` 로 시간 변화를 비교해 볼 수 있다.
  - 시나리오 시각을 UTC 로 간주한다 (`WEATHER_UTC_OFFSET_H` 로 조정). 기본 시나리오(2022-08-20 22:00 UTC~)의 위험도 레이어는 같은 ERA5 로 우리가 직접
    만들었으므로(scripts/build_ltwr_layers.py) 날짜가 어긋날 일이 없다. (팀 원본 데이터 map_20km 는 날짜 표기가 엇갈려 확인되지 않았다.)

자료 파일: `backend/data/weather/era5_scenario.nc` (`WEATHER_ERA5_PATH` 로 바꿀 수 있다). 기본 파일은 ERA5-Land 2022-08-19~21 의 이 지역 조각이다
(scripts/extract_era5_scenario.py 로 월별 파일에서 만든다, 작아서 git 에 둔다). 없으면 지표를 만들지 않고 이유를 알린다 (다른 날의 값으로 대신하지 않는다).
"""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import xarray as xr
from scipy.interpolate import RegularGridInterpolator
from scipy.ndimage import distance_transform_edt

from app.weather.curves import curve
from app.weather.era5 import assert_hourly, rain_rate_mm
from app.weather.fog import fog_probability, wet_3h

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "weather" / "era5_scenario.nc"
VARIABLES = ("tp", "t2m", "d2m", "u10", "v10", "swvl1")

# ── 가정값 (보정하지 않았다) ─────────────────────────────────────────────
WEIGHTS = {"rain": 0.4, "fog": 0.3, "soil": 0.2, "wind": 0.1}
WIND_FULL_MS = 15.0                        # 이 이상이면 바람 요인 1
NOTES = [
    "측정값이 아니라 가정이 들어간 추정입니다 (가중치와 풍속 기준은 보정하지 않은 가정값, 강수/토양수분 곡선은 팀 노트북 강수 임계 구간 기준).",
    "안개/시정은 ERA5-Land에 없어 이슬점 차, 풍속, 최근 3시간 강수로 안개 확률을 구하는 팀 노트북의 로지스틱 식으로 추정했습니다.",
    "ERA5-Land는 0.1도(약 11km x 6km) 격자입니다. 작전 구역에는 2~4칸이고, 지도는 이를 선형 보간한 값이라 세부 위치별 차이를 말해 주지 않습니다.",
    "지형의 영향은 들어 있지 않습니다 (순수 기상). 위험도와 같은 척도가 아닙니다.",
]


class WeatherUnavailable(Exception):
    """자료가 없거나 시나리오 시각을 덮지 못할 때. 메시지는 사용자에게 그대로 보여 준다."""


def data_path() -> Path:
    return Path(os.getenv("WEATHER_ERA5_PATH") or DEFAULT_PATH)


def utc_offset_h() -> float:
    return float(os.getenv("WEATHER_UTC_OFFSET_H", "0"))


# ── 요인 계산 (격자 위에서, 모두 0~1) ────────────────────────────────────

def components(rain_mmph, t2m_k, d2m_k, u10, v10, swvl1, wet=0.0) -> dict[str, np.ndarray]:
    wind = np.hypot(u10, v10)
    depression = np.maximum(t2m_k - d2m_k, 0.0)
    rain = curve("rain", rain_mmph)
    wind01 = np.clip(wind / WIND_FULL_MS, 0.0, 1.0)
    soil = curve("soil", swvl1)
    fog = fog_probability(t2m_k, d2m_k, wind, wet)
    index = WEIGHTS["rain"] * rain + WEIGHTS["fog"] * fog + WEIGHTS["soil"] * soil + WEIGHTS["wind"] * wind01
    return {"rain": rain, "fog": fog, "soil": soil, "wind": wind01, "index": index,
            "rain_mmph": rain_mmph, "depression_k": depression, "wind_ms": wind, "soil_m3m3": swvl1}


def fill_nearest(arr: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """마지막 두 축(위도, 경도)에서 값이 없는 칸을 가장 가까운 값 있는 칸으로 채운다. valid 는 (ny, nx) 불리언."""
    if valid.all():
        return arr
    if not valid.any():
        raise WeatherUnavailable("ERA5 자료에 값이 있는 칸이 없습니다.")
    iy, ix = distance_transform_edt(~valid, return_distances=False, return_indices=True)
    return arr[..., iy, ix]


class ScenarioWeather:
    """시나리오 시각(턴)별 기상 지표. 자료는 시간별이고, 턴(10분)은 앞뒤 시각을 선형 보간한다."""

    def __init__(self, ds: xr.Dataset, start_time: datetime, offset_h: float = 0.0, source: str = ""):
        times = ds.valid_time.values.astype("datetime64[ns]")
        assert_hourly(times)
        if len(times) < 3:
            raise WeatherUnavailable("ERA5 자료의 시각이 너무 적습니다.")
        self.times = times
        self.start_time = start_time
        self.offset_h = offset_h
        self.source = source
        self.lat = ds.latitude.values.astype(float)
        self.lon = ds.longitude.values.astype(float)
        get = lambda v: ds[v].transpose("valid_time", "latitude", "longitude").values.astype("float32")  # noqa: E731
        valid = np.isfinite(get("t2m")[1])
        rain = rain_rate_mm(get("tp"), times)
        rain[0] = rain[1]                       # 첫 시각은 앞 값이 없어 NaN 이므로 바로 다음 값으로 둔다 (지표는 두 번째 시각부터만 쓴다)
        wet = wet_3h(rain, axis=0)               # 최근 3시간에 비가 있었는지 (안개 식의 젖음 항, 0/1)
        self.raw = {"rain": fill_nearest(rain, valid), "wet": fill_nearest(wet, valid), "t2m": fill_nearest(get("t2m"), valid), "d2m": fill_nearest(get("d2m"), valid),
                    "u10": fill_nearest(get("u10"), valid), "v10": fill_nearest(get("v10"), valid), "swvl1": fill_nearest(get("swvl1"), valid)}

    def utc_time(self, turn: int) -> np.datetime64:
        t = self.start_time + timedelta(minutes=10 * turn) - timedelta(hours=self.offset_h)
        return np.datetime64(t, "ns")

    def coverage(self) -> tuple[str, str]:
        return str(self.times[1])[:16], str(self.times[-1])[:16]

    def coarse(self, turn: int) -> dict[str, np.ndarray]:
        """원래(0.1°) 격자에서의 요인과 지표."""
        t = self.utc_time(turn)
        if t < self.times[1] or t > self.times[-1]:
            lo, hi = self.coverage()
            raise WeatherUnavailable(f"턴 {turn}의 시각(UTC {str(t)[:16]})이 ERA5 자료 범위(UTC {lo} ~ {hi}) 밖입니다.")
        k = int(np.searchsorted(self.times, t, side="right") - 1)
        k = min(k, len(self.times) - 2)
        w = float((t - self.times[k]) / (self.times[k + 1] - self.times[k]))
        mix = {name: (1 - w) * a[k] + w * a[k + 1] for name, a in self.raw.items()}
        return components(mix["rain"], mix["t2m"], mix["d2m"], mix["u10"], mix["v10"], mix["swvl1"], mix["wet"])

    def on_grid(self, turn: int, lat2d: np.ndarray, lon2d: np.ndarray) -> dict[str, np.ndarray]:
        """작전 구역 격자(200m)로 선형 보간한 요인과 지표."""
        coarse = self.coarse(turn)
        lat_idx = np.argsort(self.lat)                         # RegularGridInterpolator 는 오름차순 축이 필요하다
        pts = np.stack([lat2d.ravel(), lon2d.ravel()], axis=-1)
        out = {}
        for name in ("rain", "fog", "soil", "wind", "index"):
            f = RegularGridInterpolator((self.lat[lat_idx], self.lon), coarse[name][lat_idx], bounds_error=False, fill_value=None)
            out[name] = f(pts).reshape(lat2d.shape).astype("float32")
        return out

    def area_mean(self, turn: int) -> dict[str, float]:
        """작전 구역 위의 평균(원 격자 칸 기준). 화면의 요약과 시계열에 쓴다."""
        c = self.coarse(turn)
        return {k: round(float(np.mean(v)), 4) for k, v in c.items()}


def open_era5(path: Path) -> xr.Dataset:
    """한글 경로에서는 netCDF4 가 못 열어서 ASCII 임시 경로로 복사해 연다 (era5.py 와 같은 이유)."""
    if not Path(path).exists():
        raise WeatherUnavailable(
            f"원시 기상 자료가 없습니다 ({Path(path).name}). 시나리오 날짜의 ERA5-Land를 받아 backend/data/weather/ 에 두세요 "
            "(python scripts/download_era5_scenario.py --help).")
    tmp = os.path.join(tempfile.gettempdir(), f"era5_scn_{os.getpid()}.nc")
    shutil.copy(path, tmp)
    try:
        with xr.open_dataset(tmp) as ds:
            missing = [v for v in VARIABLES if v not in ds]
            if missing:
                raise WeatherUnavailable(f"ERA5 자료에 변수가 없습니다: {missing}")
            return ds[list(VARIABLES)].astype("float32").load()
    finally:
        os.remove(tmp)


_cache: dict[tuple, ScenarioWeather] = {}
_lock = threading.Lock()


def get_weather() -> ScenarioWeather:
    """파일이 바뀌면(수정 시각) 다시 읽는다. 없거나 맞지 않으면 WeatherUnavailable.

    이미지 API 는 동기 함수라 스레드 풀에서 동시에 불린다 (브라우저가 다음 턴 이미지를 미리 요청한다). 락이 없으면 한 스레드가 캐시를 비우는 사이
    다른 스레드가 키를 못 찾아 KeyError(500)가 난다 (실제로 났다).
    """
    from app.simulation.shared_env import get_environment

    path = data_path()
    key = (str(path), path.stat().st_mtime_ns if path.exists() else None, utc_offset_h())
    with _lock:
        hit = _cache.get(key)
        if hit is None:
            start = get_environment().start_time
            if start is None:
                raise WeatherUnavailable("시나리오 시작 시각을 알 수 없습니다.")
            hit = ScenarioWeather(open_era5(path), start, utc_offset_h(), source=f"ERA5-Land 0.1° 시간별 ({path.name})")
            _cache.clear()
            _cache[key] = hit
        return hit

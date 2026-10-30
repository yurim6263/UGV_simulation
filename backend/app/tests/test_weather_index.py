"""
backend/app/tests/test_weather_index.py

"기상 악영향" 지표 테스트. 손으로 계산할 수 있는 합성 ERA5 자료로 요인 식, 시간 대응, 보간, 자료 없음 처리를 확인한다.
(실제 ERA5 자료가 있다는 뜻이 아니다: 저장소에는 시나리오 날짜의 자료가 없다.)
"""

import io

import numpy as np
import pytest
import xarray as xr
from httpx import AsyncClient
from PIL import Image

from app.weather import scenario_index as si
from datetime import datetime

START = datetime(2023, 6, 30, 22, 0)          # 시나리오 시작(UTC 로 간주)


def era5(rates_mm: list[float], first_hour: str = "2023-06-30T20:00", *, t2m=290.0, d2m=289.0, wind=0.0, soil=0.30, sea_col=True) -> xr.Dataset:
    """시간별 합성 ERA5. rates_mm 는 시간당 강수(mm/h). tp 는 실제처럼 UTC 0시부터의 누적값(01시에 초기화)으로 만든다."""
    times = np.datetime64(first_hour) + np.arange(len(rates_mm)) * np.timedelta64(1, "h")
    lat = np.arange(54.7, 54.0, -0.1)
    lon = np.arange(18.0, 19.01, 0.1)
    acc, tp = 0.0, []
    for t, r in zip(times, rates_mm):
        hour = int((t - t.astype("datetime64[D]")) / np.timedelta64(1, "h"))
        acc = r / 1000 if hour == 1 else acc + r / 1000
        tp.append(acc)
    shape = (len(times), len(lat), len(lon))
    full = lambda v: np.full(shape, v, dtype="float32")  # noqa: E731
    ds = xr.Dataset(
        {"tp": (("valid_time", "latitude", "longitude"), np.broadcast_to(np.array(tp, dtype="float32")[:, None, None], shape).copy()),
         "t2m": (("valid_time", "latitude", "longitude"), full(t2m)), "d2m": (("valid_time", "latitude", "longitude"), full(d2m)),
         "u10": (("valid_time", "latitude", "longitude"), full(wind)), "v10": (("valid_time", "latitude", "longitude"), full(0.0)),
         "swvl1": (("valid_time", "latitude", "longitude"), full(soil))},
        coords={"valid_time": times, "latitude": lat, "longitude": lon},
    )
    if sea_col:                                    # ERA5-Land 는 바다 칸이 비어 있다
        ds = ds.where(ds.longitude < 18.95)
    return ds


# ── 요인 식 ──────────────────────────────────────────────────────────────

def test_weights_sum_to_one_so_the_index_stays_in_0_1():
    assert sum(si.WEIGHTS.values()) == pytest.approx(1.0)


def test_calm_dewpoint_saturated_air_gives_near_full_fog_and_no_rain_wind():
    c = si.components(np.array(0.0), np.array(290.0), np.array(290.0), np.array(0.0), np.array(0.0), np.array(0.15))
    assert float(c["fog"]) > 0.999 and float(c["rain"]) == 0 and float(c["wind"]) == 0 and float(c["soil"]) == 0
    assert float(c["index"]) == pytest.approx(si.WEIGHTS["fog"], abs=1e-3)


def test_wind_and_dry_air_reduce_fog_and_wet_hours_raise_it():
    calm = si.components(np.array(0.0), np.array(290.0), np.array(289.0), np.array(1.0), np.array(0.0), np.array(0.3))
    windy = si.components(np.array(0.0), np.array(290.0), np.array(289.0), np.array(8.0), np.array(0.0), np.array(0.3))
    dry = si.components(np.array(0.0), np.array(290.0), np.array(280.0), np.array(0.0), np.array(0.0), np.array(0.3))
    wet = si.components(np.array(0.0), np.array(290.0), np.array(289.0), np.array(1.0), np.array(0.0), np.array(0.3), wet=1.0)
    assert float(calm["fog"]) > float(windy["fog"]) and float(windy["fog"]) < 0.05 and float(dry["fog"]) < 0.01
    assert float(wet["fog"]) > float(calm["fog"])


def test_rain_and_soil_use_the_same_curves_as_ltwr():
    c = si.components(np.array(2.0), np.array(300.0), np.array(280.0), np.array(0.0), np.array(0.0), np.array(0.40))
    assert float(c["rain"]) == pytest.approx(0.35) and float(c["soil"]) == pytest.approx(0.6)            # curves.py 기준점
    heavy = si.components(np.array(50.0), np.array(300.0), np.array(300.0), np.array(30.0), np.array(0.0), np.array(0.9))
    assert float(heavy["rain"]) == 1 and float(heavy["wind"]) == 1 and float(heavy["soil"]) == 1
    assert float(heavy["index"]) == pytest.approx(si.WEIGHTS["rain"] + si.WEIGHTS["soil"] + si.WEIGHTS["wind"], abs=1e-3)    # 바람이 세서 안개는 0


def test_fill_nearest_fills_missing_cells_from_the_closest_valid_cell():
    a = np.array([[1.0, 2.0, np.nan], [4.0, 5.0, np.nan]], dtype="float32")
    filled = si.fill_nearest(a, np.isfinite(a))
    assert filled.tolist() == [[1.0, 2.0, 2.0], [4.0, 5.0, 5.0]]


# ── 시간 대응과 보간 ─────────────────────────────────────────────────────

def test_rain_rate_comes_from_the_accumulated_tp_and_is_interpolated_between_hours():
    w = si.ScenarioWeather(era5([0, 0, 0, 0.0, 2.0, 0.0, 0.0, 0.0, 0.0]), START)      # UTC 23시 = 인덱스 3, 00시 = 4... 아래에서 확인
    # 자료 시각: 20,21,22,23,00,01,02,03,04 (UTC). 강수 2mm/h 는 00시 한 시각.
    assert w.utc_time(0) == np.datetime64("2023-06-30T22:00")
    assert w.coarse(0)["rain_mmph"].max() == pytest.approx(0.0)
    mid = w.coarse(9)["rain_mmph"]                                      # 22:00 + 90분 = 23:30 → 23시(0)와 00시(2) 사이
    assert float(mid.mean()) == pytest.approx(1.0, abs=1e-4)
    assert float(w.coarse(12)["rain_mmph"].mean()) == pytest.approx(2.0, abs=1e-4)      # 00:00 정각


def test_utc_offset_shifts_the_scenario_clock_to_utc():
    w = si.ScenarioWeather(era5([0.0] * 9), START, offset_h=2.0)       # 시나리오 22:00 = UTC 20:00
    assert w.utc_time(0) == np.datetime64("2023-06-30T20:00")


def test_a_turn_outside_the_data_is_refused_with_the_range_in_the_message():
    w = si.ScenarioWeather(era5([0.0] * 5), START)                     # 자료: UTC 20~24시 → 두 번째 시각부터 21시 ~ 00시
    with pytest.raises(si.WeatherUnavailable, match="밖입니다"):
        w.coarse(30)
    assert w.coarse(0)["index"].shape == (8, 11)          # 합성 격자: 위도 8칸 x 경도 11칸


def test_grid_values_stay_within_0_1_and_sea_cells_are_filled():
    from app.simulation.algo.sim_config import SimAlgoConfig

    w = si.ScenarioWeather(era5([1.0] * 9), START)
    meta = SimAlgoConfig.meta()
    g = w.on_grid(0, np.asarray(meta.lat), np.asarray(meta.lon))["index"]
    assert g.shape == np.asarray(meta.lat).shape and np.isfinite(g).all()
    assert 0.0 <= float(g.min()) and float(g.max()) <= 1.0


# ── API: 자료가 없을 때와 있을 때 ────────────────────────────────────────

@pytest.mark.asyncio
async def test_without_data_the_api_says_why_and_never_invents_values(client: AsyncClient, monkeypatch, tmp_path):
    monkeypatch.setenv("WEATHER_ERA5_PATH", str(tmp_path / "missing.nc"))
    info = (await client.get("/api/map/weather/info")).json()
    assert info["available"] is False and "원시 기상 자료가 없습니다" in info["reason"]
    assert info["weights"] and info["notes"]                                  # 가정과 한계는 자료가 없어도 보여 준다
    assert (await client.get("/api/map/weather/0.png")).status_code == 404


@pytest.mark.asyncio
async def test_with_data_the_api_returns_turn_means_and_an_overlay_image(client: AsyncClient, monkeypatch, tmp_path):
    path = tmp_path / "era5.nc"
    era5([0, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12], first_hour="2022-08-20T20:00").to_netcdf(path)          # 기본 시나리오(2022-08-20 22:00 UTC~)를 덮는 합성 자료
    monkeypatch.setenv("WEATHER_ERA5_PATH", str(path))
    si._cache.clear()
    info = (await client.get("/api/map/weather/info")).json()
    assert info["available"] is True and len(info["turns"]) == 31
    first, last = info["turns"][0], info["turns"][-1]
    assert first is not None and last is not None and last["rain_mmph"] > first["rain_mmph"]          # 비가 점점 늘어나는 합성 자료
    assert 0 <= first["index"] <= 1 and "ERA5" in info["source"]
    png = await client.get("/api/map/weather/5.png")
    assert png.status_code == 200 and png.headers["content-type"] == "image/png"
    assert Image.open(io.BytesIO(png.content)).size == (111, 111)
    assert (await client.get("/api/map/weather/31.png")).status_code == 404                           # 실황 범위(0~30) 밖
    si._cache.clear()


@pytest.mark.asyncio
async def test_data_that_does_not_cover_the_scenario_time_is_reported_not_extrapolated(client: AsyncClient, monkeypatch, tmp_path):
    path = tmp_path / "other_day.nc"
    era5([0.0] * 10, first_hour="2022-06-30T20:00").to_netcdf(path)                                   # 다른 해
    monkeypatch.setenv("WEATHER_ERA5_PATH", str(path))
    si._cache.clear()
    info = (await client.get("/api/map/weather/info")).json()
    assert info["available"] is False and "덮지 않습니다" in info["reason"]
    assert (await client.get("/api/map/weather/0.png")).status_code == 404
    si._cache.clear()


def test_concurrent_first_loads_do_not_race_on_the_cache(monkeypatch, tmp_path):
    """브라우저가 여러 턴의 이미지를 동시에 요청해도 첫 로딩에서 KeyError 가 나지 않는다 (500 이 실제로 났다)."""
    import threading

    path = tmp_path / "era5.nc"
    era5([0.0] * 12, first_hour="2022-08-20T20:00").to_netcdf(path)
    monkeypatch.setenv("WEATHER_ERA5_PATH", str(path))
    si._cache.clear()
    errors, got = [], []

    def worker():
        try:
            got.append(si.get_weather())
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    si._cache.clear()
    assert not errors and len(got) == 8 and all(g is got[0] for g in got)          # 한 번만 읽고 같은 객체를 돌려준다

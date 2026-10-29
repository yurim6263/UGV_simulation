"""
backend/app/tests/test_forecast_map.py

예보 위험도 지도 API 테스트. 데이터는 실제 시나리오 파일이다 (발표 시각 22:00, 23:00, 00:00 세 개, 발표마다 3시간 분량).
핵심은 "예보가 없는 시각을 실황이나 지속성으로 채우지 않는다"와 "현재 시각에 이미 발표된 예보만 쓴다"이다.
"""

import io

import pytest
from httpx import AsyncClient
from PIL import Image

from app.tests.test_real_runner import MISSION, _two_team_run  # noqa: F401


@pytest.fixture(autouse=True)
def _fast_clear_weather(monkeypatch):
    monkeypatch.setenv("SIM_TICK_SLEEP", "0")
    monkeypatch.setenv("SIM_WEATHER_SCALE", "clear")


@pytest.mark.asyncio
async def test_forecast_info_uses_the_latest_forecast_issued_before_now(client: AsyncClient):
    first = (await client.get("/api/map/forecast-info", params={"turn": 0, "lead_min": 60})).json()
    assert first["available"] and first["model_time"].endswith("22:00:00") and first["target_time"].endswith("23:00:00")
    later = (await client.get("/api/map/forecast-info", params={"turn": 8, "lead_min": 60})).json()    # 23:20 → 23:00 발표
    assert later["model_time"].endswith("23:00:00") and later["target_time"].endswith("00:20:00") and later["available"]
    assert later["current_time"].endswith("23:20:00")


@pytest.mark.asyncio
async def test_forecast_beyond_the_issue_range_is_unavailable_not_filled_in(client: AsyncClient):
    out = (await client.get("/api/map/forecast-info", params={"turn": 30, "lead_min": 180})).json()
    assert out["available"] is False and "범위" in out["reason"]
    assert (await client.get("/api/map/forecast/total/30/180.png")).status_code == 404


@pytest.mark.asyncio
async def test_forecast_image_is_a_grid_sized_png_with_realistic_colors(client: AsyncClient):
    resp = await client.get("/api/map/forecast/total/0/60.png", params={"scale": 0.3})
    assert resp.status_code == 200 and resp.headers["content-type"] == "image/png"
    img = Image.open(io.BytesIO(resp.content))
    assert img.size == (111, 111) and img.mode == "RGBA"
    other = await client.get("/api/map/forecast/total/0/120.png", params={"scale": 0.3})
    assert other.content != resp.content                                   # 리드타임이 다르면 다른 예보
    assert (await client.get("/api/map/forecast/sensor/0/60.png", params={"scale": 0.3})).content != resp.content


@pytest.mark.asyncio
async def test_forecast_validates_arguments(client: AsyncClient):
    assert (await client.get("/api/map/forecast-info", params={"turn": 99, "lead_min": 60})).status_code == 404
    assert (await client.get("/api/map/forecast-info", params={"turn": 0, "lead_min": 65})).status_code == 422
    assert (await client.get("/api/map/forecast-info", params={"turn": 0, "lead_min": 240})).status_code == 422
    assert (await client.get("/api/map/forecast/humidity/0/60.png")).status_code == 422


@pytest.mark.asyncio
async def test_replay_scenario_carries_the_data_start_time(auth_client: AsyncClient):
    _, run_id = await _two_team_run(auth_client)
    await auth_client.post(f"/api/runs/{run_id}/start")
    scenario = (await auth_client.get(f"/api/runs/{run_id}/replay")).json()["scenario"]
    from app.simulation.shared_env import get_environment
    assert scenario["start_time"] == get_environment().start_time.isoformat()          # 데이터(현재 데이터셋)의 첫 실황 시각
    assert scenario["start_time"] == "2022-08-20T22:00:00"                              # 기본 데이터셋: 2022-08-20 22시 사례 (MAP20KM_DIR=map_20km 이면 2023-06-30)


@pytest.mark.asyncio
async def test_forecast_info_compares_grade_shares_of_forecast_and_actual_at_the_target_time(client: AsyncClient):
    out = (await client.get("/api/map/forecast-info", params={"turn": 5, "lead_min": 60, "scale": 0.3})).json()
    for key in ("forecast_share", "actual_share"):
        assert set(out[key]) == {"G", "A", "R"} and sum(out[key].values()) == pytest.approx(1.0)
    # 저장소 예보는 위험을 낮게 본다 (기상 모델 보고서): 같은 시각 실황보다 고위험(R) 비율이 훨씬 낮다
    assert abs(out["forecast_share"]["R"] - out["actual_share"]["R"]) > 0.05         # 예보가 같은 시각 실황을 그대로 베끼지 않는다 (방향은 데이터에 따라 다르다)
    none = (await client.get("/api/map/forecast-info", params={"turn": 30, "lead_min": 180})).json()
    assert none["forecast_share"] is None and none["actual_share"] is None
    last = (await client.get("/api/map/forecast-info", params={"turn": 29, "lead_min": 0, "scale": 0.3})).json()
    assert last["available"] and last["forecast_share"] and last["actual_share"]       # 발표 범위의 끝(02:50)까지는 비교할 수 있다


def test_grades_are_ranked_within_each_time_slice_not_across_the_whole_scenario():
    """전 시간대를 한 줄로 세우면 위험도가 시간에 따라 내려가는 시나리오에서 초반은 전부 R, 후반은 전부 G 가 된다 (색이 위치가 아니라 시각을 보여 줌)."""
    import numpy as np

    from app.api import replay as r
    from app.simulation.algo.episode import risk_thresholds
    from app.simulation.shared_env import get_environment

    env = get_environment()
    grids, thr = r._overlay_setup("total", 0.3)
    ok = ~np.asarray(env.blocked)
    for t in (0, 10, 20, 30):
        g = grids[t][ok & np.isfinite(grids[t])]
        lo, hi = thr[t]
        shares = (float((g <= lo).mean()), float(((g > lo) & (g <= hi)).mean()), float((g > hi).mean()))
        assert shares == pytest.approx((0.30, 0.40, 0.30), abs=0.02), (t, shares)               # 매 시점 30/40/30
    assert thr[0][0] != thr[30][0] and thr[0][1] != thr[30][1]                                  # 경계는 시점마다 다르다
    from datetime import timedelta
    assert risk_thresholds(env, env.start_time) != risk_thresholds(env, env.start_time + timedelta(minutes=300))   # 시뮬레이션 기록의 등급도 같은 기준

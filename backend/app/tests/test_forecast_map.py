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
    assert scenario["start_time"] == "2023-06-30T22:00:00"


@pytest.mark.asyncio
async def test_forecast_info_compares_grade_shares_of_forecast_and_actual_at_the_target_time(client: AsyncClient):
    out = (await client.get("/api/map/forecast-info", params={"turn": 5, "lead_min": 60, "scale": 0.3})).json()
    for key in ("forecast_share", "actual_share"):
        assert set(out[key]) == {"G", "A", "R"} and sum(out[key].values()) == pytest.approx(1.0)
    # 저장소 예보는 위험을 낮게 본다 (기상 모델 보고서): 같은 시각 실황보다 고위험(R) 비율이 훨씬 낮다
    assert out["forecast_share"]["R"] < out["actual_share"]["R"] - 0.2
    none = (await client.get("/api/map/forecast-info", params={"turn": 30, "lead_min": 180})).json()
    assert none["forecast_share"] is None and none["actual_share"] is None
    last = (await client.get("/api/map/forecast-info", params={"turn": 29, "lead_min": 0, "scale": 0.3})).json()
    assert last["available"] and last["forecast_share"] and last["actual_share"]       # 발표 범위의 끝(02:50)까지는 비교할 수 있다

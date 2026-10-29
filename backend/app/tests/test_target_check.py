"""
backend/app/tests/test_target_check.py

정찰 목표 위치 검사: 수역이나 고립된 땅을 목표로 받으면 그 제대는 NO_PATH 로 출발지에서 움직이지 않는다 (실제로 겪은 버그).
"""

import pytest
from httpx import AsyncClient

from app.assistant.mission_intent import validate_proposal
from app.simulation.target_check import check_target

LAND = (54.40, 18.54)                      # 팀 기본 목표 1 (육지)
WATER = (54.32261, 18.30461)               # 지도 남서쪽 모서리의 호수 (실제로 목표로 입력되어 2제대가 움직이지 못했다)


def test_land_is_accepted_and_water_is_rejected_with_a_reason():
    assert check_target(*LAND) is None
    reason = check_target(*WATER)
    assert reason and "수역" in reason


def test_out_of_area_is_rejected():
    assert "작전 구역 밖" in check_target(37.5, 127.0)


@pytest.mark.asyncio
async def test_posting_a_water_target_is_refused_with_the_target_number(auth_client: AsyncClient, mission_id: int):
    body = [{"seq": 1, "lat": LAND[0], "lon": LAND[1], "patrol_duration_sec": 600},
            {"seq": 2, "lat": WATER[0], "lon": WATER[1], "patrol_duration_sec": 600}]
    r = await auth_client.post(f"/api/missions/{mission_id}/targets", json=body)
    assert r.status_code == 422 and "목표 2" in r.json()["detail"] and "수역" in r.json()["detail"]
    ok = await auth_client.post(f"/api/missions/{mission_id}/targets", json=body[:1])
    assert ok.status_code == 201


@pytest.mark.asyncio
async def test_target_check_endpoint_is_public_and_reports_reasons(client: AsyncClient):
    good = (await client.get("/api/map/tactical/target-check", params={"lat": LAND[0], "lng": LAND[1]})).json()
    bad = (await client.get("/api/map/tactical/target-check", params={"lat": WATER[0], "lng": WATER[1]})).json()
    assert good == {"ok": True, "reason": None} and bad["ok"] is False and "수역" in bad["reason"]


def test_ai_proposal_with_a_water_target_is_rejected():
    targets, _, error = validate_proposal({"targets": [{"team": 1, "lat": WATER[0], "lon": WATER[1], "recon_minutes": 30}]})
    assert targets is None and error and "수역" in error
    ok, _, err = validate_proposal({"targets": [{"team": 1, "lat": LAND[0], "lon": LAND[1], "recon_minutes": 30}]})
    assert err is None and len(ok) == 1

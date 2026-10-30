"""
backend/app/tests/test_missions.py

임무 CRUD 테스트.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_mission(auth_client: AsyncClient):
    resp = await auth_client.post(
        "/api/missions",
        json={
            "name": "테스트 임무",
            "total_ugv": 3,
            "max_ugv_count": 5,
            "mission_duration_min": 120,
            "departure_lat": 37.5,
            "departure_lon": 127.0,
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "테스트 임무"
    assert data["status"] == "DRAFT"


@pytest.mark.asyncio
async def test_get_mission_not_found(auth_client: AsyncClient):
    resp = await auth_client.get("/api/missions/99999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_set_targets(auth_client: AsyncClient, mission_id: int):
    resp = await auth_client.post(
        f"/api/missions/{mission_id}/targets",
        json=[
            {"seq": 1, "lat": 54.40, "lon": 18.54},        # 작전 구역(그단스크 인근)의 육지여야 한다 (수역/구역 밖은 422)
            {"seq": 2, "lat": 54.33, "lon": 18.36},
        ],
    )
    assert resp.status_code == 201
    assert len(resp.json()) == 2

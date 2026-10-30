"""
backend/app/tests/test_authorization.py

역할/제대별 접근 제어 테스트.
"""

import pytest
from fastapi import HTTPException
from httpx import AsyncClient

from app.api.deps import echelon_of
from app.core.security import TokenPayload


# ── echelon_of ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("unit,expected", [("1제대", 1), ("2제대", 2), ("3제대", 3), (" 3제대", 3)])
def test_echelon_comes_from_the_unit_claim_not_from_the_user_id(unit, expected):
    # user1 은 DB id 가 2 이다. 예전에는 sub 의 마지막 자리(2)를 제대 번호로 잘못 썼다.
    assert echelon_of(TokenPayload(sub="2", role="operator", unit=unit)) == expected


@pytest.mark.parametrize("unit", [None, "", "미지정"])
def test_missing_unit_is_rejected_instead_of_guessing(unit):
    with pytest.raises(HTTPException) as exc:
        echelon_of(TokenPayload(sub="1", role="operator", unit=unit))
    assert exc.value.status_code == 403


# ── 대시보드: 통제관 브리핑 ──────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("username,unit_label", [("user1", "1제대"), ("user2", "2제대"), ("user3", "3제대")])
async def test_operator_briefing_is_for_the_logged_in_operators_unit(login_as, run_id, username, unit_label):
    c = await login_as(username)
    resp = await c.get(f"/api/runs/{run_id}/operator/briefing")
    assert resp.status_code == 200, resp.text
    assert resp.json()["unit_label"] == unit_label


@pytest.mark.asyncio
async def test_commander_has_no_unit_so_operator_endpoints_refuse_instead_of_defaulting(auth_client, run_id):
    resp = await auth_client.get(f"/api/runs/{run_id}/operator/briefing")
    assert resp.status_code == 403


# ── 통제관 브리핑 API (operators) ────────────────────────────────────────

CONFIG = {
    "mode": "균형",
    "units": {
        "user1": {"success_rate": 80},
        "user2": {"success_rate": 60},
    },
}


@pytest.mark.asyncio
async def test_operator_cannot_read_another_units_briefing(auth_client: AsyncClient, login_as):
    assert (await auth_client.post("/api/operators/mission-config", json=CONFIG)).status_code == 200
    user2 = await login_as("user2")
    assert (await user2.get("/api/operators/user2/briefing")).status_code == 200
    other = await user2.get("/api/operators/user1/briefing")
    assert other.status_code == 403


@pytest.mark.asyncio
async def test_commander_can_read_any_units_briefing(auth_client: AsyncClient):
    assert (await auth_client.post("/api/operators/mission-config", json=CONFIG)).status_code == 200
    for username in ("user1", "user2"):
        assert (await auth_client.get(f"/api/operators/{username}/briefing")).status_code == 200


@pytest.mark.asyncio
async def test_only_commander_can_save_mission_config(login_as):
    user1 = await login_as("user1")
    assert (await user1.post("/api/operators/mission-config", json=CONFIG)).status_code == 403

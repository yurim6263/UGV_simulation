"""
backend/app/tests/test_auth.py

인증 엔드포인트 테스트.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient):
    resp = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "testpassword"},
    )
    assert resp.status_code == 200
    assert "access_token" in resp.json()


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient):
    resp = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "wrong"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_me_without_token(client: AsyncClient):
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_me_returns_role(auth_client: AsyncClient):
    resp = await auth_client.get("/api/auth/me")
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == "admin"
    assert body["role"] == "commander"


@pytest.mark.asyncio
async def test_default_operators_are_seeded_with_unit(client: AsyncClient):
    """통제관 3명(user1~3)이 담당 제대와 함께 시드되어야 한다."""
    for i in (1, 2, 3):
        login = await client.post(
            "/api/auth/login", json={"username": f"user{i}", "password": f"user{i}"}
        )
        assert login.status_code == 200
        me = await client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"}
        )
        assert me.json()["role"] == "operator"
        assert me.json()["assigned_unit"] == f"{i}제대"


@pytest.mark.asyncio
async def test_invalid_token_rejected(client: AsyncClient):
    resp = await client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"})
    assert resp.status_code == 401

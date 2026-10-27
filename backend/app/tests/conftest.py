"""
backend/app/tests/conftest.py

테스트 공통 fixture.

- DB: in-memory SQLite (aiosqlite). 운영 PostgreSQL 이 없어도 `pytest` 만으로 실행된다.
- app 을 import 하기 전에 환경변수를 지정해야 하므로, 아래 os.environ 설정은 반드시 import 보다 앞에 둔다.
- 각 테스트는 테이블을 새로 만들고 기본 계정(admin / user1~3)을 시드한 상태로 시작한다.
"""

import os

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-pytest-only-0123456789"
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "testpassword"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.core import rate_limit  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.init_db import init_db  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest_asyncio.fixture(autouse=True)
async def _fresh_database():
    """테스트마다 스키마를 새로 만들고 기본 계정을 시드한다."""
    import app.db.models  # noqa: F401 — Base.metadata 에 모든 모델 등록

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await init_db()

    # 로그인 rate limit / brute-force 잠금 상태가 테스트 간에 새지 않도록 초기화
    rate_limit.limiter.enabled = False
    rate_limit._failures.clear()
    rate_limit._locked_until.clear()
    yield


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _login(c: AsyncClient, username: str, password: str) -> str:
    resp = await c.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest_asyncio.fixture
async def auth_client(client: AsyncClient):
    """지휘관(admin) 로그인 상태의 client."""
    token = await _login(client, "admin", "testpassword")
    client.headers["Authorization"] = f"Bearer {token}"
    return client


@pytest_asyncio.fixture
async def operator_client():
    """통제관(user1) 로그인 상태의 별도 client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        token = await _login(c, "user1", "user1")
        c.headers["Authorization"] = f"Bearer {token}"
        yield c


@pytest_asyncio.fixture
async def mission_id(auth_client: AsyncClient) -> int:
    resp = await auth_client.post(
        "/api/missions",
        json={
            "name": "fixture 임무",
            "total_ugv": 3,
            "max_ugv_count": 5,
            "mission_duration_min": 120,
            "departure_lat": 54.48,
            "departure_lon": 18.32,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest_asyncio.fixture
async def run_id(auth_client: AsyncClient, mission_id: int) -> int:
    resp = await auth_client.post(f"/api/missions/{mission_id}/runs")
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest_asyncio.fixture
async def login_as():
    """원하는 계정으로 로그인한 client 를 만들어 주는 팩토리. 예: c = await login_as("user2")"""
    clients: list[AsyncClient] = []

    async def _login_as(username: str, password: str | None = None) -> AsyncClient:
        c = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        token = await _login(c, username, password or username)
        c.headers["Authorization"] = f"Bearer {token}"
        clients.append(c)
        return c

    yield _login_as
    for c in clients:
        await c.aclose()

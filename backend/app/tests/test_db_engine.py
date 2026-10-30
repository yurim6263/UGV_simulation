"""
backend/app/tests/test_db_engine.py

DB 엔진 선택 테스트: 메모리 SQLite 만 연결을 공유하고, 파일 SQLite 는 세션마다 연결을 쓴다.
"""

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.pool import StaticPool

from app.db.session import make_engine


def test_memory_sqlite_shares_one_connection_but_file_sqlite_does_not(tmp_path):
    assert isinstance(make_engine("sqlite+aiosqlite:///:memory:").pool, StaticPool)
    file_engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'x.db'}")
    assert not isinstance(file_engine.pool, StaticPool)


@pytest.mark.asyncio
async def test_concurrent_transactions_on_a_file_database_do_not_interfere(tmp_path):
    """모드 3개를 동시에 실행하면 세션 3개가 동시에 쓴다. 공유 연결이면 한 연결 위에서 트랜잭션이 엉켜 실패했다."""
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'concurrent.db'}")
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY, v INTEGER)"))

    async def writer(n: int):
        for i in range(25):
            async with engine.begin() as conn:
                await conn.execute(text("INSERT INTO t (v) VALUES (:v)"), {"v": n})
            await asyncio.sleep(0)

    await asyncio.gather(*(writer(n) for n in range(3)))
    async with engine.connect() as conn:
        assert (await conn.execute(text("SELECT COUNT(*) FROM t"))).scalar_one() == 75
    await engine.dispose()

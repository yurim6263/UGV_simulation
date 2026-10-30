"""
backend/app/db/session.py

AsyncSession 팩토리 + FastAPI 의존성 제공.
운영: PostgreSQL (DATABASE_URL = postgresql+asyncpg://...).
개발/테스트: SQLite (sqlite+aiosqlite://...).
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import settings


def make_engine(url: str) -> AsyncEngine:
    if not url.startswith("sqlite"):
        return create_async_engine(url, echo=False, pool_size=10, max_overflow=20)
    if ":memory:" in url or url.rstrip("/").endswith("sqlite+aiosqlite:"):
        # 메모리 DB 는 연결마다 별개의 DB 가 되므로 모든 세션이 하나의 연결을 공유해야 한다 (테스트용)
        return create_async_engine(
            url, echo=False, poolclass=StaticPool, connect_args={"check_same_thread": False},
        )
    # 파일 DB: 세션마다 자기 연결을 쓴다. 공유하면 동시에 실행되는 시뮬레이션(모드 3개)의 트랜잭션이
    # 한 연결 위에서 엉켜 "cannot commit transaction - SQL statements in progress" 가 난다.
    return create_async_engine(url, echo=False, connect_args={"timeout": 30})


engine = make_engine(settings.database_url)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 엔드포인트 DB 세션 의존성."""
    async with AsyncSessionLocal() as session:
        yield session

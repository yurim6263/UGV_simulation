"""
backend/app/db/session.py

AsyncSession 팩토리 + FastAPI 의존성 제공.
asyncpg 드라이버 사용 (DATABASE_URL = postgresql+asyncpg://...).
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

if settings.database_url.startswith("sqlite"):
    # 테스트용 SQLite(in-memory) — 모든 커넥션이 같은 DB 를 보도록 StaticPool 사용
    from sqlalchemy.pool import StaticPool

    engine = create_async_engine(
        settings.database_url,
        echo=False,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
else:
    engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_size=10,
        max_overflow=20,
    )

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 엔드포인트 DB 세션 의존성."""
    async with AsyncSessionLocal() as session:
        yield session

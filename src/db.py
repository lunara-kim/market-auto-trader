"""
데이터베이스 연결 및 세션 관리

SQLAlchemy 엔진과 세션 팩토리를 설정하고,
FastAPI 의존성 주입용 세션 제네레이터를 제공합니다.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config.settings import settings


def _build_async_url(url: str) -> str:
    """동기 DB URL을 asyncpg 드라이버용으로 변환"""
    return url.replace("postgresql://", "postgresql+asyncpg://", 1)


engine = create_async_engine(
    _build_async_url(settings.database_url),
    echo=(settings.app_env == "development"),
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI Depends용 DB 세션 제네레이터.

    사용법::

        @router.get("/items")
        async def list_items(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

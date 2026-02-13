"""
FastAPI 애플리케이션 엔트리포인트
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from config.settings import settings
from src.api.routes import router
from src.db import engine
from src.exceptions import register_exception_handlers
from src.utils.logger import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """애플리케이션 시작/종료 시 실행되는 로직"""
    # Startup
    logger.info("🚀 Market Auto Trader 시작 (환경: %s)", settings.app_env)
    db_host = settings.database_url.split("@")[-1] if "@" in settings.database_url else "unknown"
    logger.info("📊 데이터베이스: %s", db_host)

    yield

    # Shutdown
    await engine.dispose()
    logger.info("👋 Market Auto Trader 종료")


# FastAPI 앱 생성
app = FastAPI(
    title="Market Auto Trader",
    description="한국 주식 시장 자동매매 프로그램",
    version="0.2.0",
    lifespan=lifespan,
)

# 예외 핸들러 등록
register_exception_handlers(app)

# 라우터 등록
app.include_router(router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )

"""
FastAPI 애플리케이션 엔트리포인트
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from config.settings import settings
from src.api.orders import router as orders_router
from src.api.policies import router as policies_router
from src.api.portfolio import router as portfolio_router
from src.api.routes import router as base_router
from src.api.signals import router as signals_router
from src.db import engine
from src.exceptions import register_exception_handlers
from src.utils.logger import get_logger

logger = get_logger(__name__)


OPENAPI_TAGS = [
    {
        "name": "System",
        "description": "시스템 상태 확인",
    },
    {
        "name": "Portfolio",
        "description": "포트폴리오 조회 (보유종목, 계좌요약)",
    },
    {
        "name": "Orders",
        "description": "매매 주문 실행 및 주문 내역 조회",
    },
    {
        "name": "Signals",
        "description": "이동평균 교차 전략 기반 매매 신호 생성 및 조회",
    },
    {
        "name": "policies",
        "description": "원샷 매매 정책 실행 (국내/해외)",
    },
]


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
    description=(
        "한국 주식 시장 자동매매 프로그램 🐈‍⬛\n\n"
        "한국투자증권 OpenAPI를 활용한 자동 매매 시스템입니다.\n"
        "이동평균 교차 전략으로 매매 신호를 생성하고, "
        "포트폴리오를 관리합니다."
    ),
    version="0.3.0",
    openapi_tags=OPENAPI_TAGS,
    lifespan=lifespan,
)

# 예외 핸들러 등록
register_exception_handlers(app)

# 라우터 등록
app.include_router(base_router)
app.include_router(portfolio_router)
app.include_router(orders_router)
app.include_router(signals_router)
app.include_router(policies_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )

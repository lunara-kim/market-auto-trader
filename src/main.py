"""
FastAPI 애플리케이션 엔트리포인트
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from config.settings import settings
from src.api.routes import router
from src.utils.logger import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """애플리케이션 시작/종료 시 실행되는 로직"""
    # Startup
    logger.info(f"🚀 Market Auto Trader 시작 (환경: {settings.app_env})")
    logger.info(f"📊 데이터베이스: {settings.database_url.split('@')[-1]}")

    yield

    # Shutdown
    logger.info("👋 Market Auto Trader 종료")


# FastAPI 앱 생성
app = FastAPI(
    title="Market Auto Trader",
    description=(
        "한국 주식 시장 자동매매 프로그램\n\n"
        "한국투자증권 OpenAPI를 활용하여 시세 조회, 전략 기반 매매 신호 생성, "
        "자동 주문 실행을 수행합니다.\n\n"
        "## 주요 기능\n"
        "- 📊 실시간 시세 조회 및 과거 데이터 수집\n"
        "- 🤖 AI 기반 매매 전략 분석\n"
        "- 📈 자동 매수/매도 주문 실행\n"
        "- 💼 포트폴리오 관리 및 리스크 모니터링\n"
    ),
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_tags=[
        {
            "name": "System",
            "description": "서비스 상태 확인 및 시스템 관련 엔드포인트",
        },
        {
            "name": "Portfolio",
            "description": "포트폴리오 조회 및 관리",
        },
        {
            "name": "Signal",
            "description": "매매 신호 생성 및 조회",
        },
    ],
)

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

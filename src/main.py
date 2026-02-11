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
    description="한국 주식 시장 자동매매 프로그램",
    version="0.1.0",
    lifespan=lifespan
)

# 라우터 등록
app.include_router(router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )

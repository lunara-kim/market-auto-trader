"""
FastAPI 라우터 정의
"""

from fastapi import APIRouter

from config.settings import settings
from src.exceptions import NotFoundError

router = APIRouter()


@router.get("/health")
async def health_check():
    """헬스 체크 엔드포인트"""
    return {
        "status": "ok",
        "version": "0.2.0",
        "env": settings.app_env,
    }


@router.get("/api/v1/portfolio")
async def get_portfolio():
    """포트폴리오 조회 (구현 예정)"""
    raise NotFoundError(
        "포트폴리오 조회 기능은 아직 구현되지 않았습니다.",
        detail={"phase": 2, "status": "planned"},
    )


@router.post("/api/v1/signal")
async def create_signal():
    """매매 신호 생성 (구현 예정)"""
    raise NotFoundError(
        "매매 신호 생성 기능은 아직 구현되지 않았습니다.",
        detail={"phase": 2, "status": "planned"},
    )

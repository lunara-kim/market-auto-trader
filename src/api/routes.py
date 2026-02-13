"""
FastAPI 라우터 정의
"""

from fastapi import APIRouter, status

from config.settings import settings

router = APIRouter()


@router.get("/health")
async def health_check():
    """헬스 체크 엔드포인트"""
    return {"status": "ok", "env": settings.app_env}


@router.get("/api/v1/portfolio", status_code=status.HTTP_501_NOT_IMPLEMENTED)
async def get_portfolio():
    """포트폴리오 조회 (구현 예정)"""
    return {"message": "포트폴리오 조회 기능은 구현 예정입니다.", "status": "not_implemented"}


@router.post("/api/v1/signal", status_code=status.HTTP_501_NOT_IMPLEMENTED)
async def create_signal():
    """매매 신호 생성 (구현 예정)"""
    return {"message": "매매 신호 생성 기능은 구현 예정입니다.", "status": "not_implemented"}

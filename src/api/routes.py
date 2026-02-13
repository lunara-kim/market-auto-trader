"""
FastAPI 라우터 정의 — 기본 라우트 (헬스체크 등)
"""

from __future__ import annotations

from fastapi import APIRouter

from config.settings import settings
from src.api.schemas import HealthResponse
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["System"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="헬스 체크",
    description="서비스 상태 확인용 엔드포인트",
)
async def health_check() -> HealthResponse:
    """헬스 체크 엔드포인트"""
    return HealthResponse(
        status="ok",
        version="0.3.0",
        env=settings.app_env,
    )

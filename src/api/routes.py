"""
FastAPI 라우터 정의

API 엔드포인트별 요청/응답 스키마와 문서를 포함합니다.
"""

from pydantic import BaseModel, Field
from fastapi import APIRouter, status
from config.settings import settings

router = APIRouter()


# ── 응답 스키마 ────────────────────────────────────────────────

class HealthResponse(BaseModel):
    """헬스 체크 응답"""
    status: str = Field(..., description="서비스 상태", examples=["ok"])
    env: str = Field(..., description="실행 환경", examples=["development"])


class NotImplementedResponse(BaseModel):
    """미구현 엔드포인트 응답"""
    message: str = Field(..., description="안내 메시지")
    status: str = Field(
        default="not_implemented",
        description="구현 상태",
        examples=["not_implemented"],
    )


# ── 엔드포인트 ─────────────────────────────────────────────────

@router.get(
    "/health",
    response_model=HealthResponse,
    tags=["System"],
    summary="헬스 체크",
    description="서비스의 정상 동작 여부와 실행 환경을 반환합니다.",
)
async def health_check():
    """헬스 체크 엔드포인트"""
    return HealthResponse(status="ok", env=settings.app_env)


@router.get(
    "/api/v1/portfolio",
    response_model=NotImplementedResponse,
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    tags=["Portfolio"],
    summary="포트폴리오 조회",
    description="보유 종목, 평가금액, 예수금 등 포트폴리오 정보를 조회합니다. (구현 예정)",
)
async def get_portfolio():
    """포트폴리오 조회 (구현 예정)"""
    return NotImplementedResponse(
        message="포트폴리오 조회 기능은 구현 예정입니다.",
    )


@router.post(
    "/api/v1/signal",
    response_model=NotImplementedResponse,
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    tags=["Signal"],
    summary="매매 신호 생성",
    description="전략 분석 결과를 바탕으로 매수/매도/관망 신호를 생성합니다. (구현 예정)",
)
async def create_signal():
    """매매 신호 생성 (구현 예정)"""
    return NotImplementedResponse(
        message="매매 신호 생성 기능은 구현 예정입니다.",
    )

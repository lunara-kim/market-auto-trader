"""
종목 분석 API 엔드포인트

종목 스크리닝 및 유니버스 관리 API를 제공합니다.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.analysis.screener import ScreeningResult, StockScreener
from src.analysis.universe import UniverseManager
from src.api.dependencies import get_kis_client
from src.broker.kis_client import KISClient

router = APIRouter(prefix="/api/v1/analysis", tags=["Analysis"])

# 유니버스 매니저 (싱글턴)
_universe_manager = UniverseManager()


# ───────────────── Pydantic 스키마 ─────────────────


class ScreenRequest(BaseModel):
    """유니버스 일괄 스크리닝 요청"""

    stock_codes: list[str]


class FundamentalsResponse(BaseModel):
    """재무지표 응답"""

    stock_code: str
    stock_name: str
    per: float
    pbr: float
    roe: float
    dividend_yield: float
    operating_margin: float
    revenue_growth_yoy: float
    sector: str

    model_config = {"from_attributes": True}


class ScreeningResultResponse(BaseModel):
    """스크리닝 결과 응답"""

    stock_code: str
    stock_name: str
    quality: str
    quality_score: float
    reason: str
    eligible: bool
    fundamentals: FundamentalsResponse

    model_config = {"from_attributes": True}


class UniverseResponse(BaseModel):
    """유니버스 응답"""

    name: str
    stock_codes: list[str]
    description: str

    model_config = {"from_attributes": True}


# ───────────────── 헬퍼 ─────────────────


def _to_response(result: ScreeningResult) -> ScreeningResultResponse:
    f = result.fundamentals
    return ScreeningResultResponse(
        stock_code=result.stock_code,
        stock_name=result.stock_name,
        quality=result.quality,
        quality_score=result.quality_score,
        reason=result.reason,
        eligible=result.eligible,
        fundamentals=FundamentalsResponse(
            stock_code=f.stock_code,
            stock_name=f.stock_name,
            per=f.per,
            pbr=f.pbr,
            roe=f.roe,
            dividend_yield=f.dividend_yield,
            operating_margin=f.operating_margin,
            revenue_growth_yoy=f.revenue_growth_yoy,
            sector=f.sector,
        ),
    )


# ───────────────── 엔드포인트 ─────────────────


@router.get("/screen/{stock_code}", response_model=ScreeningResultResponse)
def screen_stock(
    stock_code: str,
    client: KISClient = Depends(get_kis_client),
) -> ScreeningResultResponse:
    """단일 종목 스크리닝"""
    screener = StockScreener(client)
    fundamentals = screener.get_fundamentals(stock_code)
    result = screener.evaluate_quality(fundamentals)
    return _to_response(result)


@router.post("/screen", response_model=list[ScreeningResultResponse])
def screen_universe(
    body: ScreenRequest,
    client: KISClient = Depends(get_kis_client),
) -> list[ScreeningResultResponse]:
    """유니버스 일괄 스크리닝"""
    screener = StockScreener(client)
    results = screener.screen_universe(body.stock_codes)
    return [_to_response(r) for r in results]


@router.get("/universe", response_model=list[UniverseResponse])
def list_universes() -> list[UniverseResponse]:
    """유니버스 목록 조회"""
    universes = _universe_manager.list_universes()
    return [
        UniverseResponse(
            name=u.name,
            stock_codes=u.stock_codes,
            description=u.description,
        )
        for u in universes
    ]

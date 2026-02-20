"""
시장 센티멘트 분석 API 엔드포인트
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.analysis.sentiment import (
    FearGreedIndex,
    HybridSentimentAnalyzer,
    MarketSentiment,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/analysis", tags=["Analysis"])

# 모듈 레벨 싱글턴 (캐싱 활용)
_fear_greed = FearGreedIndex()
_sentiment = MarketSentiment(fear_greed=_fear_greed)
_hybrid = HybridSentimentAnalyzer(fear_greed=_fear_greed)


class SentimentResponse(BaseModel):
    """센티멘트 API 응답"""

    score: int
    classification: str
    timestamp: str
    source: str
    buy_multiplier: float
    market_condition: str
    recommendation: str


class HybridSentimentResponse(BaseModel):
    """하이브리드 센티멘트 API 응답"""

    hybrid_score: float
    numeric_score: float
    news_score: float | None
    weights: dict[str, float]
    news_available: bool
    news_urgency: str | None
    fear_greed_raw_score: int
    fear_greed_classification: str


@router.get("/sentiment/hybrid", response_model=HybridSentimentResponse)
def get_hybrid_sentiment() -> HybridSentimentResponse:
    """하이브리드 센티멘트 조회 (수치 지표 + 뉴스 LLM)"""
    try:
        result = _hybrid.analyze()
    except Exception as exc:
        logger.error("하이브리드 센티멘트 분석 실패: %s", exc)
        raise HTTPException(
            status_code=502, detail="하이브리드 센티멘트 데이터 조회 실패"
        ) from exc

    return HybridSentimentResponse(
        hybrid_score=result.hybrid_score,
        numeric_score=result.numeric_score,
        news_score=result.news_score,
        weights=result.weights,
        news_available=result.news_available,
        news_urgency=result.news_urgency,
        fear_greed_raw_score=result.fear_greed_raw.score,
        fear_greed_classification=result.fear_greed_raw.classification,
    )


@router.get("/sentiment", response_model=SentimentResponse)
def get_sentiment() -> SentimentResponse:
    """현재 시장 센티멘트 조회"""
    try:
        result = _sentiment.analyze()
    except Exception as exc:
        logger.error("센티멘트 분석 실패: %s", exc)
        raise HTTPException(status_code=502, detail="센티멘트 데이터 조회 실패") from exc

    return SentimentResponse(
        score=result.fear_greed.score,
        classification=result.fear_greed.classification,
        timestamp=result.fear_greed.timestamp.isoformat(),
        source=result.fear_greed.source,
        buy_multiplier=result.buy_multiplier,
        market_condition=result.market_condition,
        recommendation=result.recommendation,
    )

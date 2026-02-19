"""
시장 센티멘트 분석 API 엔드포인트
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.analysis.sentiment import FearGreedIndex, MarketSentiment
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/analysis", tags=["Analysis"])

# 모듈 레벨 싱글턴 (캐싱 활용)
_fear_greed = FearGreedIndex()
_sentiment = MarketSentiment(fear_greed=_fear_greed)


class SentimentResponse(BaseModel):
    """센티멘트 API 응답"""

    score: int
    classification: str
    timestamp: str
    source: str
    buy_multiplier: float
    market_condition: str
    recommendation: str


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

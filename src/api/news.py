"""
뉴스 센티멘트 분석 API 엔드포인트
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.analysis.news_collector import NewsCollector
from src.analysis.news_sentiment import NewsSentimentAnalyzer
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/analysis/news", tags=["Analysis"])

# 모듈 레벨 싱글턴
_collector = NewsCollector()
_analyzer = NewsSentimentAnalyzer()


# ---------------------------------------------------------------------------
# Response Models
# ---------------------------------------------------------------------------


class HeadlineResponse(BaseModel):
    """헤드라인 응답"""

    title: str
    source: str
    url: str
    published_at: str
    category: str


class HeadlineAnalysisResponse(BaseModel):
    """개별 헤드라인 분석 응답"""

    title: str
    impact_score: int
    category: str
    affected_sectors: list[str]
    urgency: str
    reasoning: str


class NewsSentimentResponse(BaseModel):
    """뉴스 센티멘트 종합 응답"""

    overall_score: int
    analyses: list[HeadlineAnalysisResponse]
    category_scores: dict[str, float]
    market_impact_summary: str


class HeadlinesListResponse(BaseModel):
    """헤드라인 목록 응답"""

    headlines: list[HeadlineResponse]
    count: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/sentiment", response_model=NewsSentimentResponse)
async def get_news_sentiment() -> NewsSentimentResponse:
    """뉴스 수집 + LLM 센티멘트 분석 결과 반환"""
    try:
        headlines = await _collector.fetch_headlines()
        result = _analyzer.analyze_news_sentiment(headlines)
    except Exception as exc:
        logger.error("뉴스 센티멘트 분석 실패: %s", exc)
        raise HTTPException(
            status_code=502, detail="뉴스 센티멘트 분석 실패"
        ) from exc

    return NewsSentimentResponse(
        overall_score=result.overall_score,
        analyses=[
            HeadlineAnalysisResponse(
                title=a.title,
                impact_score=a.impact_score,
                category=a.category,
                affected_sectors=a.affected_sectors,
                urgency=a.urgency,
                reasoning=a.reasoning,
            )
            for a in result.analyses
        ],
        category_scores=result.category_scores,
        market_impact_summary=result.market_impact_summary,
    )


@router.get("/headlines", response_model=HeadlinesListResponse)
async def get_headlines() -> HeadlinesListResponse:
    """최신 뉴스 헤드라인 목록 반환"""
    try:
        headlines = await _collector.fetch_headlines()
    except Exception as exc:
        logger.error("뉴스 수집 실패: %s", exc)
        raise HTTPException(status_code=502, detail="뉴스 수집 실패") from exc

    items = [
        HeadlineResponse(
            title=h.title,
            source=h.source,
            url=h.url,
            published_at=h.published_at.isoformat(),
            category=h.category,
        )
        for h in headlines
    ]
    return HeadlinesListResponse(headlines=items, count=len(items))

"""
LLM 기반 뉴스 센티멘트 분석 모듈

OpenAI API를 사용하여 뉴스 헤드라인의 시장 영향도를 분석합니다.
10분 TTL 캐싱을 지원합니다.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass

import openai

from src.analysis.news_collector import NewsHeadline
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------


@dataclass
class HeadlineAnalysis:
    """개별 헤드라인 분석 결과"""

    title: str
    impact_score: int  # -100 ~ +100
    category: str  # geopolitical|monetary|earnings|trade|regulation|other
    affected_sectors: list[str]
    urgency: str  # low|medium|high|critical
    reasoning: str


@dataclass
class NewsSentimentResult:
    """뉴스 센티멘트 종합 결과"""

    overall_score: int  # -100 ~ +100
    analyses: list[HeadlineAnalysis]
    category_scores: dict[str, float]
    market_impact_summary: str


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

_CACHE_TTL = 600  # 10분


# ---------------------------------------------------------------------------
# NewsSentimentAnalyzer
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are a financial news analyst. Analyze the given news headlines and assess their potential impact on the stock market.

For each headline, provide:
- impact_score: integer from -100 (very negative) to +100 (very positive) for market impact
- category: one of "geopolitical", "monetary", "earnings", "trade", "regulation", "other"
- affected_sectors: list of affected market sectors
- urgency: one of "low", "medium", "high", "critical"
- reasoning: brief explanation (1-2 sentences)

Also provide:
- overall_score: integer from -100 to +100 representing overall market sentiment
- market_impact_summary: 2-3 sentence summary of overall market impact

Respond in JSON format with this exact structure:
{
  "overall_score": 0,
  "market_impact_summary": "...",
  "analyses": [
    {
      "title": "...",
      "impact_score": 0,
      "category": "...",
      "affected_sectors": ["..."],
      "urgency": "...",
      "reasoning": "..."
    }
  ]
}"""


class NewsSentimentAnalyzer:
    """OpenAI LLM을 사용한 뉴스 센티멘트 분석"""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        client: openai.OpenAI | None = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._model = model or os.environ.get("NEWS_LLM_MODEL", "gpt-4o-mini")
        self._client = client or openai.OpenAI(api_key=self._api_key)
        self._cache: NewsSentimentResult | None = None
        self._cache_time: float = 0.0

    def _should_use_cache(self) -> bool:
        return (
            self._cache is not None
            and (time.monotonic() - self._cache_time) < _CACHE_TTL
        )

    def analyze_news_sentiment(
        self, headlines: list[NewsHeadline]
    ) -> NewsSentimentResult:
        """뉴스 헤드라인 센티멘트 분석 (캐시 지원)

        Args:
            headlines: 분석할 뉴스 헤드라인 목록

        Returns:
            NewsSentimentResult 종합 분석 결과
        """
        if self._should_use_cache():
            assert self._cache is not None
            logger.debug("캐시된 뉴스 센티멘트 반환")
            return self._cache

        if not headlines:
            return NewsSentimentResult(
                overall_score=0,
                analyses=[],
                category_scores={},
                market_impact_summary="분석할 뉴스가 없습니다.",
            )

        result = self._analyze_fresh(headlines)
        self._cache = result
        self._cache_time = time.monotonic()
        return result

    def _analyze_fresh(
        self, headlines: list[NewsHeadline]
    ) -> NewsSentimentResult:
        """OpenAI API를 사용하여 실제 분석 수행"""
        headlines_text = "\n".join(
            f"- {h.title} (source: {h.source})" for h in headlines
        )

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": f"Analyze these news headlines:\n\n{headlines_text}",
                    },
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
            )

            content = response.choices[0].message.content or "{}"
            data = json.loads(content)
            return self._parse_response(data)

        except Exception as exc:
            logger.error("OpenAI API 호출 실패: %s", exc)
            raise

    def _parse_response(self, data: dict) -> NewsSentimentResult:  # type: ignore[type-arg]
        """API 응답을 NewsSentimentResult로 변환"""
        analyses: list[HeadlineAnalysis] = []
        for item in data.get("analyses", []):
            analyses.append(
                HeadlineAnalysis(
                    title=item.get("title", ""),
                    impact_score=max(-100, min(100, int(item.get("impact_score", 0)))),
                    category=item.get("category", "other"),
                    affected_sectors=item.get("affected_sectors", []),
                    urgency=item.get("urgency", "low"),
                    reasoning=item.get("reasoning", ""),
                )
            )

        # 카테고리별 점수 계산
        category_scores: dict[str, float] = {}
        category_counts: dict[str, int] = {}
        for a in analyses:
            cat = a.category
            category_scores[cat] = category_scores.get(cat, 0) + a.impact_score
            category_counts[cat] = category_counts.get(cat, 0) + 1
        for cat in category_scores:
            category_scores[cat] /= category_counts[cat]

        overall_score = max(-100, min(100, int(data.get("overall_score", 0))))

        return NewsSentimentResult(
            overall_score=overall_score,
            analyses=analyses,
            category_scores=category_scores,
            market_impact_summary=data.get("market_impact_summary", ""),
        )

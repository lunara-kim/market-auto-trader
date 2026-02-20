"""
공포탐욕지수(Fear & Greed Index) + 시장 센티멘트 분석 모듈

CNN Fear & Greed Index를 primary로, alternative.me를 fallback으로 사용합니다.
10분 TTL 캐싱을 지원합니다.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from src.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------


@dataclass
class SentimentResult:
    """공포탐욕지수 결과"""

    score: int  # 0~100
    classification: str  # "Extreme Fear", "Fear", "Neutral", "Greed", "Extreme Greed"
    timestamp: datetime
    source: str  # "cnn" or "alternative"


@dataclass
class MarketSentimentResult:
    """종합 시장 센티멘트 분석 결과"""

    fear_greed: SentimentResult
    buy_multiplier: float
    market_condition: str  # "oversold", "neutral", "overbought"
    recommendation: str  # "aggressive_buy", "buy", "hold", "reduce", "stop_buy"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CLASSIFICATIONS = [
    (25, "Extreme Fear"),
    (45, "Fear"),
    (55, "Neutral"),
    (75, "Greed"),
    (101, "Extreme Greed"),
]


def classify_score(score: int) -> str:
    """점수를 분류 문자열로 변환"""
    for threshold, label in _CLASSIFICATIONS:
        if score < threshold:
            return label
    return "Extreme Greed"


# ---------------------------------------------------------------------------
# FearGreedIndex
# ---------------------------------------------------------------------------

CNN_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
ALTERNATIVE_URL = "https://api.alternative.me/fng/?limit=1"

_CACHE_TTL = 600  # 10분


class FearGreedIndex:
    """CNN Fear & Greed Index 조회 (alternative.me fallback)"""

    def __init__(self, http_client: httpx.Client | None = None) -> None:
        self._client = http_client
        self._cache: SentimentResult | None = None
        self._cache_time: float = 0.0

    def _get_client(self) -> httpx.Client:
        if self._client is not None:
            return self._client
        return httpx.Client(timeout=10)

    def _should_use_cache(self) -> bool:
        return (
            self._cache is not None
            and (time.monotonic() - self._cache_time) < _CACHE_TTL
        )

    def fetch(self) -> SentimentResult:
        """공포탐욕지수 조회 (캐시 지원)"""
        if self._should_use_cache():
            assert self._cache is not None
            logger.debug("캐시된 공포탐욕지수 반환 (score=%d)", self._cache.score)
            return self._cache

        result = self._fetch_fresh()
        self._cache = result
        self._cache_time = time.monotonic()
        return result

    def _fetch_fresh(self) -> SentimentResult:
        """실제 API 호출"""
        try:
            return self._fetch_cnn()
        except Exception:
            logger.warning("CNN API 실패, alternative.me fallback 사용")
            return self._fetch_alternative()

    def _fetch_cnn(self) -> SentimentResult:
        client = self._get_client()
        resp = client.get(CNN_URL, headers={"User-Agent": "market-auto-trader/1.0"})
        resp.raise_for_status()
        data = resp.json()
        score = int(round(data["fear_and_greed"]["score"]))
        ts = datetime.fromtimestamp(
            data["fear_and_greed"]["timestamp"] / 1000, tz=timezone.utc
        )
        return SentimentResult(
            score=score,
            classification=classify_score(score),
            timestamp=ts,
            source="cnn",
        )

    def _fetch_alternative(self) -> SentimentResult:
        client = self._get_client()
        resp = client.get(ALTERNATIVE_URL)
        resp.raise_for_status()
        data = resp.json()["data"][0]
        score = int(data["value"])
        ts = datetime.fromtimestamp(int(data["timestamp"]), tz=timezone.utc)
        return SentimentResult(
            score=score,
            classification=classify_score(score),
            timestamp=ts,
            source="alternative",
        )

    @staticmethod
    def get_buy_multiplier(score: int) -> float:
        """공포탐욕지수 → 매수 강도 배율

        0~24  (극단적 공포): 1.5
        25~44 (공포):       1.2
        45~54 (중립):       1.0
        55~74 (탐욕):       0.5
        75~100(극단적 탐욕): 0.0 (매수 중단)
        """
        if score < 25:
            return 1.5
        if score < 45:
            return 1.2
        if score < 55:
            return 1.0
        if score < 75:
            return 0.5
        return 0.0


# ---------------------------------------------------------------------------
# MarketSentiment
# ---------------------------------------------------------------------------


class MarketSentiment:
    """종합 시장 센티멘트 분석"""

    def __init__(self, fear_greed: FearGreedIndex | None = None) -> None:
        self._fear_greed = fear_greed or FearGreedIndex()

    def analyze(self) -> MarketSentimentResult:
        """공포탐욕지수 + 시장 환경 종합 분석"""
        fg = self._fear_greed.fetch()
        multiplier = FearGreedIndex.get_buy_multiplier(fg.score)
        condition = self._determine_condition(fg.score)
        recommendation = self._determine_recommendation(fg.score)

        logger.info(
            "시장 센티멘트: score=%d (%s), multiplier=%.1f, %s → %s",
            fg.score,
            fg.classification,
            multiplier,
            condition,
            recommendation,
        )

        return MarketSentimentResult(
            fear_greed=fg,
            buy_multiplier=multiplier,
            market_condition=condition,
            recommendation=recommendation,
        )

    @staticmethod
    def _determine_condition(score: int) -> str:
        if score < 25:
            return "oversold"
        if score < 75:
            return "neutral"
        return "overbought"

    @staticmethod
    def _determine_recommendation(score: int) -> str:
        if score < 25:
            return "aggressive_buy"
        if score < 45:
            return "buy"
        if score < 55:
            return "hold"
        if score < 75:
            return "reduce"
        return "stop_buy"


# ---------------------------------------------------------------------------
# Hybrid Sentiment
# ---------------------------------------------------------------------------


@dataclass
class HybridSentimentResult:
    """하이브리드 센티멘트 분석 결과"""

    hybrid_score: float  # -100 ~ +100
    numeric_score: float  # -100 ~ +100 (정규화된 공포탐욕지수)
    news_score: float | None  # -100 ~ +100 (뉴스 LLM 스코어)
    weights: dict[str, float]  # {"numeric": 0.5, "news": 0.5}
    news_available: bool
    news_urgency: str | None  # highest urgency from news analyses
    fear_greed_raw: SentimentResult  # 원본 공포탐욕지수


class HybridSentimentAnalyzer:
    """수치 지표(FearGreedIndex) + 뉴스 LLM 분석을 가중 합산하는 하이브리드 센티멘트"""

    def __init__(
        self,
        fear_greed: FearGreedIndex | None = None,
        numeric_weight: float = 0.5,
        news_weight: float = 0.5,
    ) -> None:
        self._fear_greed = fear_greed or FearGreedIndex()
        self._numeric_weight = numeric_weight
        self._news_weight = news_weight

    @staticmethod
    def normalize_fear_greed(score: int) -> float:
        """0~100 스케일 → -100~+100 (50=중립)"""
        return (score - 50) * 2.0

    def analyze(self) -> HybridSentimentResult:
        """하이브리드 센티멘트 분석

        OPENAI_API_KEY가 없거나 뉴스 분석 실패 시 numeric 100% fallback.
        """
        fg = self._fear_greed.fetch()
        numeric_score = self.normalize_fear_greed(fg.score)

        # 뉴스 분석 시도
        news_score: float | None = None
        news_urgency: str | None = None
        news_available = False

        api_key = os.environ.get("OPENAI_API_KEY", "")
        if api_key:
            try:
                from src.analysis.news_collector import NewsCollector
                from src.analysis.news_sentiment import NewsSentimentAnalyzer

                collector = NewsCollector()
                headlines = asyncio.run(collector.fetch_headlines())
                if headlines:
                    analyzer = NewsSentimentAnalyzer(api_key=api_key)
                    result = analyzer.analyze_news_sentiment(headlines)
                    news_score = float(result.overall_score)
                    news_available = True
                    # highest urgency
                    urgency_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
                    max_urgency = "low"
                    for a in result.analyses:
                        if urgency_order.get(a.urgency, 0) > urgency_order.get(max_urgency, 0):
                            max_urgency = a.urgency
                    news_urgency = max_urgency
            except Exception:
                logger.warning("뉴스 센티멘트 분석 실패, numeric only fallback")

        # 가중 합산
        if news_available and news_score is not None:
            hybrid = self._numeric_weight * numeric_score + self._news_weight * news_score
            weights = {"numeric": self._numeric_weight, "news": self._news_weight}
        else:
            hybrid = numeric_score
            weights = {"numeric": 1.0, "news": 0.0}

        hybrid = max(-100.0, min(100.0, hybrid))

        return HybridSentimentResult(
            hybrid_score=hybrid,
            numeric_score=numeric_score,
            news_score=news_score,
            weights=weights,
            news_available=news_available,
            news_urgency=news_urgency,
            fear_greed_raw=fg,
        )

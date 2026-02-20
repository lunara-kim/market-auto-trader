"""
뉴스 센티멘트 분석 테스트 — OpenAI API는 전부 mock
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from src.analysis.news_collector import NewsHeadline
from src.analysis.news_sentiment import (
    NewsSentimentAnalyzer,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_headlines(n: int = 2) -> list[NewsHeadline]:
    return [
        NewsHeadline(
            title=f"Headline {i}",
            source="Test",
            url=f"https://example.com/{i}",
            published_at=datetime(2024, 2, 19, tzinfo=timezone.utc),
            category="economy",
        )
        for i in range(n)
    ]


def _mock_openai_response(data: dict) -> MagicMock:  # type: ignore[type-arg]
    """OpenAI API 응답 mock 생성"""
    message = MagicMock()
    message.content = json.dumps(data)
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


SAMPLE_RESPONSE = {
    "overall_score": 25,
    "market_impact_summary": "Moderately positive outlook.",
    "analyses": [
        {
            "title": "Headline 0",
            "impact_score": 30,
            "category": "monetary",
            "affected_sectors": ["finance", "tech"],
            "urgency": "medium",
            "reasoning": "Rate cuts benefit growth stocks.",
        },
        {
            "title": "Headline 1",
            "impact_score": 20,
            "category": "trade",
            "affected_sectors": ["manufacturing"],
            "urgency": "low",
            "reasoning": "Trade deal supports exports.",
        },
    ],
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestNewsSentimentAnalyzer:
    def test_analyze_returns_result(self) -> None:
        """정상 분석 결과 반환"""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_openai_response(
            SAMPLE_RESPONSE
        )

        analyzer = NewsSentimentAnalyzer(api_key="test-key", client=mock_client)
        result = analyzer.analyze_news_sentiment(_make_headlines())

        assert result.overall_score == 25
        assert len(result.analyses) == 2
        assert result.analyses[0].category == "monetary"
        assert result.market_impact_summary == "Moderately positive outlook."

    def test_category_scores_calculated(self) -> None:
        """카테고리별 평균 점수 계산"""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_openai_response(
            SAMPLE_RESPONSE
        )

        analyzer = NewsSentimentAnalyzer(api_key="test-key", client=mock_client)
        result = analyzer.analyze_news_sentiment(_make_headlines())

        assert "monetary" in result.category_scores
        assert result.category_scores["monetary"] == 30.0
        assert result.category_scores["trade"] == 20.0

    def test_score_clamping(self) -> None:
        """점수가 -100~+100 범위로 제한됨"""
        data = {
            "overall_score": 200,
            "market_impact_summary": "test",
            "analyses": [
                {
                    "title": "X",
                    "impact_score": -999,
                    "category": "other",
                    "affected_sectors": [],
                    "urgency": "low",
                    "reasoning": "test",
                }
            ],
        }
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_openai_response(data)

        analyzer = NewsSentimentAnalyzer(api_key="test-key", client=mock_client)
        result = analyzer.analyze_news_sentiment(_make_headlines(1))

        assert result.overall_score == 100
        assert result.analyses[0].impact_score == -100

    def test_empty_headlines(self) -> None:
        """빈 헤드라인 목록"""
        mock_client = MagicMock()
        analyzer = NewsSentimentAnalyzer(api_key="test-key", client=mock_client)
        result = analyzer.analyze_news_sentiment([])

        assert result.overall_score == 0
        assert result.analyses == []
        mock_client.chat.completions.create.assert_not_called()

    def test_cache_returns_cached_result(self) -> None:
        """캐시된 결과 반환"""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_openai_response(
            SAMPLE_RESPONSE
        )

        analyzer = NewsSentimentAnalyzer(api_key="test-key", client=mock_client)
        headlines = _make_headlines()

        result1 = analyzer.analyze_news_sentiment(headlines)
        result2 = analyzer.analyze_news_sentiment(headlines)

        assert result1 is result2
        assert mock_client.chat.completions.create.call_count == 1

    def test_cache_expires(self) -> None:
        """캐시 만료 후 재호출"""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_openai_response(
            SAMPLE_RESPONSE
        )

        analyzer = NewsSentimentAnalyzer(api_key="test-key", client=mock_client)
        headlines = _make_headlines()

        analyzer.analyze_news_sentiment(headlines)

        # 캐시 시간을 강제로 과거로 설정
        analyzer._cache_time = time.monotonic() - 700

        analyzer.analyze_news_sentiment(headlines)
        assert mock_client.chat.completions.create.call_count == 2

    def test_api_error_propagates(self) -> None:
        """API 에러 전파"""
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("API error")

        analyzer = NewsSentimentAnalyzer(api_key="test-key", client=mock_client)

        with pytest.raises(Exception, match="API error"):
            analyzer.analyze_news_sentiment(_make_headlines())

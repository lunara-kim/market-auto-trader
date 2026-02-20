"""
뉴스 API 엔드포인트 테스트
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from src.analysis.news_collector import NewsHeadline
from src.analysis.news_sentiment import HeadlineAnalysis, NewsSentimentResult


def _sample_headlines() -> list[NewsHeadline]:
    return [
        NewsHeadline(
            title="Market rallies",
            source="Test News",
            url="https://example.com/1",
            published_at=datetime(2024, 2, 19, 12, 0, tzinfo=timezone.utc),
            category="economy",
        ),
    ]


def _sample_sentiment_result() -> NewsSentimentResult:
    return NewsSentimentResult(
        overall_score=30,
        analyses=[
            HeadlineAnalysis(
                title="Market rallies",
                impact_score=30,
                category="monetary",
                affected_sectors=["finance"],
                urgency="medium",
                reasoning="Positive outlook.",
            ),
        ],
        category_scores={"monetary": 30.0},
        market_impact_summary="Markets look good.",
    )


class TestNewsAPI:
    def test_get_headlines(self) -> None:
        """헤드라인 엔드포인트"""
        import src.api.news as news_mod
        from src.main import app

        original_collector = news_mod._collector
        try:
            mock_collector = MagicMock()
            mock_collector.fetch_headlines = AsyncMock(
                return_value=_sample_headlines()
            )
            news_mod._collector = mock_collector

            client = TestClient(app)
            resp = client.get("/api/v1/analysis/news/headlines")

            assert resp.status_code == 200
            data = resp.json()
            assert data["count"] == 1
            assert data["headlines"][0]["title"] == "Market rallies"
        finally:
            news_mod._collector = original_collector

    def test_get_news_sentiment(self) -> None:
        """센티멘트 엔드포인트"""
        import src.api.news as news_mod
        from src.main import app

        original_collector = news_mod._collector
        original_analyzer = news_mod._analyzer
        try:
            mock_collector = MagicMock()
            mock_collector.fetch_headlines = AsyncMock(
                return_value=_sample_headlines()
            )
            news_mod._collector = mock_collector

            mock_analyzer = MagicMock()
            mock_analyzer.analyze_news_sentiment.return_value = (
                _sample_sentiment_result()
            )
            news_mod._analyzer = mock_analyzer

            client = TestClient(app)
            resp = client.get("/api/v1/analysis/news/sentiment")

            assert resp.status_code == 200
            data = resp.json()
            assert data["overall_score"] == 30
            assert len(data["analyses"]) == 1
            assert data["market_impact_summary"] == "Markets look good."
        finally:
            news_mod._collector = original_collector
            news_mod._analyzer = original_analyzer

    def test_headlines_error_returns_502(self) -> None:
        """수집 실패 시 502"""
        import src.api.news as news_mod
        from src.main import app

        original_collector = news_mod._collector
        try:
            mock_collector = MagicMock()
            mock_collector.fetch_headlines = AsyncMock(
                side_effect=Exception("Network error")
            )
            news_mod._collector = mock_collector

            client = TestClient(app)
            resp = client.get("/api/v1/analysis/news/headlines")
            assert resp.status_code == 502
        finally:
            news_mod._collector = original_collector

    def test_sentiment_error_returns_502(self) -> None:
        """분석 실패 시 502"""
        import src.api.news as news_mod
        from src.main import app

        original_collector = news_mod._collector
        original_analyzer = news_mod._analyzer
        try:
            mock_collector = MagicMock()
            mock_collector.fetch_headlines = AsyncMock(
                return_value=_sample_headlines()
            )
            news_mod._collector = mock_collector

            mock_analyzer = MagicMock()
            mock_analyzer.analyze_news_sentiment.side_effect = Exception("LLM error")
            news_mod._analyzer = mock_analyzer

            client = TestClient(app)
            resp = client.get("/api/v1/analysis/news/sentiment")
            assert resp.status_code == 502
        finally:
            news_mod._collector = original_collector
            news_mod._analyzer = original_analyzer

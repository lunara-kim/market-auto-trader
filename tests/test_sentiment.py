"""
공포탐욕지수 + 시장 센티멘트 분석 테스트
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient

from src.analysis.sentiment import (
    FearGreedIndex,
    MarketSentiment,
    MarketSentimentResult,
    SentimentResult,
    classify_score,
)


# ---------------------------------------------------------------------------
# classify_score
# ---------------------------------------------------------------------------


class TestClassifyScore:
    def test_extreme_fear(self) -> None:
        assert classify_score(0) == "Extreme Fear"
        assert classify_score(10) == "Extreme Fear"
        assert classify_score(24) == "Extreme Fear"

    def test_fear(self) -> None:
        assert classify_score(25) == "Fear"
        assert classify_score(35) == "Fear"
        assert classify_score(44) == "Fear"

    def test_neutral(self) -> None:
        assert classify_score(45) == "Neutral"
        assert classify_score(50) == "Neutral"
        assert classify_score(54) == "Neutral"

    def test_greed(self) -> None:
        assert classify_score(55) == "Greed"
        assert classify_score(65) == "Greed"
        assert classify_score(74) == "Greed"

    def test_extreme_greed(self) -> None:
        assert classify_score(75) == "Extreme Greed"
        assert classify_score(90) == "Extreme Greed"
        assert classify_score(100) == "Extreme Greed"


# ---------------------------------------------------------------------------
# FearGreedIndex.get_buy_multiplier
# ---------------------------------------------------------------------------


class TestGetBuyMultiplier:
    @pytest.mark.parametrize(
        ("score", "expected"),
        [
            (0, 1.5),
            (10, 1.5),
            (24, 1.5),
            (25, 1.2),
            (35, 1.2),
            (44, 1.2),
            (45, 1.0),
            (50, 1.0),
            (54, 1.0),
            (55, 0.5),
            (65, 0.5),
            (74, 0.5),
            (75, 0.0),
            (90, 0.0),
            (100, 0.0),
        ],
    )
    def test_multiplier_ranges(self, score: int, expected: float) -> None:
        assert FearGreedIndex.get_buy_multiplier(score) == expected


# ---------------------------------------------------------------------------
# FearGreedIndex.fetch — mocked
# ---------------------------------------------------------------------------

_CNN_RESPONSE = {
    "fear_and_greed": {
        "score": 38.5,
        "timestamp": 1708300800000,  # 2024-02-19T00:00:00Z
    }
}

_ALT_RESPONSE = {
    "data": [
        {
            "value": "22",
            "value_classification": "Extreme Fear",
            "timestamp": "1708300800",
        }
    ]
}


class TestFearGreedFetch:
    def test_fetch_cnn_success(self) -> None:
        mock_client = MagicMock(spec=httpx.Client)
        mock_resp = MagicMock()
        mock_resp.json.return_value = _CNN_RESPONSE
        mock_resp.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_resp

        fgi = FearGreedIndex(http_client=mock_client)
        result = fgi.fetch()

        assert result.score == 38  # rounded from 38.5
        assert result.classification == "Fear"
        assert result.source == "cnn"
        assert isinstance(result.timestamp, datetime)

    def test_fetch_cnn_fails_fallback_to_alternative(self) -> None:
        mock_client = MagicMock(spec=httpx.Client)

        def side_effect(url: str, **kwargs):  # noqa: ANN003, ARG001
            if "cnn" in url:
                raise httpx.HTTPError("CNN down")
            mock_resp = MagicMock()
            mock_resp.json.return_value = _ALT_RESPONSE
            mock_resp.raise_for_status = MagicMock()
            return mock_resp

        mock_client.get.side_effect = side_effect

        fgi = FearGreedIndex(http_client=mock_client)
        result = fgi.fetch()

        assert result.score == 22
        assert result.classification == "Extreme Fear"
        assert result.source == "alternative"

    def test_fetch_caching(self) -> None:
        mock_client = MagicMock(spec=httpx.Client)
        mock_resp = MagicMock()
        mock_resp.json.return_value = _CNN_RESPONSE
        mock_resp.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_resp

        fgi = FearGreedIndex(http_client=mock_client)
        r1 = fgi.fetch()
        r2 = fgi.fetch()

        assert r1 is r2
        # Only one HTTP call thanks to cache
        assert mock_client.get.call_count == 1

    def test_both_apis_fail(self) -> None:
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.side_effect = httpx.HTTPError("all down")

        fgi = FearGreedIndex(http_client=mock_client)
        with pytest.raises(httpx.HTTPError):
            fgi.fetch()


# ---------------------------------------------------------------------------
# MarketSentiment.analyze
# ---------------------------------------------------------------------------


class TestMarketSentiment:
    def _make_result(self, score: int) -> SentimentResult:
        return SentimentResult(
            score=score,
            classification=classify_score(score),
            timestamp=datetime.now(tz=timezone.utc),
            source="test",
        )

    def test_analyze_extreme_fear(self) -> None:
        fgi = MagicMock(spec=FearGreedIndex)
        fgi.fetch.return_value = self._make_result(15)
        ms = MarketSentiment(fear_greed=fgi)
        result = ms.analyze()

        assert isinstance(result, MarketSentimentResult)
        assert result.buy_multiplier == 1.5
        assert result.market_condition == "oversold"
        assert result.recommendation == "aggressive_buy"

    def test_analyze_neutral(self) -> None:
        fgi = MagicMock(spec=FearGreedIndex)
        fgi.fetch.return_value = self._make_result(50)
        ms = MarketSentiment(fear_greed=fgi)
        result = ms.analyze()

        assert result.buy_multiplier == 1.0
        assert result.market_condition == "neutral"
        assert result.recommendation == "hold"

    def test_analyze_extreme_greed(self) -> None:
        fgi = MagicMock(spec=FearGreedIndex)
        fgi.fetch.return_value = self._make_result(85)
        ms = MarketSentiment(fear_greed=fgi)
        result = ms.analyze()

        assert result.buy_multiplier == 0.0
        assert result.market_condition == "overbought"
        assert result.recommendation == "stop_buy"


# ---------------------------------------------------------------------------
# API endpoint
# ---------------------------------------------------------------------------


class TestSentimentAPI:
    def test_get_sentiment_success(self) -> None:
        import src.api.sentiment as analysis_mod
        from src.main import app

        original = analysis_mod._sentiment
        try:
            mock_sentiment = MagicMock()
            mock_sentiment.analyze.return_value = MarketSentimentResult(
                fear_greed=SentimentResult(
                    score=30,
                    classification="Fear",
                    timestamp=datetime(2024, 2, 19, tzinfo=timezone.utc),
                    source="cnn",
                ),
                buy_multiplier=1.2,
                market_condition="neutral",
                recommendation="buy",
            )
            analysis_mod._sentiment = mock_sentiment

            client = TestClient(app)
            resp = client.get("/api/v1/analysis/sentiment")
            assert resp.status_code == 200
            body = resp.json()
            assert body["score"] == 30
            assert body["classification"] == "Fear"
            assert body["buy_multiplier"] == 1.2
            assert body["recommendation"] == "buy"
        finally:
            analysis_mod._sentiment = original

    def test_get_sentiment_error(self) -> None:
        import src.api.sentiment as analysis_mod
        from src.main import app

        original = analysis_mod._sentiment
        try:
            mock_sentiment = MagicMock()
            mock_sentiment.analyze.side_effect = Exception("API down")
            analysis_mod._sentiment = mock_sentiment

            client = TestClient(app)
            resp = client.get("/api/v1/analysis/sentiment")
            assert resp.status_code == 502
        finally:
            analysis_mod._sentiment = original

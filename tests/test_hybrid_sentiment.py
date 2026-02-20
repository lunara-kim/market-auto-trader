"""
하이브리드 센티멘트 분석 테스트
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.analysis.news_sentiment import HeadlineAnalysis, NewsSentimentResult
from src.analysis.sentiment import (
    FearGreedIndex,
    HybridSentimentAnalyzer,
    HybridSentimentResult,
    SentimentResult,
)


def _make_fg_result(score: int = 50) -> SentimentResult:
    return SentimentResult(
        score=score,
        classification="Neutral",
        timestamp=datetime.now(tz=timezone.utc),
        source="test",
    )


# ---------------------------------------------------------------------------
# HybridSentimentAnalyzer.normalize_fear_greed
# ---------------------------------------------------------------------------


class TestNormalizeFearGreed:
    def test_neutral_50(self) -> None:
        assert HybridSentimentAnalyzer.normalize_fear_greed(50) == 0.0

    def test_extreme_fear_0(self) -> None:
        assert HybridSentimentAnalyzer.normalize_fear_greed(0) == -100.0

    def test_extreme_greed_100(self) -> None:
        assert HybridSentimentAnalyzer.normalize_fear_greed(100) == 100.0

    def test_fear_25(self) -> None:
        assert HybridSentimentAnalyzer.normalize_fear_greed(25) == -50.0

    def test_greed_75(self) -> None:
        assert HybridSentimentAnalyzer.normalize_fear_greed(75) == 50.0


# ---------------------------------------------------------------------------
# HybridSentimentAnalyzer.analyze — weighted combination
# ---------------------------------------------------------------------------


class TestHybridAnalyze:
    def test_both_sources_equal_weight(self) -> None:
        """numeric=50, news=+60 → hybrid = 0.5*0 + 0.5*60 = 30"""
        fgi = MagicMock(spec=FearGreedIndex)
        fgi.fetch.return_value = _make_fg_result(50)

        news_result = NewsSentimentResult(
            overall_score=60,
            analyses=[
                HeadlineAnalysis(
                    title="Good news",
                    impact_score=60,
                    category="earnings",
                    affected_sectors=["tech"],
                    urgency="medium",
                    reasoning="test",
                )
            ],
            category_scores={"earnings": 60.0},
            market_impact_summary="Positive",
        )

        analyzer = HybridSentimentAnalyzer(fear_greed=fgi)

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            with (
                patch("src.analysis.news_collector.NewsCollector") as mock_collector_cls,
                patch("src.analysis.news_sentiment.NewsSentimentAnalyzer") as mock_analyzer_cls,
            ):
                mock_collector_cls.return_value.collect_all.return_value = [MagicMock()]
                mock_analyzer_cls.return_value.analyze_news_sentiment.return_value = news_result

                result = analyzer.analyze()

        assert result.news_available is True
        assert result.numeric_score == 0.0
        assert result.news_score == 60.0
        assert result.hybrid_score == pytest.approx(30.0)
        assert result.weights == {"numeric": 0.5, "news": 0.5}

    def test_custom_weights(self) -> None:
        """numeric_weight=0.7, news_weight=0.3"""
        fgi = MagicMock(spec=FearGreedIndex)
        fgi.fetch.return_value = _make_fg_result(25)  # normalized = -50

        news_result = NewsSentimentResult(
            overall_score=80,
            analyses=[
                HeadlineAnalysis(
                    title="Great", impact_score=80, category="earnings",
                    affected_sectors=[], urgency="low", reasoning="ok",
                )
            ],
            category_scores={},
            market_impact_summary="",
        )

        analyzer = HybridSentimentAnalyzer(fear_greed=fgi, numeric_weight=0.7, news_weight=0.3)

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            with (
                patch("src.analysis.news_collector.NewsCollector") as mock_collector_cls,
                patch("src.analysis.news_sentiment.NewsSentimentAnalyzer") as mock_analyzer_cls,
            ):
                mock_collector_cls.return_value.collect_all.return_value = [MagicMock()]
                mock_analyzer_cls.return_value.analyze_news_sentiment.return_value = news_result

                result = analyzer.analyze()

        # 0.7 * (-50) + 0.3 * 80 = -35 + 24 = -11
        assert result.hybrid_score == pytest.approx(-11.0)
        assert result.weights == {"numeric": 0.7, "news": 0.3}

    def test_fallback_no_api_key(self) -> None:
        """OPENAI_API_KEY 없으면 numeric 100%"""
        fgi = MagicMock(spec=FearGreedIndex)
        fgi.fetch.return_value = _make_fg_result(30)  # normalized = -40

        analyzer = HybridSentimentAnalyzer(fear_greed=fgi)

        with patch.dict("os.environ", {"OPENAI_API_KEY": ""}, clear=False):
            result = analyzer.analyze()

        assert result.news_available is False
        assert result.news_score is None
        assert result.hybrid_score == pytest.approx(-40.0)
        assert result.weights == {"numeric": 1.0, "news": 0.0}

    def test_fallback_news_analysis_fails(self) -> None:
        """뉴스 분석 실패 시 numeric 100% fallback"""
        fgi = MagicMock(spec=FearGreedIndex)
        fgi.fetch.return_value = _make_fg_result(70)  # normalized = 40

        analyzer = HybridSentimentAnalyzer(fear_greed=fgi)

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            with patch("src.analysis.news_collector.NewsCollector") as mock_collector_cls:
                mock_collector_cls.return_value.collect_all.side_effect = Exception("fail")
                result = analyzer.analyze()

        assert result.news_available is False
        assert result.hybrid_score == pytest.approx(40.0)
        assert result.weights == {"numeric": 1.0, "news": 0.0}

    def test_critical_urgency_detected(self) -> None:
        """critical urgency가 결과에 반영"""
        fgi = MagicMock(spec=FearGreedIndex)
        fgi.fetch.return_value = _make_fg_result(50)

        news_result = NewsSentimentResult(
            overall_score=-80,
            analyses=[
                HeadlineAnalysis(
                    title="War", impact_score=-90, category="geopolitical",
                    affected_sectors=["all"], urgency="critical", reasoning="war",
                ),
                HeadlineAnalysis(
                    title="Ok", impact_score=10, category="other",
                    affected_sectors=[], urgency="low", reasoning="ok",
                ),
            ],
            category_scores={},
            market_impact_summary="",
        )

        analyzer = HybridSentimentAnalyzer(fear_greed=fgi)

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            with (
                patch("src.analysis.news_collector.NewsCollector") as mock_collector_cls,
                patch("src.analysis.news_sentiment.NewsSentimentAnalyzer") as mock_analyzer_cls,
            ):
                mock_collector_cls.return_value.collect_all.return_value = [MagicMock()]
                mock_analyzer_cls.return_value.analyze_news_sentiment.return_value = news_result

                result = analyzer.analyze()

        assert result.news_urgency == "critical"

    def test_clamp_to_range(self) -> None:
        """hybrid_score가 -100~+100 범위로 클램핑"""
        fgi = MagicMock(spec=FearGreedIndex)
        fgi.fetch.return_value = _make_fg_result(0)  # normalized = -100

        news_result = NewsSentimentResult(
            overall_score=-100,
            analyses=[],
            category_scores={},
            market_impact_summary="",
        )

        analyzer = HybridSentimentAnalyzer(fear_greed=fgi)

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            with (
                patch("src.analysis.news_collector.NewsCollector") as mock_collector_cls,
                patch("src.analysis.news_sentiment.NewsSentimentAnalyzer") as mock_analyzer_cls,
            ):
                mock_collector_cls.return_value.collect_all.return_value = [MagicMock()]
                mock_analyzer_cls.return_value.analyze_news_sentiment.return_value = news_result

                result = analyzer.analyze()

        assert result.hybrid_score == -100.0


# ---------------------------------------------------------------------------
# AutoTrader + hybrid sentiment
# ---------------------------------------------------------------------------


class TestAutoTraderHybrid:
    def test_hybrid_sentiment_score_mapping(self) -> None:
        """hybrid_score → sentiment ±30 매핑"""
        from src.analysis.screener import ScreeningResult, StockFundamentals
        from src.strategy.auto_trader import AutoTrader, AutoTraderConfig

        mock_kis = MagicMock()
        mock_kis.get_price.return_value = {
            "stck_prpr": "70000",
            "prdy_ctrt": "0.0",
            "stck_hgpr": "70500",
            "stck_lwpr": "69500",
        }

        trader = AutoTrader(mock_kis, AutoTraderConfig(dry_run=True))

        fg = _make_fg_result(30)
        from src.analysis.sentiment import MarketSentimentResult

        sentiment = MarketSentimentResult(
            fear_greed=fg, buy_multiplier=1.2,
            market_condition="neutral", recommendation="buy",
        )

        hybrid = HybridSentimentResult(
            hybrid_score=-60.0, numeric_score=-40.0, news_score=-80.0,
            weights={"numeric": 0.5, "news": 0.5}, news_available=True,
            news_urgency="high", fear_greed_raw=fg,
        )

        fundamentals = StockFundamentals(
            stock_code="005930", stock_name="삼성전자",
            per=8.0, pbr=1.5, roe=15.0, dividend_yield=2.0,
            operating_margin=15.0, revenue_growth_yoy=10.0,
            sector="기타", sector_avg_per=12.0,
            sector_avg_operating_margin=10.0, has_buyback=False,
        )
        screening = ScreeningResult(
            stock_code="005930", stock_name="삼성전자",
            fundamentals=fundamentals, quality="undervalued",
            quality_score=70.0, reason="test", eligible=True,
        )

        with (
            patch.object(trader._screener, "get_fundamentals", return_value=fundamentals),
            patch.object(trader._screener, "evaluate_quality", return_value=screening),
        ):
            signal = trader.calculate_signal("005930", sentiment, hybrid)

        # hybrid_score=-60, sentiment_score = -(-60)/100*30 = 18
        assert signal.sentiment_score == pytest.approx(18.0)

    def test_critical_urgency_skips_trading(self) -> None:
        """news urgency=critical → scan_universe returns empty"""
        from src.strategy.auto_trader import AutoTrader, AutoTraderConfig

        mock_kis = MagicMock()
        trader = AutoTrader(mock_kis, AutoTraderConfig(dry_run=True))

        critical_hybrid = HybridSentimentResult(
            hybrid_score=-80.0, numeric_score=-40.0, news_score=-100.0,
            weights={"numeric": 0.5, "news": 0.5}, news_available=True,
            news_urgency="critical", fear_greed_raw=_make_fg_result(30),
        )

        with (
            patch.object(trader._hybrid_sentiment, "analyze", return_value=critical_hybrid),
            patch.object(trader._sentiment, "analyze"),
            patch.object(trader._universe, "get_universe", return_value=MagicMock(stock_codes=["005930"])),
        ):
            signals = trader.scan_universe()

        assert signals == []

    def test_no_hybrid_fallback(self) -> None:
        """hybrid_result=None → 기존 방식 fallback"""
        from src.analysis.screener import ScreeningResult, StockFundamentals
        from src.strategy.auto_trader import AutoTrader, AutoTraderConfig

        mock_kis = MagicMock()
        mock_kis.get_price.return_value = {
            "stck_prpr": "70000", "prdy_ctrt": "0.0",
            "stck_hgpr": "70500", "stck_lwpr": "69500",
        }

        trader = AutoTrader(mock_kis, AutoTraderConfig(dry_run=True))

        fg = _make_fg_result(30)
        from src.analysis.sentiment import MarketSentimentResult

        sentiment = MarketSentimentResult(
            fear_greed=fg, buy_multiplier=1.2,
            market_condition="neutral", recommendation="buy",
        )

        fundamentals = StockFundamentals(
            stock_code="005930", stock_name="삼성전자",
            per=8.0, pbr=1.5, roe=15.0, dividend_yield=2.0,
            operating_margin=15.0, revenue_growth_yoy=10.0,
            sector="기타", sector_avg_per=12.0,
            sector_avg_operating_margin=10.0, has_buyback=False,
        )
        screening = ScreeningResult(
            stock_code="005930", stock_name="삼성전자",
            fundamentals=fundamentals, quality="undervalued",
            quality_score=70.0, reason="test", eligible=True,
        )

        with (
            patch.object(trader._screener, "get_fundamentals", return_value=fundamentals),
            patch.object(trader._screener, "evaluate_quality", return_value=screening),
        ):
            signal = trader.calculate_signal("005930", sentiment, hybrid_result=None)

        # 기존 방식: (50-30)*0.6 = 12
        assert signal.sentiment_score == pytest.approx(12.0)


# ---------------------------------------------------------------------------
# API: /sentiment/hybrid
# ---------------------------------------------------------------------------


class TestHybridAPI:
    def test_get_hybrid_sentiment(self) -> None:
        import src.api.sentiment as api_mod
        from src.main import app

        original = api_mod._hybrid
        try:
            mock_hybrid = MagicMock()
            mock_hybrid.analyze.return_value = HybridSentimentResult(
                hybrid_score=-20.0,
                numeric_score=-40.0,
                news_score=0.0,
                weights={"numeric": 0.5, "news": 0.5},
                news_available=True,
                news_urgency="medium",
                fear_greed_raw=_make_fg_result(30),
            )
            api_mod._hybrid = mock_hybrid

            client = TestClient(app)
            resp = client.get("/api/v1/analysis/sentiment/hybrid")
            assert resp.status_code == 200
            body = resp.json()
            assert body["hybrid_score"] == -20.0
            assert body["numeric_score"] == -40.0
            assert body["news_score"] == 0.0
            assert body["news_available"] is True
            assert body["news_urgency"] == "medium"
            assert body["fear_greed_raw_score"] == 30
        finally:
            api_mod._hybrid = original

    def test_hybrid_endpoint_error(self) -> None:
        import src.api.sentiment as api_mod
        from src.main import app

        original = api_mod._hybrid
        try:
            mock_hybrid = MagicMock()
            mock_hybrid.analyze.side_effect = Exception("fail")
            api_mod._hybrid = mock_hybrid

            client = TestClient(app)
            resp = client.get("/api/v1/analysis/sentiment/hybrid")
            assert resp.status_code == 502
        finally:
            api_mod._hybrid = original

    def test_existing_sentiment_endpoint_unchanged(self) -> None:
        """기존 /sentiment 엔드포인트 하위호환 확인"""
        import src.api.sentiment as api_mod
        from src.analysis.sentiment import MarketSentimentResult
        from src.main import app

        original = api_mod._sentiment
        try:
            mock_sentiment = MagicMock()
            mock_sentiment.analyze.return_value = MarketSentimentResult(
                fear_greed=_make_fg_result(45),
                buy_multiplier=1.0,
                market_condition="neutral",
                recommendation="hold",
            )
            api_mod._sentiment = mock_sentiment

            client = TestClient(app)
            resp = client.get("/api/v1/analysis/sentiment")
            assert resp.status_code == 200
            body = resp.json()
            assert body["score"] == 45
        finally:
            api_mod._sentiment = original

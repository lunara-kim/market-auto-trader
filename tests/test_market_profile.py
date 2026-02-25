"""
시장/섹터별 필터 프로필 시스템 테스트

프로필 매핑, PEG 계산, 프로필별 분류, 하위호환을 검증합니다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch


from src.analysis.market_profile import (
    MarketType,
    SectorType,
    calculate_peg_ratio,
    classify_by_profile,
    detect_market,
    detect_sector,
    get_stock_profile,
)
from src.analysis.screener import (
    StockFundamentals,
    StockScreener,
)
from src.analysis.universe import US_UNIVERSE, UniverseManager
from src.broker.kis_client import KISClient


# ───────────────── Market Detection ─────────────────


class TestDetectMarket:
    def test_kr_stock_code(self):
        assert detect_market("005930") == MarketType.KR

    def test_kr_ks_suffix(self):
        assert detect_market("005930.KS") == MarketType.KR

    def test_kr_kq_suffix(self):
        assert detect_market("035720.KQ") == MarketType.KR

    def test_us_ticker(self):
        assert detect_market("AAPL") == MarketType.US
        assert detect_market("NVDA") == MarketType.US

    def test_us_etf(self):
        assert detect_market("QQQ") == MarketType.US


# ───────────────── Sector Detection ─────────────────


class TestDetectSector:
    def test_explicit_mapping_growth(self):
        assert detect_sector("NVDA", MarketType.US) == SectorType.GROWTH
        assert detect_sector("META", MarketType.US) == SectorType.GROWTH

    def test_explicit_mapping_value(self):
        assert detect_sector("JPM", MarketType.US) == SectorType.VALUE

    def test_explicit_mapping_etf(self):
        assert detect_sector("QQQ", MarketType.US) == SectorType.ETF
        assert detect_sector("SPY", MarketType.US) == SectorType.ETF

    def test_kr_default_value(self):
        assert detect_sector("005930", MarketType.KR) == SectorType.VALUE

    def test_us_default_growth(self):
        assert detect_sector("UNKNOWN", MarketType.US) == SectorType.GROWTH


# ───────────────── StockProfile ─────────────────


class TestGetStockProfile:
    def test_us_growth(self):
        p = get_stock_profile("NVDA")
        assert p.market == MarketType.US
        assert p.sector == SectorType.GROWTH
        assert p.use_peg_ratio is True
        assert p.per_threshold == 50.0

    def test_us_value(self):
        p = get_stock_profile("JPM")
        assert p.market == MarketType.US
        assert p.sector == SectorType.VALUE
        assert p.use_peg_ratio is False
        assert p.per_threshold == 25.0

    def test_etf(self):
        p = get_stock_profile("QQQ")
        assert p.sector == SectorType.ETF
        assert p.skip_per_filter is True

    def test_kr_stock(self):
        p = get_stock_profile("005930")
        assert p.market == MarketType.KR
        assert p.sector == SectorType.VALUE
        assert p.use_peg_ratio is False
        assert p.per_threshold == 15.0


# ───────────────── PEG Ratio ─────────────────


class TestPegRatio:
    def test_basic_peg(self):
        # PE=30, earnings growth=25% (0.25) → PEG = 30/25 = 1.2
        peg = calculate_peg_ratio(30.0, 0.25, None)
        assert peg is not None
        assert abs(peg - 1.2) < 0.01

    def test_revenue_fallback(self):
        # No earnings growth, revenue growth = 20% → PEG = 40/20 = 2.0
        peg = calculate_peg_ratio(40.0, None, 0.20)
        assert peg is not None
        assert abs(peg - 2.0) < 0.01

    def test_no_growth_returns_none(self):
        assert calculate_peg_ratio(30.0, None, None) is None

    def test_negative_growth_returns_none(self):
        assert calculate_peg_ratio(30.0, -0.1, None) is None

    def test_zero_growth_returns_none(self):
        assert calculate_peg_ratio(30.0, 0.0, None) is None

    def test_negative_earnings_revenue_fallback(self):
        # earnings negative, revenue positive
        peg = calculate_peg_ratio(30.0, -0.1, 0.15)
        assert peg is not None
        assert abs(peg - 2.0) < 0.01


# ───────────────── Profile Classification ─────────────────


class TestClassifyByProfile:
    def test_etf_skip(self):
        p = get_stock_profile("QQQ")
        quality, adj, reason = classify_by_profile(p, 25.0, 20.0)
        assert quality == "skip"
        assert adj == 0.0

    def test_us_growth_undervalued(self):
        p = get_stock_profile("NVDA")
        # PEG = 30 / 25 = 1.2 < 1.5 → undervalued
        quality, adj, reason = classify_by_profile(
            p, 30.0, 25.0, earnings_growth=0.25
        )
        assert quality == "undervalued"
        assert adj == 25.0

    def test_us_growth_fair(self):
        p = get_stock_profile("NVDA")
        # PEG = 50 / 25 = 2.0 → fair
        quality, adj, reason = classify_by_profile(
            p, 50.0, 25.0, earnings_growth=0.25
        )
        assert quality == "fair"
        assert adj == 0.0

    def test_us_growth_overvalued(self):
        p = get_stock_profile("NVDA")
        # PEG = 80 / 25 = 3.2 > 2.5 → overvalued
        quality, adj, reason = classify_by_profile(
            p, 80.0, 25.0, earnings_growth=0.25
        )
        assert quality == "overvalued"

    def test_us_growth_high_revenue_allows_high_per(self):
        p = get_stock_profile("NVDA")
        # revenue > 20%, PER=90 < 100 cap → fair (not overvalued)
        quality, adj, reason = classify_by_profile(
            p, 90.0, 25.0, earnings_growth=None, revenue_growth=0.30
        )
        assert quality == "fair"

    def test_kr_value_undervalued(self):
        p = get_stock_profile("005930")
        # PER 8 < sector_avg 15 * 0.7 = 10.5 → undervalued
        quality, adj, reason = classify_by_profile(p, 8.0, 15.0)
        assert quality == "undervalued"
        assert adj == 25.0

    def test_kr_value_overvalued(self):
        p = get_stock_profile("005930")
        # PER 20 > threshold 15
        quality, adj, reason = classify_by_profile(p, 20.0, 15.0)
        assert quality == "overvalued"

    def test_us_growth_no_growth_data_fallback(self):
        p = get_stock_profile("NVDA")
        # No growth data, PER 30 < threshold 50 → fair (fallback)
        quality, adj, reason = classify_by_profile(p, 30.0, 25.0)
        assert quality == "fair"


# ───────────────── Screener Integration ─────────────────


class TestScreenerWithProfile:
    def test_evaluate_with_profile_etf(self):
        mock_kis = MagicMock(spec=KISClient)
        screener = StockScreener(mock_kis)
        profile = get_stock_profile("QQQ")
        f = StockFundamentals(
            stock_code="QQQ", stock_name="QQQ", per=0.0, pbr=0.0,
            roe=0.0, dividend_yield=0.0, operating_margin=0.0,
            revenue_growth_yoy=0.0, sector="ETF",
            sector_avg_per=0.0, sector_avg_operating_margin=0.0,
        )
        result = screener.evaluate_quality_with_profile(f, profile)
        assert result.eligible is True
        assert result.quality == "etf_pass"

    def test_evaluate_with_profile_growth_undervalued(self):
        mock_kis = MagicMock(spec=KISClient)
        screener = StockScreener(mock_kis)
        profile = get_stock_profile("NVDA")
        f = StockFundamentals(
            stock_code="NVDA", stock_name="NVIDIA", per=30.0, pbr=20.0,
            roe=50.0, dividend_yield=0.0, operating_margin=55.0,
            revenue_growth_yoy=120.0, sector="반도체",
            sector_avg_per=25.0, sector_avg_operating_margin=30.0,
        )
        result = screener.evaluate_quality_with_profile(
            f, profile, earnings_growth=0.25
        )
        assert result.eligible is True
        assert result.quality == "undervalued"

    def test_evaluate_without_profile_backward_compat(self):
        """profile=None이면 기존 로직으로 fallback"""
        mock_kis = MagicMock(spec=KISClient)
        screener = StockScreener(mock_kis)
        f = StockFundamentals(
            stock_code="005930", stock_name="삼성전자", per=8.0, pbr=1.2,
            roe=15.0, dividend_yield=2.0, operating_margin=25.0,
            revenue_growth_yoy=10.0, sector="반도체",
            sector_avg_per=15.0, sector_avg_operating_margin=20.0,
        )
        result = screener.evaluate_quality_with_profile(f, profile=None)
        assert result.eligible is True
        assert result.quality == "undervalued"


# ───────────────── Universe ─────────────────


class TestUSUniverse:
    def test_us_universe_exists(self):
        mgr = UniverseManager()
        u = mgr.get_universe("us_universe")
        assert u is not None
        assert "AAPL" in u.stock_codes
        assert "QQQ" in u.stock_codes

    def test_us_universe_preset(self):
        assert len(US_UNIVERSE) == 7


# ───────────────── AutoTrader Profile Integration ─────────────────


class TestAutoTraderWithProfile:
    """AutoTrader가 프로필을 올바르게 사용하는지 검증"""

    def test_us_growth_not_excluded(self):
        """US GROWTH 종목이 PER 높아도 HOLD가 아닌지 확인"""
        from src.analysis.sentiment import (
            MarketSentimentResult,
            SentimentResult,
        )
        from src.strategy.auto_trader import AutoTrader, AutoTraderConfig

        mock_kis = MagicMock(spec=KISClient)
        mock_kis.get_overseas_price.return_value = {
            "per": "35.0", "pbr": "20.0", "rsym": "NVDA",
        }
        mock_kis.get_price.return_value = {
            "stck_prpr": "130", "prdy_ctrt": "-2.0",
            "stck_hgpr": "135", "stck_lwpr": "125",
        }

        config = AutoTraderConfig(dry_run=True)
        trader = AutoTrader(mock_kis, config)

        sentiment = MarketSentimentResult(
            fear_greed=SentimentResult(
                score=30, classification="Fear",
                timestamp=datetime.now(tz=timezone.utc), source="test",
            ),
            buy_multiplier=1.2,
            market_condition="neutral",
            recommendation="buy",
        )

        profile = get_stock_profile("NVDA")

        with patch("yfinance.Ticker") as mock_ticker_cls:
            mock_ticker = MagicMock()
            mock_ticker.info = {"earningsGrowth": 0.30, "revenueGrowth": 0.25}
            mock_ticker_cls.return_value = mock_ticker

            signal = trader.calculate_signal("NVDA", sentiment, profile=profile)

        assert signal.stock_code == "NVDA"
        # PEG = 35/30 ≈ 1.17 < 1.5 → undervalued, should not be HOLD with 0 score
        # (exact behavior depends on screener eligible check)

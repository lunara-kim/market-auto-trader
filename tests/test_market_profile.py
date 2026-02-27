"""시장/섹터별 프로필 시스템 테스트 — Phase 5 버전"""

from __future__ import annotations

from unittest.mock import MagicMock

from src.analysis.market_profile import (
    SectorType,
    StockProfile,
    classify_by_profile,
    get_stock_profile,
)
from src.analysis.screener import StockFundamentals, StockScreener
from src.broker.kis_client import KISClient


# ───────────────── StockProfile ─────────────────


class TestGetStockProfile:
    def test_us_growth(self):
        p = get_stock_profile("NVDA")
        assert p.market == "US"
        assert p.sector == SectorType.GROWTH
        assert p.use_peg_ratio is True

    def test_us_default_growth(self):
        """STOCK_SECTOR_MAP에 없는 US 티커는 GROWTH로 분류"""
        p = get_stock_profile("QQQ")
        assert p.market == "US"
        assert p.sector == SectorType.GROWTH

    def test_kr_stock(self):
        p = get_stock_profile("005930")
        assert p.market == "KR"
        assert p.sector == SectorType.VALUE
        assert p.use_peg_ratio is False


# ───────────────── classify_by_profile ─────────────────


class TestClassifyByProfile:
    def test_etf_skip(self):
        """skip_per_filter=True인 프로필은 ETF로 분류"""
        p = StockProfile(market="US", sector=SectorType.ETF, skip_per_filter=True)
        quality, adj, reason = classify_by_profile(
            profile=p, per=25.0, sector_avg_per=20.0,
        )
        assert quality == "etf"
        assert adj == 0.0

    def test_us_growth_undervalued(self):
        p = get_stock_profile("NVDA")
        quality, adj, reason = classify_by_profile(
            profile=p, per=30.0, sector_avg_per=25.0, earnings_growth=0.25,
        )
        assert quality == "undervalued"
        assert adj == 25.0

    def test_us_growth_fair(self):
        p = get_stock_profile("NVDA")
        quality, adj, reason = classify_by_profile(
            profile=p, per=50.0, sector_avg_per=25.0, earnings_growth=0.25,
        )
        assert quality == "fair"

    def test_us_growth_overvalued(self):
        p = get_stock_profile("NVDA")
        quality, adj, reason = classify_by_profile(
            profile=p, per=80.0, sector_avg_per=25.0, earnings_growth=0.25,
        )
        assert quality == "overvalued"

    def test_kr_value_undervalued(self):
        p = get_stock_profile("005930")
        quality, adj, reason = classify_by_profile(
            profile=p, per=8.0, sector_avg_per=15.0,
        )
        assert quality == "undervalued"
        assert adj == 25.0

    def test_kr_value_overvalued(self):
        p = get_stock_profile("005930")
        quality, adj, reason = classify_by_profile(
            profile=p, per=20.0, sector_avg_per=15.0,
        )
        assert quality == "overvalued"

    def test_no_growth_data_fallback(self):
        p = get_stock_profile("NVDA")
        quality, adj, reason = classify_by_profile(
            profile=p, per=30.0, sector_avg_per=25.0,
        )
        assert quality == "fair"


# ───────────────── Screener Integration ─────────────────


class TestScreenerWithProfile:
    def test_evaluate_with_profile_etf(self):
        mock_kis = MagicMock(spec=KISClient)
        screener = StockScreener(mock_kis)
        profile = StockProfile(market="US", sector=SectorType.ETF, skip_per_filter=True)
        f = StockFundamentals(
            stock_code="QQQ", stock_name="QQQ", per=0.0, pbr=0.0,
            roe=0.0, dividend_yield=0.0, operating_margin=0.0,
            revenue_growth_yoy=0.0, sector="ETF",
            sector_avg_per=0.0, sector_avg_operating_margin=0.0,
        )
        result = screener.evaluate_quality_with_profile(f, profile=profile)
        assert result.eligible is True
        assert result.quality == "etf"

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

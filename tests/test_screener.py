"""
종목 스크리너 테스트

PER 품질 판단 로직, 품질 점수 계산, 유니버스 스크리닝,
API 엔드포인트를 검증합니다.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.analysis.screener import ScreeningResult, StockFundamentals, StockScreener
from src.analysis.universe import UniverseManager
from src.broker.kis_client import KISClient


# ───────────────── Fixtures ─────────────────


@pytest.fixture()
def mock_kis() -> MagicMock:
    return MagicMock(spec=KISClient)


@pytest.fixture()
def screener(mock_kis: MagicMock) -> StockScreener:
    return StockScreener(mock_kis)


def _make_fundamentals(**overrides: object) -> StockFundamentals:
    """테스트용 StockFundamentals 팩토리."""
    defaults = {
        "stock_code": "005930",
        "stock_name": "삼성전자",
        "per": 8.0,
        "pbr": 1.2,
        "roe": 15.0,
        "dividend_yield": 2.0,
        "operating_margin": 15.0,
        "revenue_growth_yoy": 10.0,
        "sector": "반도체",
        "sector_avg_per": 15.0,
        "sector_avg_operating_margin": 10.0,
        "has_buyback": False,
    }
    defaults.update(overrides)
    return StockFundamentals(**defaults)  # type: ignore[arg-type]


# ───────────────── evaluate_quality 테스트 ─────────────────


class TestEvaluateQuality:
    """PER 품질 판단 테스트"""

    def test_undervalued(self, screener: StockScreener) -> None:
        """진짜 저평가: PER < 업종평균×70%, ROE > 10%, 영업이익률 > 업종평균, 매출성장 > 0%"""
        f = _make_fundamentals(
            per=8.0,  # < 15.0 * 0.7 = 10.5
            roe=15.0,
            operating_margin=15.0,  # > 10.0
            revenue_growth_yoy=10.0,
            dividend_yield=2.0,
        )
        result = screener.evaluate_quality(f)

        assert result.eligible is True
        assert result.quality == "undervalued"
        assert "진짜 저평가" in result.reason

    def test_value_trap_low_roe(self, screener: StockScreener) -> None:
        """가치함정: PER 낮지만 ROE < 5%"""
        f = _make_fundamentals(
            per=5.0,  # < 10.5
            roe=3.0,  # < 5%
            revenue_growth_yoy=5.0,
        )
        result = screener.evaluate_quality(f)

        assert result.eligible is False
        assert result.quality == "value_trap"
        assert "ROE" in result.reason

    def test_value_trap_revenue_decline(self, screener: StockScreener) -> None:
        """가치함정: PER 낮지만 매출 역성장"""
        f = _make_fundamentals(
            per=5.0,
            roe=12.0,
            revenue_growth_yoy=-5.0,  # 매출 역성장
        )
        result = screener.evaluate_quality(f)

        assert result.eligible is False
        assert result.quality == "value_trap"
        assert "매출 역성장" in result.reason

    def test_poor_shareholder_return(self, screener: StockScreener) -> None:
        """주주환원 미흡: PER 낮고 ROE 높지만 배당 < 1% AND 자사주 매입 없음"""
        f = _make_fundamentals(
            per=8.0,  # < 10.5
            roe=12.0,  # > 10%
            operating_margin=8.0,  # < 10.0 (업종평균 이하 → 저평가 조건 미충족)
            revenue_growth_yoy=5.0,
            dividend_yield=0.5,  # < 1%
            has_buyback=False,
        )
        result = screener.evaluate_quality(f)

        assert result.eligible is False
        assert result.quality == "poor_shareholder_return"

    def test_poor_shareholder_return_eligible_false(
        self, screener: StockScreener
    ) -> None:
        """주주환원 미흡 종목은 반드시 eligible=False"""
        f = _make_fundamentals(
            per=7.0,
            roe=20.0,
            operating_margin=8.0,  # 업종평균 이하
            revenue_growth_yoy=15.0,
            dividend_yield=0.3,
            has_buyback=False,
        )
        result = screener.evaluate_quality(f)

        assert result.eligible is False


# ───────────────── get_quality_score 테스트 ─────────────────


class TestQualityScore:
    """품질 점수 계산 테스트"""

    def test_score_range(self, screener: StockScreener) -> None:
        """점수는 0~100 범위"""
        f = _make_fundamentals()
        score = screener.get_quality_score(f)
        assert 0.0 <= score <= 100.0

    def test_high_quality_stock(self, screener: StockScreener) -> None:
        """좋은 지표 → 높은 점수"""
        f = _make_fundamentals(
            per=5.0,
            roe=20.0,
            operating_margin=25.0,
            revenue_growth_yoy=20.0,
            dividend_yield=4.0,
            sector_avg_per=15.0,
            sector_avg_operating_margin=10.0,
        )
        score = screener.get_quality_score(f)
        assert score >= 70.0

    def test_low_quality_stock(self, screener: StockScreener) -> None:
        """나쁜 지표 → 낮은 점수"""
        f = _make_fundamentals(
            per=30.0,
            roe=2.0,
            operating_margin=1.0,
            revenue_growth_yoy=-10.0,
            dividend_yield=0.0,
            sector_avg_per=15.0,
            sector_avg_operating_margin=10.0,
        )
        score = screener.get_quality_score(f)
        assert score < 30.0

    def test_score_components(self, screener: StockScreener) -> None:
        """점수는 5개 항목의 합"""
        # 모든 항목 최대 → 30 + 25 + 20 + 15 + 10 = 100
        f = _make_fundamentals(
            per=0.1,  # PER 매우 낮음 → 30점
            roe=15.0,  # ROE 15% → 25점
            operating_margin=20.0,  # 업종평균의 2배 → 20점
            revenue_growth_yoy=20.0,  # 성장률 20% → 15점
            dividend_yield=5.0,  # 배당 5% → 10점
            sector_avg_per=15.0,
            sector_avg_operating_margin=10.0,
        )
        score = screener.get_quality_score(f)
        assert score == 100.0


# ───────────────── screen_universe 테스트 ─────────────────


class TestScreenUniverse:
    """유니버스 일괄 스크리닝 테스트"""

    def test_screen_multiple_stocks(
        self, screener: StockScreener, mock_kis: MagicMock
    ) -> None:
        """여러 종목 일괄 스크리닝"""
        mock_kis.get_price.return_value = {
            "per": "10.0",
            "pbr": "1.5",
            "hts_kor_isnm": "테스트종목",
        }

        results = screener.screen_universe(["005930", "000660", "035420"])

        assert len(results) == 3
        assert all(isinstance(r, ScreeningResult) for r in results)

    def test_screen_handles_errors(
        self, screener: StockScreener, mock_kis: MagicMock
    ) -> None:
        """API 오류 시 해당 종목 건너뛰기"""
        mock_kis.get_price.side_effect = [
            {"per": "10.0", "pbr": "1.5", "hts_kor_isnm": "정상종목"},
            Exception("API 오류"),
            {"per": "8.0", "pbr": "1.0", "hts_kor_isnm": "정상종목2"},
        ]

        results = screener.screen_universe(["005930", "000660", "035420"])
        assert len(results) == 2


# ───────────────── UniverseManager 테스트 ─────────────────


class TestUniverseManager:
    """유니버스 관리 테스트"""

    def test_list_universes(self) -> None:
        mgr = UniverseManager()
        universes = mgr.list_universes()
        assert len(universes) >= 2
        names = [u.name for u in universes]
        assert "kospi_top30" in names

    def test_get_universe(self) -> None:
        mgr = UniverseManager()
        u = mgr.get_universe("kospi_top30")
        assert u is not None
        assert len(u.stock_codes) == 30

    def test_add_remove_stock(self) -> None:
        mgr = UniverseManager()
        mgr.add_stock("default_watchlist", "999999")
        u = mgr.get_universe("default_watchlist")
        assert u is not None
        assert "999999" in u.stock_codes

        mgr.remove_stock("default_watchlist", "999999")
        assert "999999" not in u.stock_codes


# ───────────────── API 엔드포인트 테스트 ─────────────────


class TestAnalysisAPI:
    """분석 API 엔드포인트 테스트"""

    @pytest.fixture()
    def client(self) -> TestClient:
        from src.main import app

        return TestClient(app)

    def test_list_universes(self, client: TestClient) -> None:
        resp = client.get("/api/v1/analysis/universe")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 2

    def test_screen_stock(self, client: TestClient) -> None:
        mock_client = MagicMock(spec=KISClient)
        mock_client.get_price.return_value = {
            "per": "8.0",
            "pbr": "1.2",
            "hts_kor_isnm": "삼성전자",
        }

        from src.api.dependencies import get_kis_client
        from src.main import app

        app.dependency_overrides[get_kis_client] = lambda: mock_client

        try:
            resp = client.get("/api/v1/analysis/screen/005930")
            assert resp.status_code == 200
            data = resp.json()
            assert data["stock_code"] == "005930"
            assert "quality" in data
            assert "eligible" in data
        finally:
            app.dependency_overrides.clear()

    def test_screen_universe_api(self, client: TestClient) -> None:
        mock_client = MagicMock(spec=KISClient)
        mock_client.get_price.return_value = {
            "per": "10.0",
            "pbr": "1.5",
            "hts_kor_isnm": "테스트",
        }

        from src.api.dependencies import get_kis_client
        from src.main import app

        app.dependency_overrides[get_kis_client] = lambda: mock_client

        try:
            resp = client.post(
                "/api/v1/analysis/screen",
                json={"stock_codes": ["005930", "000660"]},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, list)
            assert len(data) == 2
        finally:
            app.dependency_overrides.clear()

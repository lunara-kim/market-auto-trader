"""히스토리컬 PER Quality 계산 테스트."""

from __future__ import annotations

from src.backtest.historical_per import HistoricalPERCalculator


class TestHistoricalPERCalculator:
    def test_undervalued(self) -> None:
        """trailing EPS로 PER 역산 → 업종평균 미만이면 undervalued."""
        calc = HistoricalPERCalculator(
            yf_fetcher=lambda _sym: {"trailing_eps": 10.0, "per": None},
            sector_map={"AAPL": "IT"},
        )
        # price=200, eps=10 → PER=20, IT 미국 avg_per=30 → undervalued
        result = calc.get_quality("AAPL", current_price=200.0)
        assert result.per == 20.0
        assert result.is_undervalued is True
        assert result.quality_score == 25.0

    def test_not_undervalued(self) -> None:
        calc = HistoricalPERCalculator(
            yf_fetcher=lambda _sym: {"trailing_eps": 5.0, "per": None},
            sector_map={"AAPL": "IT"},
        )
        # price=200, eps=5 → PER=40, IT avg_per=30 → not undervalued
        result = calc.get_quality("AAPL", current_price=200.0)
        assert result.per == 40.0
        assert result.is_undervalued is False
        assert result.quality_score == 0.0

    def test_fallback_to_per_field(self) -> None:
        """trailing_eps가 없으면 per 필드를 직접 사용."""
        calc = HistoricalPERCalculator(
            yf_fetcher=lambda _sym: {"trailing_eps": None, "per": 12.0},
            sector_map={"AAPL": "IT"},
        )
        result = calc.get_quality("AAPL")
        assert result.per == 12.0
        assert result.is_undervalued is True  # 12 < 30

    def test_no_data_returns_zero(self) -> None:
        """EPS도 PER도 없으면 quality_score=0."""
        calc = HistoricalPERCalculator(
            yf_fetcher=lambda _sym: {},
            sector_map={},
        )
        result = calc.get_quality("UNKNOWN")
        assert result.per is None
        assert result.quality_score == 0.0

    def test_cache(self) -> None:
        """같은 심볼 두 번 호출 시 캐시 사용."""
        call_count = 0

        def fetcher(_sym):
            nonlocal call_count
            call_count += 1
            return {"trailing_eps": 10.0, "per": None}

        calc = HistoricalPERCalculator(yf_fetcher=fetcher, sector_map={"X": "IT"})
        calc.get_quality("X", current_price=200.0)
        calc.get_quality("X", current_price=200.0)
        assert call_count == 1

"""
RegimeEngine 단위 테스트
"""

from __future__ import annotations

import pytest

from src.strategy.regime import MarketRegime, RegimeEngine


class TestRegimeEngine:
    @pytest.fixture
    def engine(self) -> RegimeEngine:
        return RegimeEngine()

    # ───────────────── classify ─────────────────

    def test_risk_off_extreme_fear(self, engine: RegimeEngine) -> None:
        assert engine.classify(5) == MarketRegime.RISK_OFF

    def test_risk_off_boundary(self, engine: RegimeEngine) -> None:
        assert engine.classify(29) == MarketRegime.RISK_OFF

    def test_neutral_lower(self, engine: RegimeEngine) -> None:
        assert engine.classify(30) == MarketRegime.NEUTRAL

    def test_neutral_mid(self, engine: RegimeEngine) -> None:
        assert engine.classify(50) == MarketRegime.NEUTRAL

    def test_neutral_upper(self, engine: RegimeEngine) -> None:
        assert engine.classify(64) == MarketRegime.NEUTRAL

    def test_risk_on_boundary(self, engine: RegimeEngine) -> None:
        assert engine.classify(65) == MarketRegime.RISK_ON

    def test_risk_on_extreme_greed(self, engine: RegimeEngine) -> None:
        assert engine.classify(95) == MarketRegime.RISK_ON

    # ───────────────── get_allowed_strategies ─────────────────

    def test_risk_off_allows_mean_reversion_only(self, engine: RegimeEngine) -> None:
        strategies = engine.get_allowed_strategies(MarketRegime.RISK_OFF)
        assert strategies == ["mean_reversion"]

    def test_neutral_allows_both(self, engine: RegimeEngine) -> None:
        strategies = engine.get_allowed_strategies(MarketRegime.NEUTRAL)
        assert "mean_reversion" in strategies
        assert "trend_following" in strategies

    def test_risk_on_allows_trend_following_only(self, engine: RegimeEngine) -> None:
        strategies = engine.get_allowed_strategies(MarketRegime.RISK_ON)
        assert strategies == ["trend_following"]

"""
BaseStrategy (매매 전략 베이스 클래스) 테스트

추상 클래스이므로 직접 인스턴스화 불가 확인,
구체 클래스 상속 후 올바르게 동작하는지 검증합니다.
"""

import pytest
from src.strategy.base import BaseStrategy


class DummyStrategy(BaseStrategy):
    """테스트용 구체 전략 클래스"""

    def analyze(self, market_data):
        """간단한 분석: 종가가 이동평균보다 높으면 bullish"""
        close = market_data.get("close", 0)
        ma = market_data.get("ma", 0)
        trend = "bullish" if close > ma else "bearish"
        return {"trend": trend, "close": close, "ma": ma}

    def generate_signal(self, analysis_result):
        """분석 결과 기반 신호 생성"""
        if analysis_result["trend"] == "bullish":
            return {
                "signal": "buy",
                "strength": 0.8,
                "reason": "종가가 이동평균 상회",
            }
        return {
            "signal": "sell",
            "strength": 0.6,
            "reason": "종가가 이동평균 하회",
        }

    def backtest(self, historical_data, initial_capital):
        """간단한 백테스트: 총 수익률만 계산"""
        if not historical_data:
            return {
                "total_return": 0.0,
                "trades": 0,
                "final_capital": initial_capital,
            }
        first = historical_data[0].get("close", 0)
        last = historical_data[-1].get("close", 0)
        total_return = (last - first) / first if first else 0.0
        return {
            "total_return": total_return,
            "trades": len(historical_data),
            "final_capital": initial_capital * (1 + total_return),
        }


class TestBaseStrategyAbstract:
    """BaseStrategy 추상 클래스 테스트"""

    def test_cannot_instantiate_directly(self):
        """BaseStrategy를 직접 인스턴스화하면 TypeError 발생"""
        with pytest.raises(TypeError):
            BaseStrategy("direct")

    def test_missing_methods_raises_error(self):
        """추상 메서드를 구현하지 않으면 인스턴스화 불가"""

        class IncompleteStrategy(BaseStrategy):
            def analyze(self, market_data):
                return {}

        with pytest.raises(TypeError):
            IncompleteStrategy("incomplete")


class TestDummyStrategy:
    """구체 전략 구현 테스트"""

    @pytest.fixture
    def strategy(self):
        return DummyStrategy("test_strategy")

    def test_strategy_name(self, strategy):
        """전략 이름이 올바르게 설정되는지 확인"""
        assert strategy.name == "test_strategy"

    def test_analyze_bullish(self, strategy):
        """종가 > 이동평균 시 bullish 판단"""
        result = strategy.analyze({"close": 75000, "ma": 70000})
        assert result["trend"] == "bullish"

    def test_analyze_bearish(self, strategy):
        """종가 < 이동평균 시 bearish 판단"""
        result = strategy.analyze({"close": 65000, "ma": 70000})
        assert result["trend"] == "bearish"

    def test_generate_signal_buy(self, strategy):
        """bullish 분석 시 buy 신호 생성"""
        analysis = {"trend": "bullish", "close": 75000, "ma": 70000}
        signal = strategy.generate_signal(analysis)
        assert signal["signal"] == "buy"
        assert 0.0 <= signal["strength"] <= 1.0

    def test_generate_signal_sell(self, strategy):
        """bearish 분석 시 sell 신호 생성"""
        analysis = {"trend": "bearish", "close": 65000, "ma": 70000}
        signal = strategy.generate_signal(analysis)
        assert signal["signal"] == "sell"

    def test_backtest_with_data(self, strategy):
        """과거 데이터로 백테스팅 결과 확인"""
        data = [
            {"close": 50000},
            {"close": 55000},
            {"close": 60000},
        ]
        result = strategy.backtest(data, initial_capital=10_000_000)
        assert result["total_return"] == pytest.approx(0.2)
        assert result["trades"] == 3
        assert result["final_capital"] == pytest.approx(12_000_000)

    def test_backtest_empty_data(self, strategy):
        """빈 데이터로 백테스팅 시 수익률 0"""
        result = strategy.backtest([], initial_capital=10_000_000)
        assert result["total_return"] == 0.0
        assert result["trades"] == 0
        assert result["final_capital"] == 10_000_000

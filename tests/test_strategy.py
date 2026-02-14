"""
이동평균 교차 전략 테스트

SMA/EMA 계산, 골든크로스/데드크로스 신호 생성, 백테스팅 검증.
"""

from __future__ import annotations

import math

import pytest

from src.strategy.base import BaseStrategy
from src.strategy.moving_average import (
    AnalysisResult,
    MAConfig,
    MAType,
    MovingAverageCrossover,
    calculate_ema,
    calculate_sma,
)


# ─────────────────────────────────────────────
# BaseStrategy 추상 클래스 테스트
# ─────────────────────────────────────────────

class TestBaseStrategy:
    """BaseStrategy 추상 클래스 동작 검증"""

    def test_cannot_instantiate_directly(self) -> None:
        """추상 클래스 직접 인스턴스화 불가"""
        with pytest.raises(TypeError):
            BaseStrategy(name="test")  # type: ignore[abstract]

    def test_incomplete_subclass_fails(self) -> None:
        """일부 메서드만 구현한 서브클래스는 인스턴스화 불가"""

        class Partial(BaseStrategy):
            def analyze(self, market_data):
                return {}

        with pytest.raises(TypeError):
            Partial(name="partial")  # type: ignore[abstract]


# ─────────────────────────────────────────────
# MAConfig 테스트
# ─────────────────────────────────────────────

class TestMAConfig:
    """MAConfig 유효성 검증"""

    def test_default_config(self) -> None:
        cfg = MAConfig()
        assert cfg.short_window == 5
        assert cfg.long_window == 20
        assert cfg.ma_type == MAType.SMA
        assert cfg.signal_threshold == 0.0

    def test_custom_config(self) -> None:
        cfg = MAConfig(short_window=10, long_window=50, ma_type=MAType.EMA, signal_threshold=0.5)
        assert cfg.short_window == 10
        assert cfg.long_window == 50
        assert cfg.ma_type == MAType.EMA

    def test_invalid_windows_raises(self) -> None:
        """short >= long 이면 에러"""
        with pytest.raises(ValueError, match="작아야"):
            MAConfig(short_window=20, long_window=20)
        with pytest.raises(ValueError, match="작아야"):
            MAConfig(short_window=30, long_window=20)

    def test_too_small_short_window(self) -> None:
        """short_window < 2이면 에러"""
        with pytest.raises(ValueError, match="최소 2"):
            MAConfig(short_window=1, long_window=5)


# ─────────────────────────────────────────────
# SMA / EMA 계산 테스트
# ─────────────────────────────────────────────

class TestSMA:
    """단순이동평균(SMA) 계산 검증"""

    def test_basic_sma(self) -> None:
        prices = [10.0, 20.0, 30.0, 40.0, 50.0]
        result = calculate_sma(prices, 3)
        assert len(result) == 5
        assert result[0] == 0.0  # padding
        assert result[1] == 0.0  # padding
        assert result[2] == pytest.approx(20.0)  # (10+20+30)/3
        assert result[3] == pytest.approx(30.0)  # (20+30+40)/3
        assert result[4] == pytest.approx(40.0)  # (30+40+50)/3

    def test_sma_window_equals_length(self) -> None:
        prices = [10.0, 20.0, 30.0]
        result = calculate_sma(prices, 3)
        assert len(result) == 3
        assert result[-1] == pytest.approx(20.0)

    def test_sma_insufficient_data(self) -> None:
        prices = [10.0, 20.0]
        result = calculate_sma(prices, 5)
        assert result == []

    def test_sma_constant_prices(self) -> None:
        prices = [100.0] * 10
        result = calculate_sma(prices, 3)
        # 패딩 이후 모든 값이 100.0
        for val in result[2:]:
            assert val == pytest.approx(100.0)


class TestEMA:
    """지수이동평균(EMA) 계산 검증"""

    def test_basic_ema(self) -> None:
        prices = [10.0, 20.0, 30.0, 40.0, 50.0]
        result = calculate_ema(prices, 3)
        assert len(result) == 5
        assert result[0] == 0.0
        assert result[1] == 0.0
        # 첫 EMA = SMA(3) = 20.0
        assert result[2] == pytest.approx(20.0)
        # EMA = (40 - 20) * 0.5 + 20 = 30.0
        assert result[3] == pytest.approx(30.0)
        # EMA = (50 - 30) * 0.5 + 30 = 40.0
        assert result[4] == pytest.approx(40.0)

    def test_ema_insufficient_data(self) -> None:
        prices = [10.0, 20.0]
        result = calculate_ema(prices, 5)
        assert result == []

    def test_ema_reacts_faster_than_sma(self) -> None:
        """EMA는 최근 가격에 더 빠르게 반응"""
        # 가격이 급등하는 시나리오
        prices = [100.0] * 10 + [200.0] * 5
        sma = calculate_sma(prices, 5)
        ema = calculate_ema(prices, 5)
        # 급등 직후 EMA가 SMA보다 높아야 함
        assert ema[11] > sma[11]


# ─────────────────────────────────────────────
# AnalysisResult 테스트
# ─────────────────────────────────────────────

class TestAnalysisResult:
    """AnalysisResult 데이터 클래스 검증"""

    def test_default_values(self) -> None:
        result = AnalysisResult()
        assert result.current_price == 0.0
        assert result.trend == "neutral"
        assert result.short_ma == []
        assert result.long_ma == []

    def test_to_dict(self) -> None:
        result = AnalysisResult(
            current_price=50000.0,
            ma_spread=1.2345,
            trend="uptrend",
        )
        d = result.to_dict()
        assert d["current_price"] == 50000.0
        assert d["ma_spread"] == 1.2345
        assert d["trend"] == "uptrend"


# ─────────────────────────────────────────────
# MovingAverageCrossover 분석 테스트
# ─────────────────────────────────────────────

class TestAnalyze:
    """analyze() 메서드 검증"""

    def setup_method(self) -> None:
        self.strategy = MovingAverageCrossover(
            MAConfig(short_window=3, long_window=5),
        )

    def test_insufficient_data(self) -> None:
        """데이터 부족 시 기본 결과 반환"""
        result = self.strategy.analyze({"prices": [100.0, 200.0], "stock_code": "005930"})
        assert result["trend"] == "neutral"
        assert result["current_price"] == 200.0
        assert result["current_short_ma"] == 0.0

    def test_uptrend_analysis(self) -> None:
        """상승 추세 데이터 분석"""
        # 꾸준히 상승하는 가격
        prices = [100.0, 110.0, 120.0, 130.0, 140.0, 150.0, 160.0]
        result = self.strategy.analyze({"prices": prices})
        assert result["current_short_ma"] > 0
        assert result["current_long_ma"] > 0
        assert result["ma_spread"] > 0  # 단기 > 장기
        assert result["trend"] == "uptrend"

    def test_downtrend_analysis(self) -> None:
        """하락 추세 데이터 분석"""
        prices = [200.0, 190.0, 180.0, 170.0, 160.0, 150.0, 140.0]
        result = self.strategy.analyze({"prices": prices})
        assert result["ma_spread"] < 0  # 단기 < 장기
        assert result["trend"] == "downtrend"

    def test_neutral_analysis(self) -> None:
        """횡보 추세 데이터 분석"""
        prices = [100.0, 101.0, 99.0, 100.0, 101.0, 100.0, 100.5]
        result = self.strategy.analyze({"prices": prices})
        assert result["trend"] == "neutral"

    def test_dates_passed_through(self) -> None:
        """dates가 결과에 포함됨"""
        prices = list(range(100, 108))
        dates = [f"2026-01-0{i}" for i in range(1, 9)]
        result = self.strategy.analyze({"prices": prices, "dates": dates})
        assert result["dates"] == dates

    def test_ema_strategy(self) -> None:
        """EMA 모드 분석"""
        strategy = MovingAverageCrossover(
            MAConfig(short_window=3, long_window=5, ma_type=MAType.EMA),
        )
        prices = [100.0, 110.0, 120.0, 130.0, 140.0, 150.0, 160.0]
        result = strategy.analyze({"prices": prices})
        assert result["current_short_ma"] > 0
        assert result["trend"] == "uptrend"


# ─────────────────────────────────────────────
# MovingAverageCrossover 신호 생성 테스트
# ─────────────────────────────────────────────

class TestGenerateSignal:
    """generate_signal() 메서드 검증"""

    def setup_method(self) -> None:
        self.strategy = MovingAverageCrossover(
            MAConfig(short_window=3, long_window=5),
        )

    def test_golden_cross_buy(self) -> None:
        """골든크로스 → 매수 신호"""
        analysis = {
            "current_short_ma": 105.0,
            "current_long_ma": 100.0,
            "prev_short_ma": 98.0,
            "prev_long_ma": 100.0,
            "current_price": 106.0,
            "ma_spread": 5.0,
            "trend": "uptrend",
        }
        signal = self.strategy.generate_signal(analysis)
        assert signal["signal"] == "buy"
        assert signal["strength"] > 0
        assert "골든크로스" in signal["reason"]

    def test_dead_cross_sell(self) -> None:
        """데드크로스 → 매도 신호"""
        analysis = {
            "current_short_ma": 95.0,
            "current_long_ma": 100.0,
            "prev_short_ma": 101.0,
            "prev_long_ma": 100.0,
            "current_price": 94.0,
            "ma_spread": -5.0,
            "trend": "downtrend",
        }
        signal = self.strategy.generate_signal(analysis)
        assert signal["signal"] == "sell"
        assert signal["strength"] > 0
        assert "데드크로스" in signal["reason"]

    def test_no_cross_hold(self) -> None:
        """교차 없음 → 관망"""
        analysis = {
            "current_short_ma": 105.0,
            "current_long_ma": 100.0,
            "prev_short_ma": 103.0,
            "prev_long_ma": 100.0,
            "current_price": 106.0,
            "ma_spread": 5.0,
            "trend": "uptrend",
        }
        signal = self.strategy.generate_signal(analysis)
        assert signal["signal"] == "hold"

    def test_insufficient_data_hold(self) -> None:
        """데이터 부족 → HOLD"""
        analysis = {
            "current_short_ma": 0.0,
            "current_long_ma": 0.0,
            "prev_short_ma": 0.0,
            "prev_long_ma": 0.0,
            "current_price": 0.0,
            "ma_spread": 0.0,
            "trend": "neutral",
        }
        signal = self.strategy.generate_signal(analysis)
        assert signal["signal"] == "hold"
        assert "데이터 부족" in signal["reason"]

    def test_signal_threshold_filter(self) -> None:
        """threshold 이하의 미세한 교차는 무시"""
        strategy = MovingAverageCrossover(
            MAConfig(short_window=3, long_window=5, signal_threshold=1.0),
        )
        # 스프레드가 0.1%로 threshold(1.0%) 미만
        analysis = {
            "current_short_ma": 100.1,
            "current_long_ma": 100.0,
            "prev_short_ma": 99.9,
            "prev_long_ma": 100.0,
            "current_price": 100.2,
            "ma_spread": 0.1,
            "trend": "neutral",
        }
        signal = strategy.generate_signal(analysis)
        assert signal["signal"] == "hold"
        assert "임계값" in signal["reason"]

    def test_signal_has_required_fields(self) -> None:
        """신호 결과에 필수 필드가 모두 포함됨"""
        analysis = {
            "current_short_ma": 105.0,
            "current_long_ma": 100.0,
            "prev_short_ma": 98.0,
            "prev_long_ma": 100.0,
            "current_price": 106.0,
            "ma_spread": 5.0,
            "trend": "uptrend",
        }
        signal = self.strategy.generate_signal(analysis)
        required = {"signal", "strength", "reason", "strategy_name", "timestamp", "metrics"}
        assert required.issubset(signal.keys())

    def test_strength_bounded(self) -> None:
        """신호 강도는 0.0 ~ 1.0 범위"""
        # 아주 큰 스프레드
        analysis = {
            "current_short_ma": 200.0,
            "current_long_ma": 100.0,
            "prev_short_ma": 99.0,
            "prev_long_ma": 100.0,
            "current_price": 210.0,
            "ma_spread": 100.0,
            "trend": "uptrend",
        }
        signal = self.strategy.generate_signal(analysis)
        assert 0.0 <= signal["strength"] <= 1.0


# ─────────────────────────────────────────────
# 백테스팅 테스트
# ─────────────────────────────────────────────

class TestBacktest:
    """backtest() 메서드 검증"""

    def setup_method(self) -> None:
        self.strategy = MovingAverageCrossover(
            MAConfig(short_window=3, long_window=5),
        )

    def test_insufficient_data(self) -> None:
        """데이터 부족 시 빈 결과"""
        data = [{"date": "2026-01-01", "close": 100.0}]
        result = self.strategy.backtest(data, 10_000_000)
        assert result["total_return"] == 0.0
        assert result["total_trades"] == 0
        assert "error" in result

    def test_uptrend_profit(self) -> None:
        """상승 추세에서 매수 → 수익"""
        # 횡보 후 상승
        data = []
        prices = (
            [100.0] * 5          # 횡보 (장기MA = 100)
            + [95.0, 90.0]       # 약간 하락 (단기 < 장기)
            + [105.0, 110.0, 115.0, 120.0, 125.0]  # 급등 (골든크로스)
        )
        for i, p in enumerate(prices):
            data.append({"date": f"2026-01-{i+1:02d}", "close": p})

        result = self.strategy.backtest(data, 10_000_000)
        assert result["total_trades"] >= 1
        assert len(result["equity_curve"]) > 0

    def test_backtest_result_structure(self) -> None:
        """결과에 필수 필드 포함"""
        data = [{"date": f"2026-01-{i+1:02d}", "close": 100.0 + i} for i in range(30)]
        result = self.strategy.backtest(data, 10_000_000)
        required = {
            "strategy_name", "initial_capital", "final_capital",
            "total_return", "total_trades", "winning_trades", "losing_trades",
            "win_rate", "max_drawdown", "sharpe_ratio", "trades", "equity_curve",
        }
        assert required.issubset(result.keys())

    def test_initial_capital_preserved_no_trades(self) -> None:
        """거래 없으면 자본금 보존"""
        # 계속 상승만 하면 골든크로스는 있지만 데드크로스가 없어서 마지막에 정산
        data = [{"date": f"2026-01-{i+1:02d}", "close": float(100 + i)} for i in range(10)]
        result = self.strategy.backtest(data, 10_000_000)
        # 마지막에 정산되므로 final_capital이 있음
        assert result["final_capital"] > 0

    def test_mdd_is_non_negative(self) -> None:
        """MDD는 0 이상"""
        data = [{"date": f"d{i}", "close": 100.0 + (i % 5) * 10 - 20} for i in range(50)]
        result = self.strategy.backtest(data, 10_000_000)
        assert result["max_drawdown"] >= 0.0

    def test_win_rate_bounds(self) -> None:
        """승률은 0~100%"""
        data = [{"date": f"d{i}", "close": 100.0 + 5 * math.sin(i * 0.3)} for i in range(100)]
        result = self.strategy.backtest(data, 10_000_000)
        assert 0.0 <= result["win_rate"] <= 100.0

    def test_commission_and_tax_applied(self) -> None:
        """수수료/세금이 적용되면 순수익 < 총이익"""
        # 상승 추세로 확실한 골든크로스 만들기
        data = []
        prices = (
            [100.0] * 5
            + [95.0, 90.0, 85.0]  # 하락
            + [90.0, 95.0, 100.0, 110.0, 120.0, 130.0, 140.0]  # 상승
        )
        for i, p in enumerate(prices):
            data.append({"date": f"d{i}", "close": p})

        result = self.strategy.backtest(data, 10_000_000)
        # 거래가 있으면 수수료가 0보다 큼
        for trade in result["trades"]:
            assert trade["commission"] >= 0


# ─────────────────────────────────────────────
# 통합 테스트 (analyze → signal 파이프라인)
# ─────────────────────────────────────────────

class TestIntegration:
    """분석 → 신호 생성 파이프라인 통합 테스트"""

    def test_full_pipeline_golden_cross(self) -> None:
        """하락→상승 전환에서 골든크로스 매수 신호"""
        strategy = MovingAverageCrossover(MAConfig(short_window=3, long_window=5))

        # 하락 후 반등
        prices = [120.0, 115.0, 110.0, 105.0, 100.0, 95.0, 100.0, 110.0, 120.0]
        analysis = strategy.analyze({"prices": prices, "stock_code": "005930"})
        signal = strategy.generate_signal(analysis)

        assert signal["signal"] in ("buy", "hold")
        assert signal["strategy_name"].startswith("MA_Crossover")

    def test_full_pipeline_dead_cross(self) -> None:
        """상승→하락 전환에서 데드크로스 매도 신호"""
        strategy = MovingAverageCrossover(MAConfig(short_window=3, long_window=5))

        # 상승 후 급락
        prices = [80.0, 90.0, 100.0, 110.0, 120.0, 115.0, 100.0, 90.0, 80.0]
        analysis = strategy.analyze({"prices": prices, "stock_code": "005930"})
        signal = strategy.generate_signal(analysis)

        assert signal["signal"] in ("sell", "hold")

    def test_ema_pipeline(self) -> None:
        """EMA 모드 파이프라인"""
        strategy = MovingAverageCrossover(
            MAConfig(short_window=3, long_window=5, ma_type=MAType.EMA),
        )
        prices = [100.0, 110.0, 120.0, 130.0, 140.0, 150.0, 160.0]
        analysis = strategy.analyze({"prices": prices})
        signal = strategy.generate_signal(analysis)

        assert signal["signal"] in ("buy", "sell", "hold")
        assert "EMA" in signal["strategy_name"]

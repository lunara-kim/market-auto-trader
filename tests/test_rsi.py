"""
RSI 전략 테스트

RSI 계산 정확성, 과매수/과매도 신호 생성, 백테스팅 검증.
"""

from __future__ import annotations

import math

import pytest

from src.strategy.rsi import (
    RSIConfig,
    RSIStrategy,
    SignalType,
    calculate_rsi,
)


# ─────────────────────────────────────────────
# RSIConfig 테스트
# ─────────────────────────────────────────────

class TestRSIConfig:
    """RSIConfig 유효성 검증"""

    def test_default_config(self) -> None:
        cfg = RSIConfig()
        assert cfg.period == 14
        assert cfg.overbought == 70.0
        assert cfg.oversold == 30.0
        assert cfg.signal_threshold == 0.0

    def test_custom_config(self) -> None:
        cfg = RSIConfig(period=10, overbought=80, oversold=20, signal_threshold=0.5)
        assert cfg.period == 10
        assert cfg.overbought == 80.0
        assert cfg.oversold == 20.0
        assert cfg.signal_threshold == 0.5

    def test_too_small_period_raises(self) -> None:
        """period < 2이면 에러"""
        with pytest.raises(ValueError, match="최소 2"):
            RSIConfig(period=1)

    def test_invalid_overbought_oversold_raises(self) -> None:
        """oversold >= overbought이면 에러"""
        with pytest.raises(ValueError, match="올바르지 않습니다"):
            RSIConfig(overbought=30, oversold=70)

    def test_overbought_equals_oversold_raises(self) -> None:
        """overbought == oversold이면 에러"""
        with pytest.raises(ValueError, match="올바르지 않습니다"):
            RSIConfig(overbought=50, oversold=50)

    def test_boundary_zero_oversold_raises(self) -> None:
        """oversold가 0이면 에러"""
        with pytest.raises(ValueError, match="올바르지 않습니다"):
            RSIConfig(oversold=0)

    def test_boundary_100_overbought_raises(self) -> None:
        """overbought가 100이면 에러"""
        with pytest.raises(ValueError, match="올바르지 않습니다"):
            RSIConfig(overbought=100)


# ─────────────────────────────────────────────
# RSI 계산 테스트
# ─────────────────────────────────────────────

class TestCalculateRSI:
    """calculate_rsi() 함수 검증"""

    def test_basic_rsi(self) -> None:
        """단순 상승 데이터에서 RSI ≈ 100"""
        # 계속 상승하면 avg_loss = 0 → RSI = 100
        prices = [float(i) for i in range(1, 20)]
        result = calculate_rsi(prices, period=14)
        assert len(result) == len(prices)
        # 패딩 영역은 0.0
        for val in result[:14]:
            assert val == 0.0
        # 상승만 있으면 RSI = 100
        assert result[14] == 100.0

    def test_basic_rsi_downtrend(self) -> None:
        """단순 하락 데이터에서 RSI ≈ 0"""
        prices = [float(100 - i) for i in range(20)]
        result = calculate_rsi(prices, period=14)
        assert len(result) == 20
        # 하락만 있으면 RSI = 0
        assert result[14] == pytest.approx(0.0)

    def test_rsi_range(self) -> None:
        """RSI는 항상 0~100 범위"""
        # 변동이 큰 데이터
        prices = [100.0 + 20 * math.sin(i * 0.5) for i in range(50)]
        result = calculate_rsi(prices, period=14)
        for val in result[14:]:
            assert 0.0 <= val <= 100.0

    def test_insufficient_data(self) -> None:
        """데이터 부족 시 빈 리스트 반환"""
        prices = [100.0, 110.0, 105.0]
        result = calculate_rsi(prices, period=14)
        assert result == []

    def test_rsi_padding(self) -> None:
        """처음 period개는 0.0 패딩"""
        prices = [100.0 + i for i in range(30)]
        result = calculate_rsi(prices, period=5)
        assert len(result) == 30
        for val in result[:5]:
            assert val == 0.0
        # 5번째부터는 값이 있음
        assert result[5] > 0

    def test_constant_prices(self) -> None:
        """가격 변동 없으면 RSI = 100 (상승/하락 모두 0 → 특수 케이스)"""
        prices = [100.0] * 20
        result = calculate_rsi(prices, period=14)
        # avg_gain=0, avg_loss=0이면 첫 RSI에서 avg_loss=0 → RSI=100
        # 이후에도 변동 없으므로 avg_gain=0, avg_loss=0 → RSI=100
        # (구현에 따라 다를 수 있지만 avg_loss=0이면 100)
        for val in result[14:]:
            assert val == 100.0

    def test_rsi_period_2(self) -> None:
        """최소 기간(2)으로 RSI 계산"""
        prices = [100.0, 110.0, 105.0, 115.0, 108.0]
        result = calculate_rsi(prices, period=2)
        assert len(result) == 5
        assert result[0] == 0.0
        assert result[1] == 0.0
        assert result[2] > 0  # 값이 존재


# ─────────────────────────────────────────────
# RSIStrategy 분석 테스트
# ─────────────────────────────────────────────

class TestRSIAnalyze:
    """RSIStrategy.analyze() 메서드 검증"""

    def setup_method(self) -> None:
        self.strategy = RSIStrategy(RSIConfig(period=5))

    def test_insufficient_data(self) -> None:
        """데이터 부족 시 기본 결과 반환"""
        result = self.strategy.analyze({"prices": [100.0, 200.0], "stock_code": "005930"})
        assert result["zone"] == "neutral"
        assert result["current_rsi"] == 0.0
        assert result["rsi_values"] == []

    def test_overbought_zone(self) -> None:
        """과매수 구간 감지"""
        # 급격한 상승 → RSI 높음
        prices = [100.0] * 5 + [110.0, 120.0, 130.0, 140.0, 150.0]
        result = self.strategy.analyze({"prices": prices})
        assert result["current_rsi"] > 0
        assert result["zone"] == "overbought"

    def test_oversold_zone(self) -> None:
        """과매도 구간 감지"""
        # 급격한 하락 → RSI 낮음
        prices = [100.0] * 5 + [90.0, 80.0, 70.0, 60.0, 50.0]
        result = self.strategy.analyze({"prices": prices})
        assert result["current_rsi"] < 30
        assert result["zone"] == "oversold"

    def test_neutral_zone(self) -> None:
        """중립 구간 감지"""
        # 완만한 변동
        prices = [100.0, 101.0, 99.0, 100.0, 101.0, 99.5, 100.5, 100.0]
        result = self.strategy.analyze({"prices": prices})
        assert result["zone"] == "neutral"
        assert 30 <= result["current_rsi"] <= 70

    def test_dates_passed_through(self) -> None:
        """dates가 결과에 포함됨"""
        prices = [100.0 + i for i in range(10)]
        dates = [f"2026-01-{i+1:02d}" for i in range(10)]
        result = self.strategy.analyze({"prices": prices, "dates": dates})
        assert result["dates"] == dates

    def test_prev_rsi_exists(self) -> None:
        """이전 RSI 값이 존재"""
        prices = [100.0 + i * 2 for i in range(15)]
        result = self.strategy.analyze({"prices": prices})
        assert result["prev_rsi"] > 0


# ─────────────────────────────────────────────
# RSIStrategy 신호 생성 테스트
# ─────────────────────────────────────────────

class TestRSIGenerateSignal:
    """RSIStrategy.generate_signal() 메서드 검증"""

    def setup_method(self) -> None:
        self.strategy = RSIStrategy(RSIConfig(period=5))

    def test_oversold_exit_buy(self) -> None:
        """과매도 탈출 → 매수 신호"""
        analysis = {
            "rsi_values": [25.0, 31.0],
            "current_rsi": 31.0,
            "prev_rsi": 25.0,
            "current_price": 100.0,
            "zone": "neutral",
        }
        signal = self.strategy.generate_signal(analysis)
        assert signal["signal"] == "buy"
        assert signal["strength"] > 0
        assert "과매도 탈출" in signal["reason"]

    def test_overbought_entry_sell(self) -> None:
        """과매수 진입 → 매도 신호"""
        analysis = {
            "rsi_values": [65.0, 75.0],
            "current_rsi": 75.0,
            "prev_rsi": 65.0,
            "current_price": 100.0,
            "zone": "overbought",
        }
        signal = self.strategy.generate_signal(analysis)
        assert signal["signal"] == "sell"
        assert signal["strength"] > 0
        assert "과매수 진입" in signal["reason"]

    def test_neutral_hold(self) -> None:
        """중립 구간 → 관망"""
        analysis = {
            "rsi_values": [50.0, 55.0],
            "current_rsi": 55.0,
            "prev_rsi": 50.0,
            "current_price": 100.0,
            "zone": "neutral",
        }
        signal = self.strategy.generate_signal(analysis)
        assert signal["signal"] == "hold"

    def test_insufficient_data_hold(self) -> None:
        """데이터 부족 → HOLD"""
        analysis = {
            "rsi_values": [],
            "current_rsi": 0.0,
            "prev_rsi": 0.0,
            "current_price": 0.0,
            "zone": "neutral",
        }
        signal = self.strategy.generate_signal(analysis)
        assert signal["signal"] == "hold"
        assert "데이터 부족" in signal["reason"]

    def test_signal_threshold_filter(self) -> None:
        """threshold 이하의 약한 신호는 무시"""
        strategy = RSIStrategy(RSIConfig(period=5, signal_threshold=0.5))
        # 과매도에서 살짝 탈출 (강도 낮음)
        analysis = {
            "rsi_values": [29.5, 30.5],
            "current_rsi": 30.5,
            "prev_rsi": 29.5,
            "current_price": 100.0,
            "zone": "neutral",
        }
        signal = strategy.generate_signal(analysis)
        assert signal["signal"] == "hold"
        assert "임계값" in signal["reason"]

    def test_signal_has_required_fields(self) -> None:
        """신호 결과에 필수 필드가 모두 포함됨"""
        analysis = {
            "rsi_values": [25.0, 35.0],
            "current_rsi": 35.0,
            "prev_rsi": 25.0,
            "current_price": 100.0,
            "zone": "neutral",
        }
        signal = self.strategy.generate_signal(analysis)
        required = {"signal", "strength", "reason", "strategy_name", "timestamp", "metrics"}
        assert required.issubset(signal.keys())

    def test_strength_bounded(self) -> None:
        """신호 강도는 0.0 ~ 1.0 범위"""
        analysis = {
            "rsi_values": [10.0, 50.0],
            "current_rsi": 50.0,
            "prev_rsi": 10.0,
            "current_price": 100.0,
            "zone": "neutral",
        }
        signal = self.strategy.generate_signal(analysis)
        assert 0.0 <= signal["strength"] <= 1.0

    def test_staying_oversold_no_signal(self) -> None:
        """과매도 구간에 머물러 있으면 매수 신호 없음"""
        analysis = {
            "rsi_values": [20.0, 25.0],
            "current_rsi": 25.0,
            "prev_rsi": 20.0,
            "current_price": 100.0,
            "zone": "oversold",
        }
        signal = self.strategy.generate_signal(analysis)
        assert signal["signal"] == "hold"


# ─────────────────────────────────────────────
# RSI 백테스팅 테스트
# ─────────────────────────────────────────────

class TestRSIBacktest:
    """RSIStrategy.backtest() 메서드 검증"""

    def setup_method(self) -> None:
        self.strategy = RSIStrategy(RSIConfig(period=5))

    def test_insufficient_data(self) -> None:
        """데이터 부족 시 빈 결과"""
        data = [{"date": "2026-01-01", "close": 100.0}]
        result = self.strategy.backtest(data, 10_000_000)
        assert result["total_return"] == 0.0
        assert result["total_trades"] == 0
        assert "error" in result

    def test_backtest_result_structure(self) -> None:
        """결과에 필수 필드 포함"""
        prices = [100.0 + 10 * math.sin(i * 0.3) for i in range(50)]
        data = [{"date": f"d{i}", "close": p} for i, p in enumerate(prices)]
        result = self.strategy.backtest(data, 10_000_000)
        required = {
            "strategy_name", "initial_capital", "final_capital",
            "total_return", "total_trades", "winning_trades", "losing_trades",
            "win_rate", "max_drawdown", "sharpe_ratio", "trades", "equity_curve",
        }
        assert required.issubset(result.keys())

    def test_mdd_is_non_negative(self) -> None:
        """MDD는 0 이상"""
        prices = [100.0 + 20 * math.sin(i * 0.2) for i in range(80)]
        data = [{"date": f"d{i}", "close": p} for i, p in enumerate(prices)]
        result = self.strategy.backtest(data, 10_000_000)
        assert result["max_drawdown"] >= 0.0

    def test_win_rate_bounds(self) -> None:
        """승률은 0~100%"""
        prices = [100.0 + 15 * math.sin(i * 0.3) for i in range(100)]
        data = [{"date": f"d{i}", "close": p} for i, p in enumerate(prices)]
        result = self.strategy.backtest(data, 10_000_000)
        assert 0.0 <= result["win_rate"] <= 100.0

    def test_commission_applied(self) -> None:
        """수수료가 적용됨"""
        # 큰 변동으로 거래 유도
        prices = (
            [100.0] * 6
            + [80.0, 70.0, 60.0, 50.0]       # 급락 → 과매도
            + [60.0, 70.0, 80.0, 90.0, 100.0] # 반등 → 과매도 탈출
            + [110.0, 120.0, 130.0, 140.0]     # 상승 → 과매수
        )
        data = [{"date": f"d{i}", "close": p} for i, p in enumerate(prices)]
        result = self.strategy.backtest(data, 10_000_000)
        for trade in result["trades"]:
            assert trade["commission"] >= 0

    def test_equity_curve_exists(self) -> None:
        """equity_curve가 생성됨"""
        prices = [100.0 + i for i in range(20)]
        data = [{"date": f"d{i}", "close": p} for i, p in enumerate(prices)]
        result = self.strategy.backtest(data, 10_000_000)
        assert len(result["equity_curve"]) > 0


# ─────────────────────────────────────────────
# 통합 테스트 (analyze → signal 파이프라인)
# ─────────────────────────────────────────────

class TestRSIIntegration:
    """분석 → 신호 생성 파이프라인 통합 테스트"""

    def test_full_pipeline_oversold_exit(self) -> None:
        """과매도 탈출 시나리오 파이프라인"""
        strategy = RSIStrategy(RSIConfig(period=5))

        # 급락 후 반등
        prices = [100.0] * 5 + [90.0, 80.0, 70.0, 60.0, 50.0, 55.0, 60.0, 70.0]
        analysis = strategy.analyze({"prices": prices, "stock_code": "005930"})
        signal = strategy.generate_signal(analysis)

        assert signal["signal"] in ("buy", "hold")
        assert signal["strategy_name"].startswith("RSI")

    def test_full_pipeline_overbought_entry(self) -> None:
        """과매수 진입 시나리오 파이프라인"""
        strategy = RSIStrategy(RSIConfig(period=5))

        # 급등
        prices = [100.0] * 5 + [110.0, 120.0, 130.0, 140.0, 150.0]
        analysis = strategy.analyze({"prices": prices, "stock_code": "005930"})
        signal = strategy.generate_signal(analysis)

        assert signal["signal"] in ("sell", "hold")

    def test_strategy_name_format(self) -> None:
        """전략 이름 형식 확인"""
        strategy = RSIStrategy(RSIConfig(period=14))
        assert strategy.name == "RSI(14)"

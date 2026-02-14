"""
볼린저 밴드 전략 테스트

밴드 계산 정확성, 이탈/복귀 신호 생성, 백테스팅 검증.
"""

from __future__ import annotations

import math

import pytest

from src.strategy.bollinger_bands import (
    BollingerBandStrategy,
    BollingerConfig,
    calculate_bollinger_bands,
)


# ─────────────────────────────────────────────
# BollingerConfig 테스트
# ─────────────────────────────────────────────

class TestBollingerConfig:
    """BollingerConfig 유효성 검증"""

    def test_default_config(self) -> None:
        cfg = BollingerConfig()
        assert cfg.period == 20
        assert cfg.num_std == 2.0
        assert cfg.signal_threshold == 0.0

    def test_custom_config(self) -> None:
        cfg = BollingerConfig(period=10, num_std=1.5, signal_threshold=0.3)
        assert cfg.period == 10
        assert cfg.num_std == 1.5
        assert cfg.signal_threshold == 0.3

    def test_too_small_period_raises(self) -> None:
        """period < 2이면 에러"""
        with pytest.raises(ValueError, match="최소 2"):
            BollingerConfig(period=1)

    def test_zero_num_std_raises(self) -> None:
        """num_std가 0이면 에러"""
        with pytest.raises(ValueError, match="0보다 커야"):
            BollingerConfig(num_std=0.0)

    def test_negative_num_std_raises(self) -> None:
        """num_std가 음수이면 에러"""
        with pytest.raises(ValueError, match="0보다 커야"):
            BollingerConfig(num_std=-1.0)


# ─────────────────────────────────────────────
# 볼린저 밴드 계산 테스트
# ─────────────────────────────────────────────

class TestCalculateBollingerBands:
    """calculate_bollinger_bands() 함수 검증"""

    def test_basic_bands(self) -> None:
        """기본 볼린저 밴드 계산"""
        prices = [float(i) for i in range(1, 22)]  # 1~21
        bands = calculate_bollinger_bands(prices, period=5, num_std=2.0)
        assert len(bands["middle"]) == 21
        assert len(bands["upper"]) == 21
        assert len(bands["lower"]) == 21

        # 패딩 영역은 0.0
        for key in ("middle", "upper", "lower"):
            for val in bands[key][:4]:
                assert val == 0.0

        # 5번째부터 값 존재
        assert bands["middle"][4] > 0
        assert bands["upper"][4] > bands["middle"][4]
        assert bands["lower"][4] < bands["middle"][4]

    def test_upper_above_middle_above_lower(self) -> None:
        """항상 upper > middle > lower"""
        prices = [100.0 + 10 * math.sin(i * 0.5) for i in range(30)]
        bands = calculate_bollinger_bands(prices, period=10, num_std=2.0)
        for i in range(9, len(prices)):
            assert bands["upper"][i] >= bands["middle"][i]
            assert bands["middle"][i] >= bands["lower"][i]

    def test_constant_prices(self) -> None:
        """가격 변동 없으면 upper == middle == lower (std = 0)"""
        prices = [100.0] * 25
        bands = calculate_bollinger_bands(prices, period=5, num_std=2.0)
        for i in range(4, 25):
            assert bands["middle"][i] == pytest.approx(100.0)
            assert bands["upper"][i] == pytest.approx(100.0)
            assert bands["lower"][i] == pytest.approx(100.0)

    def test_insufficient_data(self) -> None:
        """데이터 부족 시 빈 딕셔너리 반환"""
        prices = [100.0, 110.0]
        bands = calculate_bollinger_bands(prices, period=5)
        assert bands["middle"] == []
        assert bands["upper"] == []
        assert bands["lower"] == []

    def test_middle_is_sma(self) -> None:
        """middle은 SMA"""
        prices = [10.0, 20.0, 30.0, 40.0, 50.0]
        bands = calculate_bollinger_bands(prices, period=3, num_std=2.0)
        # SMA(3) at index 2: (10+20+30)/3 = 20
        assert bands["middle"][2] == pytest.approx(20.0)
        # SMA(3) at index 3: (20+30+40)/3 = 30
        assert bands["middle"][3] == pytest.approx(30.0)
        # SMA(3) at index 4: (30+40+50)/3 = 40
        assert bands["middle"][4] == pytest.approx(40.0)

    def test_bandwidth_with_known_values(self) -> None:
        """알려진 값으로 밴드폭 계산 검증"""
        # [10, 20, 30] → SMA=20, std=sqrt((100+0+100)/3)=sqrt(200/3)
        prices = [10.0, 20.0, 30.0]
        bands = calculate_bollinger_bands(prices, period=3, num_std=1.0)
        expected_std = (200.0 / 3.0) ** 0.5
        assert bands["upper"][2] == pytest.approx(20.0 + expected_std, abs=0.01)
        assert bands["lower"][2] == pytest.approx(20.0 - expected_std, abs=0.01)

    def test_num_std_affects_width(self) -> None:
        """num_std가 클수록 밴드폭 증가"""
        prices = [100.0 + 5 * math.sin(i * 0.5) for i in range(30)]
        bands_1 = calculate_bollinger_bands(prices, period=10, num_std=1.0)
        bands_2 = calculate_bollinger_bands(prices, period=10, num_std=2.0)
        for i in range(9, 30):
            width_1 = bands_1["upper"][i] - bands_1["lower"][i]
            width_2 = bands_2["upper"][i] - bands_2["lower"][i]
            assert width_2 > width_1


# ─────────────────────────────────────────────
# BollingerBandStrategy 분석 테스트
# ─────────────────────────────────────────────

class TestBollingerAnalyze:
    """BollingerBandStrategy.analyze() 메서드 검증"""

    def setup_method(self) -> None:
        self.strategy = BollingerBandStrategy(BollingerConfig(period=5))

    def test_insufficient_data(self) -> None:
        """데이터 부족 시 기본 결과 반환"""
        result = self.strategy.analyze({"prices": [100.0, 200.0], "stock_code": "005930"})
        assert result["zone"] == "neutral"
        assert result["current_upper"] == 0.0
        assert result["middle"] == []

    def test_above_upper_zone(self) -> None:
        """상단 밴드 위 감지"""
        # period=5일 때 단일 극단값으로는 밴드 초과 불가 (max z = √(N-1) = 2 = num_std)
        # period=10을 사용하면 max z = √9 = 3 > 2 이므로 초과 가능
        strategy = BollingerBandStrategy(BollingerConfig(period=10))
        prices = [100.0] * 10 + [300.0]
        result = strategy.analyze({"prices": prices})
        assert result["zone"] == "above_upper"
        assert result["percent_b"] > 1.0

    def test_below_lower_zone(self) -> None:
        """하단 밴드 아래 감지"""
        strategy = BollingerBandStrategy(BollingerConfig(period=10))
        prices = [100.0] * 10 + [0.0]
        result = strategy.analyze({"prices": prices})
        assert result["zone"] == "below_lower"
        assert result["percent_b"] < 0.0

    def test_neutral_zone(self) -> None:
        """중립 구간 감지"""
        prices = [100.0, 101.0, 99.0, 100.0, 101.0, 100.5]
        result = self.strategy.analyze({"prices": prices})
        assert result["zone"] == "neutral"
        assert 0.0 <= result["percent_b"] <= 1.0

    def test_dates_passed_through(self) -> None:
        """dates가 결과에 포함됨"""
        prices = [100.0 + i for i in range(10)]
        dates = [f"2026-01-{i+1:02d}" for i in range(10)]
        result = self.strategy.analyze({"prices": prices, "dates": dates})
        assert result["dates"] == dates

    def test_bandwidth_positive(self) -> None:
        """밴드폭은 양수 (변동이 있을 때)"""
        prices = [100.0 + 10 * math.sin(i * 0.5) for i in range(15)]
        result = self.strategy.analyze({"prices": prices})
        assert result["bandwidth"] > 0

    def test_percent_b_calculation(self) -> None:
        """%B 계산이 합리적"""
        # 가격이 중심선 부근이면 %B ≈ 0.5
        prices = [100.0, 101.0, 99.0, 100.0, 101.0, 100.0]
        result = self.strategy.analyze({"prices": prices})
        assert 0.0 <= result["percent_b"] <= 1.0


# ─────────────────────────────────────────────
# BollingerBandStrategy 신호 생성 테스트
# ─────────────────────────────────────────────

class TestBollingerGenerateSignal:
    """BollingerBandStrategy.generate_signal() 메서드 검증"""

    def setup_method(self) -> None:
        self.strategy = BollingerBandStrategy(BollingerConfig(period=5))

    def test_lower_exit_buy(self) -> None:
        """하단 이탈 후 복귀 → 매수 신호"""
        analysis = {
            "middle": [100.0],
            "current_price": 95.0,
            "prev_price": 88.0,
            "current_upper": 110.0,
            "current_lower": 90.0,
            "current_middle": 100.0,
            "prev_upper": 110.0,
            "prev_lower": 90.0,
            "percent_b": 0.25,
            "bandwidth": 20.0,
            "zone": "neutral",
        }
        signal = self.strategy.generate_signal(analysis)
        assert signal["signal"] == "buy"
        assert signal["strength"] > 0
        assert "하단 이탈 후 복귀" in signal["reason"]

    def test_upper_exit_sell(self) -> None:
        """상단 돌파 후 복귀 → 매도 신호"""
        analysis = {
            "middle": [100.0],
            "current_price": 108.0,
            "prev_price": 115.0,
            "current_upper": 110.0,
            "current_lower": 90.0,
            "current_middle": 100.0,
            "prev_upper": 110.0,
            "prev_lower": 90.0,
            "percent_b": 0.9,
            "bandwidth": 20.0,
            "zone": "neutral",
        }
        signal = self.strategy.generate_signal(analysis)
        assert signal["signal"] == "sell"
        assert signal["strength"] > 0
        assert "상단 돌파 후 복귀" in signal["reason"]

    def test_neutral_hold(self) -> None:
        """밴드 내부 → 관망"""
        analysis = {
            "middle": [100.0],
            "current_price": 100.0,
            "prev_price": 99.0,
            "current_upper": 110.0,
            "current_lower": 90.0,
            "current_middle": 100.0,
            "prev_upper": 110.0,
            "prev_lower": 90.0,
            "percent_b": 0.5,
            "bandwidth": 20.0,
            "zone": "neutral",
        }
        signal = self.strategy.generate_signal(analysis)
        assert signal["signal"] == "hold"

    def test_insufficient_data_hold(self) -> None:
        """데이터 부족 → HOLD"""
        analysis = {
            "middle": [],
            "current_price": 0.0,
            "prev_price": 0.0,
            "current_upper": 0.0,
            "current_lower": 0.0,
            "current_middle": 0.0,
            "prev_upper": 0.0,
            "prev_lower": 0.0,
            "percent_b": 0.0,
            "bandwidth": 0.0,
            "zone": "neutral",
        }
        signal = self.strategy.generate_signal(analysis)
        assert signal["signal"] == "hold"
        assert "데이터 부족" in signal["reason"]

    def test_signal_threshold_filter(self) -> None:
        """threshold 이하의 약한 신호는 무시"""
        strategy = BollingerBandStrategy(
            BollingerConfig(period=5, signal_threshold=0.9),
        )
        analysis = {
            "middle": [100.0],
            "current_price": 91.0,
            "prev_price": 88.0,
            "current_upper": 110.0,
            "current_lower": 90.0,
            "current_middle": 100.0,
            "prev_upper": 110.0,
            "prev_lower": 90.0,
            "percent_b": 0.05,
            "bandwidth": 20.0,
            "zone": "neutral",
        }
        signal = strategy.generate_signal(analysis)
        assert signal["signal"] == "hold"
        assert "임계값" in signal["reason"]

    def test_signal_has_required_fields(self) -> None:
        """신호 결과에 필수 필드가 모두 포함됨"""
        analysis = {
            "middle": [100.0],
            "current_price": 95.0,
            "prev_price": 88.0,
            "current_upper": 110.0,
            "current_lower": 90.0,
            "current_middle": 100.0,
            "prev_upper": 110.0,
            "prev_lower": 90.0,
            "percent_b": 0.25,
            "bandwidth": 20.0,
            "zone": "neutral",
        }
        signal = self.strategy.generate_signal(analysis)
        required = {"signal", "strength", "reason", "strategy_name", "timestamp", "metrics"}
        assert required.issubset(signal.keys())

    def test_strength_bounded(self) -> None:
        """신호 강도는 0.0 ~ 1.0 범위"""
        analysis = {
            "middle": [100.0],
            "current_price": 95.0,
            "prev_price": 50.0,
            "current_upper": 110.0,
            "current_lower": 90.0,
            "current_middle": 100.0,
            "prev_upper": 110.0,
            "prev_lower": 90.0,
            "percent_b": 0.25,
            "bandwidth": 20.0,
            "zone": "neutral",
        }
        signal = self.strategy.generate_signal(analysis)
        assert 0.0 <= signal["strength"] <= 1.0


# ─────────────────────────────────────────────
# 볼린저 밴드 백테스팅 테스트
# ─────────────────────────────────────────────

class TestBollingerBacktest:
    """BollingerBandStrategy.backtest() 메서드 검증"""

    def setup_method(self) -> None:
        self.strategy = BollingerBandStrategy(BollingerConfig(period=5))

    def test_insufficient_data(self) -> None:
        """데이터 부족 시 빈 결과"""
        data = [{"date": "2026-01-01", "close": 100.0}]
        result = self.strategy.backtest(data, 10_000_000)
        assert result["total_return"] == 0.0
        assert result["total_trades"] == 0
        assert "error" in result

    def test_backtest_result_structure(self) -> None:
        """결과에 필수 필드 포함"""
        prices = [100.0 + 20 * math.sin(i * 0.3) for i in range(50)]
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
        # 큰 변동으로 거래 유도 (하단 이탈 후 복귀 패턴)
        prices = (
            [100.0] * 5
            + [80.0, 60.0]       # 급락 (하단 이탈)
            + [90.0, 100.0]      # 복귀 (매수 신호)
            + [120.0, 140.0]     # 급등 (상단 돌파)
            + [110.0, 100.0]     # 복귀 (매도 신호)
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

class TestBollingerIntegration:
    """분석 → 신호 생성 파이프라인 통합 테스트"""

    def test_full_pipeline_lower_exit(self) -> None:
        """하단 이탈 후 복귀 시나리오 파이프라인"""
        strategy = BollingerBandStrategy(BollingerConfig(period=5))

        # 안정 → 급락 → 반등
        prices = [100.0] * 5 + [80.0, 60.0, 70.0, 85.0, 95.0]
        analysis = strategy.analyze({"prices": prices, "stock_code": "005930"})
        signal = strategy.generate_signal(analysis)

        assert signal["signal"] in ("buy", "hold")
        assert signal["strategy_name"].startswith("Bollinger")

    def test_full_pipeline_upper_exit(self) -> None:
        """상단 돌파 후 복귀 시나리오 파이프라인"""
        strategy = BollingerBandStrategy(BollingerConfig(period=5))

        # 안정 → 급등 → 하락
        prices = [100.0] * 5 + [120.0, 140.0, 130.0, 110.0, 105.0]
        analysis = strategy.analyze({"prices": prices, "stock_code": "005930"})
        signal = strategy.generate_signal(analysis)

        assert signal["signal"] in ("sell", "hold")

    def test_strategy_name_format(self) -> None:
        """전략 이름 형식 확인"""
        strategy = BollingerBandStrategy(BollingerConfig(period=20, num_std=2.0))
        assert strategy.name == "Bollinger(20,2.0)"

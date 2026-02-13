from __future__ import annotations

import math

import pytest

from src.exceptions import StrategyError, ValidationError
from src.strategy.risk import (
    PositionRiskConfig,
    calculate_position_size,
    check_daily_loss_limit,
)


class TestPositionRiskConfig:
    def test_invalid_config_values_raise_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            PositionRiskConfig(max_risk_per_trade_pct=0)

        with pytest.raises(ValidationError):
            PositionRiskConfig(max_position_size_pct=0)


class TestCalculatePositionSize:
    def test_calculates_quantity_with_risk_and_position_limits(self) -> None:
        # 계좌 10,000,000원, 1트레이드당 1% 리스크, 종목당 최대 20% 배분
        # - 트레이드당 최대 손실: 100,000원
        # - 진입 50,000원, 손절 48,000원 → 주당 리스크 2,000원
        #   → 리스크 기준 수량: 50주 (100,000 / 2,000)
        # - 포지션 크기 기준: 2,000,000원 / 50,000원 = 40주
        # 결과적으로 더 작은 값인 40주가 선택되어야 한다.
        config = PositionRiskConfig(
            max_risk_per_trade_pct=1.0,
            max_position_size_pct=20.0,
        )

        quantity = calculate_position_size(
            equity=10_000_000,
            entry_price=50_000,
            stop_loss_price=48_000,
            config=config,
        )

        assert quantity == 40

    def test_raises_when_no_valid_quantity(self) -> None:
        # 계좌가 너무 작거나 리스크 설정이 너무 보수적인 경우
        config = PositionRiskConfig(
            max_risk_per_trade_pct=0.5,
            max_position_size_pct=5.0,
        )

        with pytest.raises(ValidationError):
            calculate_position_size(
                equity=100_000,
                entry_price=50_000,
                stop_loss_price=49_000,
                config=config,
            )

    @pytest.mark.parametrize(
        "equity, entry, stop",
        [
            (0, 10_000, 9_000),
            (1_000_000, 0, 9_000),
            (1_000_000, 10_000, 0),
            (1_000_000, 9_000, 10_000),  # 손절이 진입가보다 높은 경우
        ],
    )
    def test_invalid_inputs_raise_validation_error(
        self, equity: float, entry: float, stop: float
    ) -> None:
        with pytest.raises(ValidationError):
            calculate_position_size(
                equity=equity,
                entry_price=entry,
                stop_loss_price=stop,
            )


class TestCheckDailyLossLimit:
    def test_allows_trading_when_drawdown_within_limit(self) -> None:
        # 고점 10M → 현재 9.7M (3% 손실), 한도 5% → 허용
        assert check_daily_loss_limit(10_000_000, 9_700_000, 5.0) is True

    def test_raises_strategy_error_when_limit_exceeded(self) -> None:
        # 고점 10M → 현재 9.4M (6% 손실), 한도 5% → 초과
        with pytest.raises(StrategyError) as exc:
            check_daily_loss_limit(10_000_000, 9_400_000, 5.0)

        detail = exc.value.detail or {}
        # 부동소수점 오차를 고려해 대략적인 값만 검증
        assert math.isclose(detail["drawdown_pct"], 6.0, rel_tol=1e-3)

    def test_updates_peak_when_new_high(self) -> None:
        # current_equity가 peak를 넘는 경우는 단순 True 반환 (고점 갱신)
        assert check_daily_loss_limit(10_000_000, 10_500_000, 5.0) is True

    @pytest.mark.parametrize(
        "peak, current, limit",
        [
            (0, 1_000_000, 5.0),
            (1_000_000, 0, 5.0),
            (1_000_000, 900_000, 0),
        ],
    )
    def test_invalid_inputs_raise_validation_error(
        self, peak: float, current: float, limit: float
    ) -> None:
        with pytest.raises(ValidationError):
            check_daily_loss_limit(peak, current, limit)

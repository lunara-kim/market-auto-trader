"""
포트폴리오 설정 테스트

config/portfolio.py의 PortfolioSettings 유효성 검증 및 기본값을 테스트합니다.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from config.portfolio import PortfolioSettings


def test_default_values() -> None:
    """기본값 검증"""
    settings = PortfolioSettings()

    assert settings.target_allocations == {}
    assert settings.rebalance_threshold_pct == 5.0
    assert settings.min_trade_amount_krw == 50_000
    assert settings.max_single_order_pct == 10.0
    assert settings.rebalance_mode == "threshold"


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """환경변수로 설정 오버라이드"""
    monkeypatch.setenv(
        "PORTFOLIO_TARGET_ALLOCATIONS", '{"005930": 30.0, "000660": 20.0}'
    )
    monkeypatch.setenv("PORTFOLIO_REBALANCE_THRESHOLD_PCT", "10.0")
    monkeypatch.setenv("PORTFOLIO_MIN_TRADE_AMOUNT_KRW", "100000")
    monkeypatch.setenv("PORTFOLIO_MAX_SINGLE_ORDER_PCT", "15.0")
    monkeypatch.setenv("PORTFOLIO_REBALANCE_MODE", "proportional")

    settings = PortfolioSettings()

    assert settings.target_allocations == {"005930": 30.0, "000660": 20.0}
    assert settings.rebalance_threshold_pct == 10.0
    assert settings.min_trade_amount_krw == 100_000
    assert settings.max_single_order_pct == 15.0
    assert settings.rebalance_mode == "proportional"


def test_target_allocations_sum_exceeds_100() -> None:
    """목표 비중 합계가 100% 초과 시 ValidationError"""
    with pytest.raises(
        ValidationError, match="목표 비중 합계.*100% 이하여야 합니다"
    ):
        PortfolioSettings(target_allocations={"005930": 60.0, "000660": 50.0})


def test_target_allocations_negative_value() -> None:
    """목표 비중이 음수인 경우 ValidationError"""
    with pytest.raises(
        ValidationError, match="목표 비중.*0 이상이어야 합니다"
    ):
        PortfolioSettings(target_allocations={"005930": -10.0})


def test_rebalance_threshold_zero() -> None:
    """리밸런싱 임계값이 0 이하인 경우 ValidationError"""
    with pytest.raises(
        ValidationError, match="rebalance_threshold_pct.*0보다 커야 합니다"
    ):
        PortfolioSettings(rebalance_threshold_pct=0.0)


def test_min_trade_amount_zero() -> None:
    """최소 거래 금액이 0 이하인 경우 ValidationError"""
    with pytest.raises(
        ValidationError, match="min_trade_amount_krw.*0보다 커야 합니다"
    ):
        PortfolioSettings(min_trade_amount_krw=0)


def test_max_single_order_pct_invalid() -> None:
    """최대 주문 비율이 범위를 벗어난 경우 ValidationError"""
    # 0 이하
    with pytest.raises(
        ValidationError, match="max_single_order_pct.*0보다 크고 100 이하여야 합니다"
    ):
        PortfolioSettings(max_single_order_pct=0.0)

    # 100 초과
    with pytest.raises(
        ValidationError, match="max_single_order_pct.*0보다 크고 100 이하여야 합니다"
    ):
        PortfolioSettings(max_single_order_pct=101.0)


def test_invalid_rebalance_mode() -> None:
    """유효하지 않은 리밸런싱 모드인 경우 ValidationError"""
    with pytest.raises(ValidationError, match="rebalance_mode는.*중 하나여야 합니다"):
        PortfolioSettings(rebalance_mode="invalid_mode")


def test_valid_rebalance_modes() -> None:
    """유효한 리밸런싱 모드 (threshold, proportional)"""
    # threshold
    settings1 = PortfolioSettings(rebalance_mode="threshold")
    assert settings1.rebalance_mode == "threshold"

    # proportional
    settings2 = PortfolioSettings(rebalance_mode="proportional")
    assert settings2.rebalance_mode == "proportional"

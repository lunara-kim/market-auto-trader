"""
리밸런싱 엔진 테스트

src/strategy/rebalancer.py의 핵심 로직을 검증합니다.
"""

from __future__ import annotations

import pytest

from config.portfolio import PortfolioSettings
from src.exceptions import ValidationError
from src.strategy.rebalancer import (
    RebalanceOrder,
    RebalancePlan,
    calculate_current_allocations,
    generate_rebalance_plan,
)


# ───────────────── calculate_current_allocations 테스트 ─────────────────


def test_calculate_current_allocations_basic() -> None:
    """기본 현재 비중 계산"""
    holdings = [
        {"stock_code": "005930", "quantity": 10, "current_price": 70_000.0},
        {"stock_code": "000660", "quantity": 20, "current_price": 50_000.0},
    ]
    total_equity = 2_000_000.0  # 700k + 1000k + 300k cash

    allocations = calculate_current_allocations(holdings, total_equity)

    assert allocations["005930"] == pytest.approx(35.0, abs=0.01)  # 700k / 2000k
    assert allocations["000660"] == pytest.approx(50.0, abs=0.01)  # 1000k / 2000k


def test_calculate_current_allocations_zero_equity() -> None:
    """총 평가액이 0인 경우 ValidationError"""
    holdings = [{"stock_code": "005930", "quantity": 10, "current_price": 70_000.0}]

    with pytest.raises(ValidationError, match="총 평가액.*0보다 커야 합니다"):
        calculate_current_allocations(holdings, 0.0)


def test_calculate_current_allocations_missing_stock_code() -> None:
    """stock_code가 없는 경우 ValidationError"""
    holdings = [{"quantity": 10, "current_price": 70_000.0}]

    with pytest.raises(ValidationError, match="stock_code가 없습니다"):
        calculate_current_allocations(holdings, 1_000_000.0)


def test_calculate_current_allocations_invalid_quantity() -> None:
    """수량 또는 가격이 유효하지 않은 경우 경고 로그 + 스킵"""
    holdings = [
        {"stock_code": "005930", "quantity": 0, "current_price": 70_000.0},
        {"stock_code": "000660", "quantity": 20, "current_price": 0.0},
        {"stock_code": "035720", "quantity": 5, "current_price": 100_000.0},
    ]
    total_equity = 1_000_000.0

    allocations = calculate_current_allocations(holdings, total_equity)

    # 유효하지 않은 종목은 스킵되고 035720만 포함
    assert "005930" not in allocations
    assert "000660" not in allocations
    assert allocations["035720"] == pytest.approx(50.0, abs=0.01)


# ───────────────── generate_rebalance_plan 테스트 ─────────────────


def test_generate_rebalance_plan_basic_sell_and_buy() -> None:
    """기본 리밸런싱: 비중 이탈 종목 조정"""
    holdings = [
        {"stock_code": "005930", "quantity": 15, "current_price": 70_000.0},  # 1.05M (52.5%)
        {"stock_code": "000660", "quantity": 10, "current_price": 50_000.0},  # 500k (25%)
    ]
    cash = 450_000.0  # 22.5%
    total_equity = 2_000_000.0

    config = PortfolioSettings(
        target_allocations={"005930": 30.0, "000660": 40.0},  # 나머지 30% 현금
        rebalance_threshold_pct=5.0,
        min_trade_amount_krw=50_000,
        max_single_order_pct=50.0,
        rebalance_mode="threshold",
    )

    plan = generate_rebalance_plan(holdings, cash, total_equity, config)

    # 005930: 52.5% → 30% (매도)
    # 000660: 25% → 40% (매수)
    assert len(plan.sell_orders) == 1
    assert plan.sell_orders[0].stock_code == "005930"
    assert plan.sell_orders[0].quantity > 0

    assert len(plan.buy_orders) == 1
    assert plan.buy_orders[0].stock_code == "000660"
    assert plan.buy_orders[0].quantity > 0

    # 매도 → 매수 순서
    assert plan.orders[0].side == "sell"
    assert plan.orders[1].side == "buy"


def test_generate_rebalance_plan_threshold_not_exceeded() -> None:
    """threshold 미초과 시 리밸런싱 스킵"""
    holdings = [
        {"stock_code": "005930", "quantity": 10, "current_price": 70_000.0},  # 700k (35%)
    ]
    cash = 1_300_000.0  # 65%
    total_equity = 2_000_000.0

    config = PortfolioSettings(
        target_allocations={"005930": 30.0},  # 현재 35%, 차이 5%
        rebalance_threshold_pct=10.0,  # 10% 이상 이탈 시에만 리밸런싱
        min_trade_amount_krw=50_000,
        max_single_order_pct=50.0,
        rebalance_mode="threshold",
    )

    plan = generate_rebalance_plan(holdings, cash, total_equity, config)

    # 비중 차이 5% < 임계값 10% → 스킵
    assert plan.total_orders == 0
    assert "005930" in plan.skipped_stocks


def test_generate_rebalance_plan_cash_shortage() -> None:
    """현금 부족 시 매도 우선 처리"""
    holdings = [
        {"stock_code": "005930", "quantity": 20, "current_price": 70_000.0},  # 1.4M (70%)
    ]
    cash = 100_000.0  # 5%
    total_equity = 2_000_000.0

    config = PortfolioSettings(
        target_allocations={"005930": 30.0, "000660": 40.0},  # 000660 신규 매수 필요
        rebalance_threshold_pct=5.0,
        min_trade_amount_krw=50_000,
        max_single_order_pct=50.0,
        rebalance_mode="threshold",
    )

    plan = generate_rebalance_plan(holdings, cash, total_equity, config)

    # 005930 매도 → 현금 확보
    assert len(plan.sell_orders) >= 1
    assert plan.cash_after_sells > cash

    # 000660은 holdings에 없어서 현재가 정보 없음 → 스킵 (실제로는 외부 조회 필요)


def test_generate_rebalance_plan_empty_portfolio() -> None:
    """빈 포트폴리오 (현금만 있음)"""
    holdings: list[dict] = []
    cash = 2_000_000.0
    total_equity = 2_000_000.0

    config = PortfolioSettings(
        target_allocations={"005930": 50.0},
        rebalance_threshold_pct=5.0,
        min_trade_amount_krw=50_000,
        max_single_order_pct=50.0,
        rebalance_mode="threshold",
    )

    plan = generate_rebalance_plan(holdings, cash, total_equity, config)

    # 신규 종목이라 현재가 정보가 없어 매수 불가 (실제로는 외부 조회 필요)
    # 현재 구현: holdings에 없는 종목은 스킵
    assert plan.total_orders == 0


def test_generate_rebalance_plan_single_stock() -> None:
    """단일 종목 포트폴리오"""
    holdings = [
        {"stock_code": "005930", "quantity": 20, "current_price": 70_000.0},  # 1.4M (70%)
    ]
    cash = 600_000.0  # 30%
    total_equity = 2_000_000.0

    config = PortfolioSettings(
        target_allocations={"005930": 50.0},  # 목표 50% (현재 70%)
        rebalance_threshold_pct=5.0,
        min_trade_amount_krw=50_000,
        max_single_order_pct=50.0,
        rebalance_mode="threshold",
    )

    plan = generate_rebalance_plan(holdings, cash, total_equity, config)

    # 70% → 50% 매도
    assert len(plan.sell_orders) == 1
    assert plan.sell_orders[0].stock_code == "005930"


def test_generate_rebalance_plan_min_trade_amount_filter() -> None:
    """최소 거래금액 필터링"""
    holdings = [
        {"stock_code": "005930", "quantity": 10, "current_price": 70_000.0},  # 700k (70%)
    ]
    cash = 300_000.0  # 30%
    total_equity = 1_000_000.0

    config = PortfolioSettings(
        target_allocations={"005930": 69.0},  # 현재 70%, 차이 1% (10k원) → 최소 거래금액 미달
        rebalance_threshold_pct=0.5,
        min_trade_amount_krw=50_000,  # 5만 원 미만 주문 제외
        max_single_order_pct=50.0,
        rebalance_mode="threshold",
    )

    plan = generate_rebalance_plan(holdings, cash, total_equity, config)

    # 매도 금액이 10k원 < 50k원 → 스킵
    assert plan.total_orders == 0


def test_generate_rebalance_plan_max_single_order_pct_limit() -> None:
    """최대 단일 주문 비율 제한"""
    holdings = [
        {"stock_code": "005930", "quantity": 30, "current_price": 70_000.0},  # 2.1M (70%)
    ]
    cash = 900_000.0  # 30%
    total_equity = 3_000_000.0

    config = PortfolioSettings(
        target_allocations={"005930": 20.0},  # 현재 70% → 목표 20% (50% 매도 필요)
        rebalance_threshold_pct=5.0,
        min_trade_amount_krw=50_000,
        max_single_order_pct=30.0,  # 한 번에 30% 이상 주문 불가
        rebalance_mode="threshold",
    )

    plan = generate_rebalance_plan(holdings, cash, total_equity, config)

    # 매도 필요 금액: 2.1M - 600k = 1.5M (50%)
    # 최대 주문: 30% (900k)
    assert len(plan.sell_orders) == 1
    sell_value = plan.sell_orders[0].quantity * plan.sell_orders[0].current_price
    assert sell_value <= 900_000.0 + 100_000.0  # 최대 30% + 약간의 여유


def test_generate_rebalance_plan_proportional_mode() -> None:
    """proportional 모드: 전체 비례 리밸런싱"""
    holdings = [
        {"stock_code": "005930", "quantity": 10, "current_price": 70_000.0},  # 700k (35%)
        {"stock_code": "000660", "quantity": 5, "current_price": 50_000.0},   # 250k (12.5%)
    ]
    cash = 1_050_000.0  # 52.5%
    total_equity = 2_000_000.0

    config = PortfolioSettings(
        target_allocations={"005930": 30.0, "000660": 20.0},  # 나머지 50% 현금
        rebalance_threshold_pct=100.0,  # proportional 모드에서는 임계값 무관
        min_trade_amount_krw=50_000,
        max_single_order_pct=50.0,
        rebalance_mode="proportional",
    )

    plan = generate_rebalance_plan(holdings, cash, total_equity, config)

    # proportional 모드: 임계값 무관하게 모든 종목 조정
    # 005930: 35% → 30% (매도)
    # 000660: 12.5% → 20% (매수)
    assert len(plan.sell_orders) >= 1
    assert len(plan.buy_orders) >= 1


def test_generate_rebalance_plan_new_stock_addition() -> None:
    """신규 종목 추가 (현재 미보유)"""
    holdings = [
        {"stock_code": "005930", "quantity": 10, "current_price": 70_000.0},  # 700k (70%)
    ]
    cash = 300_000.0  # 30%
    total_equity = 1_000_000.0

    config = PortfolioSettings(
        target_allocations={"005930": 50.0, "000660": 30.0},  # 000660 신규
        rebalance_threshold_pct=5.0,
        min_trade_amount_krw=50_000,
        max_single_order_pct=50.0,
        rebalance_mode="threshold",
    )

    plan = generate_rebalance_plan(holdings, cash, total_equity, config)

    # 신규 종목 000660은 holdings에 없어서 현재가 정보 없음 → 스킵
    # (실제로는 외부에서 가격 조회 후 holdings에 추가 필요)
    # 005930은 70% → 50% 매도
    assert len(plan.sell_orders) == 1
    assert plan.sell_orders[0].stock_code == "005930"


def test_generate_rebalance_plan_sell_before_buy_order() -> None:
    """매도 후 매수 순서 검증"""
    holdings = [
        {"stock_code": "005930", "quantity": 15, "current_price": 70_000.0},  # 1.05M (52.5%)
        {"stock_code": "000660", "quantity": 10, "current_price": 50_000.0},  # 500k (25%)
    ]
    cash = 450_000.0  # 22.5%
    total_equity = 2_000_000.0

    config = PortfolioSettings(
        target_allocations={"005930": 30.0, "000660": 40.0},
        rebalance_threshold_pct=5.0,
        min_trade_amount_krw=50_000,
        max_single_order_pct=50.0,
        rebalance_mode="threshold",
    )

    plan = generate_rebalance_plan(holdings, cash, total_equity, config)

    # 매도 주문이 먼저, 매수 주문이 나중
    sell_indices = [i for i, o in enumerate(plan.orders) if o.side == "sell"]
    buy_indices = [i for i, o in enumerate(plan.orders) if o.side == "buy"]

    if sell_indices and buy_indices:
        assert max(sell_indices) < min(buy_indices), "매도 주문이 매수 주문보다 먼저 와야 합니다"


def test_generate_rebalance_plan_negative_cash() -> None:
    """현금이 음수인 경우 ValidationError"""
    holdings = [
        {"stock_code": "005930", "quantity": 10, "current_price": 70_000.0},
    ]

    config = PortfolioSettings()

    with pytest.raises(ValidationError, match="현금.*0 이상이어야 합니다"):
        generate_rebalance_plan(holdings, -100_000.0, 1_000_000.0, config)


def test_generate_rebalance_plan_zero_total_equity() -> None:
    """총 평가액이 0인 경우 ValidationError"""
    holdings: list[dict] = []

    config = PortfolioSettings()

    with pytest.raises(ValidationError, match="총 평가액.*0보다 커야 합니다"):
        generate_rebalance_plan(holdings, 0.0, 0.0, config)


def test_rebalance_plan_summary() -> None:
    """RebalancePlan summary 속성 검증"""
    plan = RebalancePlan(
        orders=[
            RebalanceOrder(
                stock_code="005930",
                side="sell",
                quantity=5,
                current_price=70_000.0,
                target_value_krw=600_000.0,
                reason="test",
            ),
            RebalanceOrder(
                stock_code="000660",
                side="buy",
                quantity=10,
                current_price=50_000.0,
                target_value_krw=800_000.0,
                reason="test",
            ),
        ],
        total_equity=2_000_000.0,
        cash_before=500_000.0,
        estimated_cash_after=650_000.0,
        skipped_stocks=["035720"],
    )

    summary = plan.summary

    assert summary["total_orders"] == 2
    assert summary["buy_orders"] == 1
    assert summary["sell_orders"] == 1
    assert summary["total_equity_krw"] == 2_000_000.0
    assert summary["cash_before_krw"] == 500_000.0
    assert summary["estimated_cash_after_krw"] == 650_000.0
    assert summary["skipped_stocks"] == ["035720"]

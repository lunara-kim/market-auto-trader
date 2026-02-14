"""
src/utils/trade_report.py 유닛 테스트
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import MagicMock

import pytest

from src.utils.trade_report import (
    calculate_pnl,
    format_report_text,
    generate_daily_summary,
    generate_portfolio_snapshot,
)


# ───────────────────── Fixtures ─────────────────────


@pytest.fixture
def sample_orders() -> list[MagicMock]:
    """샘플 주문 데이터"""
    orders = []

    # 매수 체결 3건 (2026-02-15)
    for i in range(3):
        order = MagicMock()
        order.created_at = datetime(2026, 2, 15, 9, 30, tzinfo=timezone.utc)
        order.status = "executed"
        order.order_type = "buy"
        order.stock_code = f"00593{i}"
        order.quantity = 10
        order.executed_price = 70000 + i * 1000
        orders.append(order)

    # 매도 체결 2건
    for i in range(2):
        order = MagicMock()
        order.created_at = datetime(2026, 2, 15, 14, 30, tzinfo=timezone.utc)
        order.status = "executed"
        order.order_type = "sell"
        order.stock_code = f"00593{i}"
        order.quantity = 5
        order.executed_price = 72000 + i * 1000
        orders.append(order)

    # pending 주문 1건
    order = MagicMock()
    order.created_at = datetime(2026, 2, 15, 15, 0, tzinfo=timezone.utc)
    order.status = "pending"
    order.order_type = "buy"
    order.stock_code = "005935"
    order.quantity = 20
    order.executed_price = None
    orders.append(order)

    # 다른 날짜 주문 1건
    order = MagicMock()
    order.created_at = datetime(2026, 2, 14, 10, 0, tzinfo=timezone.utc)
    order.status = "executed"
    order.order_type = "buy"
    order.stock_code = "000660"
    order.quantity = 15
    order.executed_price = 100000
    orders.append(order)

    return orders


@pytest.fixture
def sample_holdings() -> list[dict]:
    """샘플 보유 종목 데이터"""
    return [
        {
            "stock_code": "005930",
            "stock_name": "삼성전자",
            "quantity": 10,
            "avg_price": 70000,
            "current_price": 72000,
        },
        {
            "stock_code": "000660",
            "stock_name": "SK하이닉스",
            "quantity": 5,
            "avg_price": 120000,
            "current_price": 115000,
        },
        {
            "stock_code": "035720",
            "stock_name": "카카오",
            "quantity": 20,
            "avg_price": 50000,
            "current_price": 52000,
        },
    ]


# ───────────────────── generate_daily_summary 테스트 ─────────────────────


def test_generate_daily_summary_basic(sample_orders: list[MagicMock]) -> None:
    """기본 일일 요약 생성"""
    target_date = date(2026, 2, 15)
    summary = generate_daily_summary(sample_orders, target_date)

    assert summary["date"] == "2026-02-15"
    assert summary["total_orders"] == 6  # pending 1건 포함
    assert summary["executed_orders"] == 5
    assert summary["buy_count"] == 3
    assert summary["sell_count"] == 2


def test_generate_daily_summary_amounts(sample_orders: list[MagicMock]) -> None:
    """거래 금액 계산"""
    target_date = date(2026, 2, 15)
    summary = generate_daily_summary(sample_orders, target_date)

    # 매수: 70000*10 + 71000*10 + 72000*10 = 2,130,000
    assert summary["total_buy_amount"] == 2_130_000

    # 매도: 72000*5 + 73000*5 = 725,000
    assert summary["total_sell_amount"] == 725_000


def test_generate_daily_summary_no_orders() -> None:
    """주문이 없는 날"""
    summary = generate_daily_summary([], date(2026, 2, 16))

    assert summary["total_orders"] == 0
    assert summary["executed_orders"] == 0
    assert summary["buy_count"] == 0
    assert summary["sell_count"] == 0
    assert summary["total_buy_amount"] == 0
    assert summary["total_sell_amount"] == 0


def test_generate_daily_summary_different_date(sample_orders: list[MagicMock]) -> None:
    """다른 날짜 조회"""
    target_date = date(2026, 2, 14)
    summary = generate_daily_summary(sample_orders, target_date)

    assert summary["date"] == "2026-02-14"
    assert summary["total_orders"] == 1
    assert summary["executed_orders"] == 1
    assert summary["buy_count"] == 1
    assert summary["sell_count"] == 0
    assert summary["total_buy_amount"] == 1_500_000  # 100000 * 15


# ───────────────────── generate_portfolio_snapshot 테스트 ─────────────────────


def test_generate_portfolio_snapshot_basic(sample_holdings: list[dict]) -> None:
    """기본 포트폴리오 스냅샷 생성"""
    snapshot = generate_portfolio_snapshot(sample_holdings)

    assert len(snapshot) == 3
    assert snapshot[0]["stock_code"] == "005930"
    assert snapshot[0]["stock_name"] == "삼성전자"


def test_generate_portfolio_snapshot_calculations(sample_holdings: list[dict]) -> None:
    """평가금액 및 손익 계산"""
    snapshot = generate_portfolio_snapshot(sample_holdings)

    # 삼성전자: 72000 * 10 = 720000, 손익 = 720000 - 700000 = 20000
    assert snapshot[0]["evaluation"] == 720_000
    assert snapshot[0]["profit_loss"] == 20_000
    assert snapshot[0]["profit_loss_rate"] == 2.86

    # SK하이닉스: 115000 * 5 = 575000, 손익 = 575000 - 600000 = -25000
    assert snapshot[1]["evaluation"] == 575_000
    assert snapshot[1]["profit_loss"] == -25_000
    assert snapshot[1]["profit_loss_rate"] == -4.17

    # 카카오: 52000 * 20 = 1040000, 손익 = 1040000 - 1000000 = 40000
    assert snapshot[2]["evaluation"] == 1_040_000
    assert snapshot[2]["profit_loss"] == 40_000
    assert snapshot[2]["profit_loss_rate"] == 4.0


def test_generate_portfolio_snapshot_empty() -> None:
    """빈 포트폴리오"""
    snapshot = generate_portfolio_snapshot([])
    assert snapshot == []


def test_generate_portfolio_snapshot_zero_cost() -> None:
    """평단가 0인 경우 (수익률 0으로 처리)"""
    holdings = [
        {
            "stock_code": "TEST",
            "stock_name": "테스트",
            "quantity": 10,
            "avg_price": 0,
            "current_price": 1000,
        },
    ]
    snapshot = generate_portfolio_snapshot(holdings)

    assert snapshot[0]["profit_loss_rate"] == 0.0


# ───────────────────── calculate_pnl 테스트 ─────────────────────


def test_calculate_pnl_basic(sample_orders: list[MagicMock]) -> None:
    """기본 실현 손익 계산"""
    pnl = calculate_pnl(sample_orders)

    assert "total_realized_pnl" in pnl
    assert "by_stock" in pnl
    assert isinstance(pnl["by_stock"], dict)


def test_calculate_pnl_amounts(sample_orders: list[MagicMock]) -> None:
    """실현 손익 금액 계산"""
    pnl = calculate_pnl(sample_orders)

    # 005930: 매수 70000*10=700000, 매도 72000*5=360000 → -340000
    assert pnl["by_stock"]["005930"]["buy_amount"] == 700_000
    assert pnl["by_stock"]["005930"]["sell_amount"] == 360_000
    assert pnl["by_stock"]["005930"]["realized_pnl"] == -340_000

    # 005931: 매수 71000*10=710000, 매도 73000*5=365000 → -345000
    assert pnl["by_stock"]["005931"]["buy_amount"] == 710_000
    assert pnl["by_stock"]["005931"]["sell_amount"] == 365_000
    assert pnl["by_stock"]["005931"]["realized_pnl"] == -345_000

    # 총 실현 손익
    total = pnl["total_realized_pnl"]
    assert total == -340_000 + -345_000 + (-720_000) + (-1_500_000)


def test_calculate_pnl_only_executed() -> None:
    """체결된 주문만 계산"""
    orders = []

    # 체결된 주문
    order1 = MagicMock()
    order1.status = "executed"
    order1.order_type = "buy"
    order1.stock_code = "005930"
    order1.quantity = 10
    order1.executed_price = 70000
    orders.append(order1)

    # pending 주문 (제외되어야 함)
    order2 = MagicMock()
    order2.status = "pending"
    order2.order_type = "sell"
    order2.stock_code = "005930"
    order2.quantity = 5
    order2.executed_price = None
    orders.append(order2)

    pnl = calculate_pnl(orders)

    assert pnl["by_stock"]["005930"]["buy_amount"] == 700_000
    assert pnl["by_stock"]["005930"]["sell_amount"] == 0


def test_calculate_pnl_empty() -> None:
    """주문이 없는 경우"""
    pnl = calculate_pnl([])

    assert pnl["total_realized_pnl"] == 0
    assert pnl["by_stock"] == {}


# ───────────────────── format_report_text 테스트 ─────────────────────


def test_format_report_text_basic() -> None:
    """기본 텍스트 리포트 포매팅"""
    summary = {
        "date": "2026-02-15",
        "total_orders": 10,
        "executed_orders": 8,
        "buy_count": 5,
        "sell_count": 3,
        "total_buy_amount": 1_500_000,
        "total_sell_amount": 800_000,
    }
    snapshot = []
    pnl = {"total_realized_pnl": 150_000, "by_stock": {}}

    text = format_report_text(summary, snapshot, pnl)

    assert "2026-02-15" in text
    assert "총 주문: 10건" in text
    assert "체결: 8건" in text
    assert "매수: 5건" in text
    assert "매도: 3건" in text
    assert "150,000원" in text


def test_format_report_text_with_holdings() -> None:
    """보유 종목 포함 리포트"""
    summary = {
        "date": "2026-02-15",
        "total_orders": 5,
        "executed_orders": 5,
        "buy_count": 3,
        "sell_count": 2,
        "total_buy_amount": 2_000_000,
        "total_sell_amount": 1_000_000,
    }
    snapshot = [
        {
            "stock_code": "005930",
            "stock_name": "삼성전자",
            "quantity": 10,
            "avg_price": 70000,
            "current_price": 72000,
            "evaluation": 720_000,
            "profit_loss": 20_000,
            "profit_loss_rate": 2.86,
        },
    ]
    pnl = {"total_realized_pnl": 50_000, "by_stock": {}}

    text = format_report_text(summary, snapshot, pnl)

    assert "삼성전자" in text
    assert "005930" in text
    assert "10주" in text
    assert "+20,000원" in text
    assert "+2.86%" in text


def test_format_report_text_with_pnl_by_stock() -> None:
    """종목별 실현 손익 포함 리포트"""
    summary = {
        "date": "2026-02-15",
        "total_orders": 5,
        "executed_orders": 5,
        "buy_count": 3,
        "sell_count": 2,
        "total_buy_amount": 2_000_000,
        "total_sell_amount": 2_100_000,
    }
    snapshot = []
    pnl = {
        "total_realized_pnl": 100_000,
        "by_stock": {
            "005930": {
                "buy_amount": 700_000,
                "sell_amount": 750_000,
                "realized_pnl": 50_000,
            },
            "000660": {
                "buy_amount": 1_300_000,
                "sell_amount": 1_350_000,
                "realized_pnl": 50_000,
            },
        },
    }

    text = format_report_text(summary, snapshot, pnl)

    assert "005930" in text
    assert "000660" in text
    assert "+50,000원" in text

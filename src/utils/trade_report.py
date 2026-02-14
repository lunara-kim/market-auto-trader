"""
거래 리포트 유틸리티

순수 함수 기반으로 일일 거래 요약, 포트폴리오 스냅샷, 손익 계산 등을 제공합니다.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any


def generate_daily_summary(orders: list[Any], target_date: date) -> dict[str, Any]:
    """
    일일 거래 요약을 생성합니다.

    Args:
        orders: Order 객체 리스트
        target_date: 조회 대상 날짜

    Returns:
        {
            "date": "2026-02-15",
            "total_orders": 10,
            "executed_orders": 8,
            "buy_count": 5,
            "sell_count": 3,
            "total_buy_amount": 1500000.0,
            "total_sell_amount": 800000.0,
        }
    """
    # 해당 날짜의 주문만 필터링
    target_orders = [
        o
        for o in orders
        if o.created_at.date() == target_date
    ]

    executed_orders = [o for o in target_orders if o.status == "executed"]
    buy_orders = [o for o in executed_orders if o.order_type == "buy"]
    sell_orders = [o for o in executed_orders if o.order_type == "sell"]

    total_buy_amount = sum(
        (o.executed_price or 0) * o.quantity for o in buy_orders
    )
    total_sell_amount = sum(
        (o.executed_price or 0) * o.quantity for o in sell_orders
    )

    return {
        "date": target_date.isoformat(),
        "total_orders": len(target_orders),
        "executed_orders": len(executed_orders),
        "buy_count": len(buy_orders),
        "sell_count": len(sell_orders),
        "total_buy_amount": total_buy_amount,
        "total_sell_amount": total_sell_amount,
    }


def generate_portfolio_snapshot(holdings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    포트폴리오 스냅샷을 생성합니다.

    Args:
        holdings: 보유 종목 정보 리스트
            [{"stock_code": "005930", "stock_name": "삼성전자", "quantity": 10,
              "avg_price": 70000, "current_price": 72000}, ...]

    Returns:
        [
            {
                "stock_code": "005930",
                "stock_name": "삼성전자",
                "quantity": 10,
                "avg_price": 70000.0,
                "current_price": 72000.0,
                "evaluation": 720000.0,
                "profit_loss": 20000.0,
                "profit_loss_rate": 2.86,
            },
            ...
        ]
    """
    snapshot = []
    for h in holdings:
        quantity = h["quantity"]
        avg_price = h["avg_price"]
        current_price = h["current_price"]

        evaluation = current_price * quantity
        cost = avg_price * quantity
        pnl = evaluation - cost
        pnl_rate = (pnl / cost * 100) if cost > 0 else 0.0

        snapshot.append(
            {
                "stock_code": h["stock_code"],
                "stock_name": h.get("stock_name", ""),
                "quantity": quantity,
                "avg_price": avg_price,
                "current_price": current_price,
                "evaluation": evaluation,
                "profit_loss": pnl,
                "profit_loss_rate": round(pnl_rate, 2),
            },
        )

    return snapshot


def calculate_pnl(orders: list[Any]) -> dict[str, Any]:
    """
    실현 손익을 계산합니다 (매수/매도 쌍 매칭).

    Args:
        orders: Order 객체 리스트 (status="executed"만 계산 대상)

    Returns:
        {
            "total_realized_pnl": 150000.0,
            "by_stock": {
                "005930": {
                    "buy_amount": 700000.0,
                    "sell_amount": 720000.0,
                    "realized_pnl": 20000.0,
                },
                ...
            }
        }
    """
    executed_orders = [o for o in orders if o.status == "executed"]

    # 종목별 매수/매도 금액 집계
    by_stock: dict[str, dict[str, float]] = defaultdict(
        lambda: {"buy_amount": 0.0, "sell_amount": 0.0, "realized_pnl": 0.0},
    )

    for o in executed_orders:
        stock_code = o.stock_code
        amount = (o.executed_price or 0) * o.quantity

        if o.order_type == "buy":
            by_stock[stock_code]["buy_amount"] += amount
        elif o.order_type == "sell":
            by_stock[stock_code]["sell_amount"] += amount

    # 실현 손익 = 매도 금액 - 매수 금액 (단순화된 계산)
    total_realized_pnl = 0.0
    for stock_code, data in by_stock.items():
        pnl = data["sell_amount"] - data["buy_amount"]
        data["realized_pnl"] = pnl
        total_realized_pnl += pnl

    return {
        "total_realized_pnl": total_realized_pnl,
        "by_stock": dict(by_stock),
    }


def format_report_text(
    summary: dict[str, Any],
    snapshot: list[dict[str, Any]],
    pnl: dict[str, Any],
) -> str:
    """
    텍스트 기반 리포트를 포매팅합니다 (Discord/터미널 출력용).

    Args:
        summary: generate_daily_summary 결과
        snapshot: generate_portfolio_snapshot 결과
        pnl: calculate_pnl 결과

    Returns:
        포매팅된 텍스트 리포트
    """
    lines = []
    lines.append("=" * 50)
    lines.append(f"📊 일일 거래 리포트 ({summary['date']})")
    lines.append("=" * 50)
    lines.append("")

    # 일일 거래 요약
    lines.append("## 거래 요약")
    lines.append(f"  • 총 주문: {summary['total_orders']}건")
    lines.append(f"  • 체결: {summary['executed_orders']}건")
    lines.append(f"  • 매수: {summary['buy_count']}건 ({summary['total_buy_amount']:,.0f}원)")
    lines.append(f"  • 매도: {summary['sell_count']}건 ({summary['total_sell_amount']:,.0f}원)")
    lines.append("")

    # 실현 손익
    lines.append("## 실현 손익")
    lines.append(f"  • 총 실현 손익: {pnl['total_realized_pnl']:,.0f}원")
    if pnl["by_stock"]:
        lines.append("  • 종목별:")
        for stock_code, data in pnl["by_stock"].items():
            lines.append(
                f"    - {stock_code}: {data['realized_pnl']:+,.0f}원 "
                f"(매수 {data['buy_amount']:,.0f} / 매도 {data['sell_amount']:,.0f})",
            )
    lines.append("")

    # 포트폴리오 스냅샷
    lines.append("## 포트폴리오 현황")
    if not snapshot:
        lines.append("  (보유 종목 없음)")
    else:
        for item in snapshot:
            lines.append(
                f"  • {item['stock_name']}({item['stock_code']}): "
                f"{item['quantity']}주 | "
                f"평단 {item['avg_price']:,.0f}원 | "
                f"현재 {item['current_price']:,.0f}원 | "
                f"평가 {item['evaluation']:,.0f}원 | "
                f"손익 {item['profit_loss']:+,.0f}원 ({item['profit_loss_rate']:+.2f}%)",
            )
    lines.append("")
    lines.append("=" * 50)

    return "\n".join(lines)

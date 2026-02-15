"""
실시간 포트폴리오 PnL 대시보드 API

보유 종목별 손익, 수익률 추이, 종합 요약 등을 제공합니다.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query

from src.api.dependencies import get_kis_client
from src.api.schemas import (
    DashboardPerformanceItem,
    DashboardPerformanceResponse,
    DashboardPnLResponse,
    DashboardSummaryResponse,
    PnLHoldingItem,
)
from src.broker.kis_client import KISClient
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/dashboard", tags=["Dashboard"])


# ───────────────────── Helper ─────────────────────


def _calculate_holdings_pnl(
    stocks: list[dict],
    total_eval: float,
) -> list[PnLHoldingItem]:
    """보유종목별 PnL 계산

    Args:
        stocks: KIS balance의 stocks 데이터
        total_eval: 전체 평가금액

    Returns:
        보유종목별 PnL 리스트
    """
    holdings: list[PnLHoldingItem] = []

    for stock in stocks:
        current_price = stock.get("current_price", 0)
        avg_price = stock.get("avg_price", 0)
        quantity = stock.get("quantity", 0)
        eval_amount = current_price * quantity
        purchase_amount = avg_price * quantity
        profit_loss = eval_amount - purchase_amount
        profit_loss_rate = (
            ((current_price - avg_price) / avg_price * 100) if avg_price > 0 else 0.0
        )
        weight = (eval_amount / total_eval * 100) if total_eval > 0 else 0.0

        holdings.append(PnLHoldingItem(
            stock_code=stock.get("stock_code", ""),
            stock_name=stock.get("stock_name", ""),
            current_price=current_price,
            avg_price=avg_price,
            quantity=quantity,
            eval_amount=eval_amount,
            purchase_amount=purchase_amount,
            profit_loss=profit_loss,
            profit_loss_rate=round(profit_loss_rate, 2),
            weight=round(weight, 2),
        ))

    return holdings


# ───────────────────── Endpoints ─────────────────────


@router.get(
    "/pnl",
    response_model=DashboardPnLResponse,
    summary="실시간 포트폴리오 손익 현황",
    description=(
        "보유종목별 현재가, 매입가, 평가손익, 수익률과 "
        "전체 평가금액, 총 손익, 포지션별 비중을 조회합니다."
    ),
)
def get_pnl(
    client: KISClient = Depends(get_kis_client),
) -> DashboardPnLResponse:
    """실시간 포트폴리오 손익 현황"""
    balance = client.get_balance()

    stocks = balance.get("stocks", [])
    summary = balance.get("summary", {})

    total_eval = summary.get("total_eval", 0)
    total_purchase = summary.get("total_purchase", 0)
    total_profit_loss = total_eval - total_purchase
    total_profit_loss_rate = (
        ((total_eval - total_purchase) / total_purchase * 100)
        if total_purchase > 0
        else 0.0
    )

    holdings = _calculate_holdings_pnl(stocks, total_eval)

    now = datetime.now(UTC)

    logger.info(
        "PnL 조회: %d종목, 총평가 %.0f원, 손익 %.0f원",
        len(holdings),
        total_eval,
        total_profit_loss,
    )

    return DashboardPnLResponse(
        holdings=holdings,
        total_eval_amount=total_eval,
        total_purchase_amount=total_purchase,
        total_profit_loss=total_profit_loss,
        total_profit_loss_rate=round(total_profit_loss_rate, 2),
        daily_change=0.0,  # 전일 대비 변동 (별도 API 필요)
        updated_at=now.isoformat(),
    )


@router.get(
    "/performance",
    response_model=DashboardPerformanceResponse,
    summary="수익률 추이",
    description="일별 또는 주별 수익률 추이를 조회합니다.",
)
def get_performance(
    period: str = Query(
        default="daily",
        description="조회 기간 (daily/weekly)",
        pattern=r"^(daily|weekly)$",
    ),
    days: int = Query(
        default=30,
        ge=1,
        le=365,
        description="조회 일수",
    ),
    client: KISClient = Depends(get_kis_client),
) -> DashboardPerformanceResponse:
    """수익률 추이 조회

    실제 운영에서는 DB에 일별 스냅샷을 저장하여 조회합니다.
    현재는 현재 잔고 기준으로 단일 데이터포인트를 반환합니다.
    """
    balance = client.get_balance()
    summary = balance.get("summary", {})

    total_eval = summary.get("total_eval", 0)
    total_purchase = summary.get("total_purchase", 0)
    profit_loss_rate = (
        ((total_eval - total_purchase) / total_purchase * 100)
        if total_purchase > 0
        else 0.0
    )

    now = datetime.now(UTC)

    # 현재 시점의 데이터포인트 생성
    items = [
        DashboardPerformanceItem(
            date=now.date().isoformat(),
            total_eval=total_eval,
            total_purchase=total_purchase,
            profit_loss=total_eval - total_purchase,
            profit_loss_rate=round(profit_loss_rate, 2),
            daily_return=0.0,
        ),
    ]

    logger.info("수익률 추이 조회: period=%s, days=%d", period, days)

    return DashboardPerformanceResponse(
        period=period,
        items=items,
        start_date=(now - timedelta(days=days)).date().isoformat(),
        end_date=now.date().isoformat(),
    )


@router.get(
    "/summary",
    response_model=DashboardSummaryResponse,
    summary="대시보드 요약",
    description="포트폴리오 종합 정보를 한 번에 조회합니다.",
)
def get_summary(
    client: KISClient = Depends(get_kis_client),
) -> DashboardSummaryResponse:
    """대시보드 종합 요약"""
    balance = client.get_balance()

    stocks = balance.get("stocks", [])
    summary = balance.get("summary", {})

    total_eval = summary.get("total_eval", 0)
    total_purchase = summary.get("total_purchase", 0)
    cash = summary.get("cash", 0)
    total_profit_loss = total_eval - total_purchase
    total_profit_loss_rate = (
        ((total_eval - total_purchase) / total_purchase * 100)
        if total_purchase > 0
        else 0.0
    )

    holdings = _calculate_holdings_pnl(stocks, total_eval)

    now = datetime.now(UTC)

    # 종목 수 및 수익/손실 종목 수
    profit_count = sum(1 for h in holdings if h.profit_loss > 0)
    loss_count = sum(1 for h in holdings if h.profit_loss < 0)
    even_count = sum(1 for h in holdings if h.profit_loss == 0)

    logger.info(
        "대시보드 요약: %d종목 (수익 %d, 손실 %d, 보합 %d)",
        len(holdings),
        profit_count,
        loss_count,
        even_count,
    )

    return DashboardSummaryResponse(
        total_eval_amount=total_eval,
        total_purchase_amount=total_purchase,
        total_profit_loss=total_profit_loss,
        total_profit_loss_rate=round(total_profit_loss_rate, 2),
        cash=cash,
        net_asset=total_eval + cash,
        holding_count=len(holdings),
        profit_count=profit_count,
        loss_count=loss_count,
        even_count=even_count,
        top_holdings=holdings[:5],
        daily_change=0.0,
        updated_at=now.isoformat(),
    )

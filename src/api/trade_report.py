"""
거래 리포트 API 엔드포인트

일일 거래 리포트 및 포트폴리오 스냅샷 조회 API를 제공합니다.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from src.api.dependencies import get_kis_client
from src.broker.kis_client import KISClient
from src.db import get_session_factory
from src.models.schema import Order
from src.utils.logger import get_logger
from src.utils.trade_report import (
    calculate_pnl,
    format_report_text,
    generate_daily_summary,
    generate_portfolio_snapshot,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/report", tags=["Reports"])


# ───────────────────── Pydantic 스키마 ─────────────────────


class DailySummaryResponse(BaseModel):
    """일일 거래 요약 응답"""

    date: str = Field(..., description="조회 날짜 (YYYY-MM-DD)")
    total_orders: int = Field(..., description="총 주문 수")
    executed_orders: int = Field(..., description="체결된 주문 수")
    buy_count: int = Field(..., description="매수 건수")
    sell_count: int = Field(..., description="매도 건수")
    total_buy_amount: float = Field(..., description="총 매수 금액")
    total_sell_amount: float = Field(..., description="총 매도 금액")


class PortfolioSnapshotItem(BaseModel):
    """포트폴리오 종목 항목"""

    stock_code: str
    stock_name: str
    quantity: int
    avg_price: float
    current_price: float
    evaluation: float = Field(..., description="평가금액")
    profit_loss: float = Field(..., description="손익")
    profit_loss_rate: float = Field(..., description="수익률 (%)")


class PortfolioSnapshotResponse(BaseModel):
    """포트폴리오 스냅샷 응답"""

    holdings: list[PortfolioSnapshotItem]
    total_evaluation: float = Field(..., description="총 평가금액")
    total_profit_loss: float = Field(..., description="총 손익")


class RealizedPnLByStock(BaseModel):
    """종목별 실현 손익"""

    buy_amount: float
    sell_amount: float
    realized_pnl: float


class DailyReportResponse(BaseModel):
    """일일 리포트 전체 응답"""

    summary: DailySummaryResponse
    realized_pnl: dict[str, Any] = Field(..., description="실현 손익 정보")
    text_report: str = Field(..., description="텍스트 기반 리포트 (Discord 출력용)")


# ───────────────────── API 엔드포인트 ─────────────────────


@router.get(
    "/daily",
    response_model=DailyReportResponse,
    summary="일일 거래 리포트 조회",
    description="특정 날짜의 거래 요약 및 실현 손익을 조회합니다.",
)
def get_daily_report(
    target_date: Annotated[
        date | None,
        Query(alias="date", description="조회 날짜 (YYYY-MM-DD). 기본값: 오늘"),
    ] = None,
    session_factory: sessionmaker = Depends(get_session_factory),
) -> DailyReportResponse:
    """일일 거래 리포트를 조회합니다."""
    if target_date is None:
        target_date = datetime.now().date()

    with session_factory() as session:
        # 모든 주문 조회 (실현 손익 계산용)
        stmt = select(Order)
        orders = session.execute(stmt).scalars().all()

        # 일일 요약 생성
        summary = generate_daily_summary(list(orders), target_date)

        # 실현 손익 계산
        pnl = calculate_pnl(list(orders))

        # 텍스트 리포트 생성 (포트폴리오는 빈 리스트로)
        text_report = format_report_text(summary, [], pnl)

        logger.info(
            "일일 리포트 생성: %s (주문 %d건, 체결 %d건)",
            target_date,
            summary["total_orders"],
            summary["executed_orders"],
        )

        return DailyReportResponse(
            summary=DailySummaryResponse(**summary),
            realized_pnl=pnl,
            text_report=text_report,
        )


@router.get(
    "/portfolio",
    response_model=PortfolioSnapshotResponse,
    summary="현재 포트폴리오 스냅샷 조회",
    description="실시간 포트폴리오 현황(보유 종목, 평가금액, 수익률)을 조회합니다.",
)
def get_portfolio_snapshot(
    client: KISClient = Depends(get_kis_client),
) -> PortfolioSnapshotResponse:
    """현재 포트폴리오 스냅샷을 조회합니다."""
    # KISClient를 통해 실시간 잔고 조회
    balance = client.get_balance()

    # holdings 데이터 변환
    holdings_data = []
    for stock in balance.get("stocks", []):
        holdings_data.append(
            {
                "stock_code": stock["stock_code"],
                "stock_name": stock.get("stock_name", ""),
                "quantity": stock["quantity"],
                "avg_price": stock["avg_price"],
                "current_price": stock["current_price"],
            },
        )

    # 포트폴리오 스냅샷 생성
    snapshot = generate_portfolio_snapshot(holdings_data)

    # 총 평가금액 및 총 손익 계산
    total_evaluation = sum(item["evaluation"] for item in snapshot)
    total_profit_loss = sum(item["profit_loss"] for item in snapshot)

    logger.info(
        "포트폴리오 스냅샷 생성: %d 종목, 총 평가 %.0f원",
        len(snapshot),
        total_evaluation,
    )

    return PortfolioSnapshotResponse(
        holdings=[PortfolioSnapshotItem(**item) for item in snapshot],
        total_evaluation=total_evaluation,
        total_profit_loss=total_profit_loss,
    )

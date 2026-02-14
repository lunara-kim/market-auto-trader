"""
SQLAlchemy 데이터베이스 모델

주요 엔티티의 테이블 스키마를 정의합니다.
SQLAlchemy 2.0 Mapped Column 패턴을 사용합니다.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


def _utcnow() -> datetime:
    """UTC 기준 현재 시각을 반환합니다."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """모든 모델의 베이스 클래스"""


class Portfolio(Base):
    """포트폴리오 테이블"""

    __tablename__ = "portfolios"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    account_no: Mapped[str] = mapped_column(String(50))
    total_value: Mapped[float]  # 총 평가금액
    cash: Mapped[float]  # 예수금
    profit_loss: Mapped[float] = mapped_column(default=0.0)  # 손익
    profit_loss_rate: Mapped[float] = mapped_column(default=0.0)  # 수익률 (%)
    updated_at: Mapped[datetime] = mapped_column(
        default=_utcnow,
        onupdate=_utcnow,
    )
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)

    # 관계
    orders: Mapped[list[Order]] = relationship(back_populates="portfolio")


class Order(Base):
    """주문 테이블"""

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    portfolio_id: Mapped[int | None] = mapped_column(
        ForeignKey("portfolios.id"),
    )
    stock_code: Mapped[str] = mapped_column(String(20))  # 종목 코드
    stock_name: Mapped[str | None] = mapped_column(String(100))  # 종목명
    order_type: Mapped[str] = mapped_column(String(10))  # buy, sell
    order_price: Mapped[float | None] = mapped_column()  # 주문가 (None → 시장가)
    quantity: Mapped[int]  # 수량
    status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
    )  # pending, executed, cancelled
    executed_price: Mapped[float | None] = mapped_column()  # 체결가
    executed_at: Mapped[datetime | None] = mapped_column()  # 체결 시각
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)

    # 관계
    portfolio: Mapped[Portfolio | None] = relationship(back_populates="orders")


class MarketData(Base):
    """시장 데이터 테이블"""

    __tablename__ = "market_data"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    stock_code: Mapped[str] = mapped_column(String(20), index=True)
    stock_name: Mapped[str | None] = mapped_column(String(100))
    date: Mapped[datetime] = mapped_column(index=True)
    open_price: Mapped[float | None] = mapped_column()  # 시가
    high_price: Mapped[float | None] = mapped_column()  # 고가
    low_price: Mapped[float | None] = mapped_column()  # 저가
    close_price: Mapped[float | None] = mapped_column()  # 종가
    volume: Mapped[int | None] = mapped_column()  # 거래량
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)


class RebalanceHistory(Base):
    """리밸런싱 내역 테이블"""

    __tablename__ = "rebalance_history"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    trigger_type: Mapped[str] = mapped_column(String(20))  # "manual", "scheduled"
    schedule_type: Mapped[str | None] = mapped_column(String(20))  # "daily", "weekly", "monthly"
    total_equity: Mapped[float]  # 실행 시점 총 평가액
    cash_before: Mapped[float]  # 실행 전 현금
    cash_after: Mapped[float]  # 실행 후 예상 현금
    total_orders: Mapped[int]  # 생성된 주문 수
    buy_orders_count: Mapped[int]
    sell_orders_count: Mapped[int]
    skipped_stocks: Mapped[str | None] = mapped_column(Text())  # JSON 배열
    status: Mapped[str] = mapped_column(
        String(20), default="planned",
    )  # planned, executing, completed, failed
    error_message: Mapped[str | None] = mapped_column(Text())
    started_at: Mapped[datetime] = mapped_column(default=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)

    # 관계
    order_details: Mapped[list[RebalanceOrderDetail]] = relationship(
        back_populates="rebalance_history",
    )


class RebalanceOrderDetail(Base):
    """리밸런싱 주문 상세 테이블"""

    __tablename__ = "rebalance_order_details"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    rebalance_id: Mapped[int] = mapped_column(
        ForeignKey("rebalance_history.id"),
    )
    stock_code: Mapped[str] = mapped_column(String(20))
    side: Mapped[str] = mapped_column(String(10))  # buy, sell
    quantity: Mapped[int]
    current_price: Mapped[float]
    target_value_krw: Mapped[float]
    reason: Mapped[str | None] = mapped_column(Text())
    status: Mapped[str] = mapped_column(
        String(20), default="planned",
    )  # planned, executed, failed
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)

    # 관계
    rebalance_history: Mapped[RebalanceHistory] = relationship(
        back_populates="order_details",
    )


class Signal(Base):
    """매매 신호 테이블"""

    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    stock_code: Mapped[str] = mapped_column(String(20))
    signal_type: Mapped[str] = mapped_column(String(10))  # buy, sell, hold
    strength: Mapped[float | None] = mapped_column()  # 신호 강도 (0.0 ~ 1.0)
    target_price: Mapped[float | None] = mapped_column()  # 목표가
    stop_loss: Mapped[float | None] = mapped_column()  # 손절가
    strategy_name: Mapped[str | None] = mapped_column(String(100))  # 전략명
    reason: Mapped[str | None] = mapped_column(Text())  # 신호 생성 사유
    is_executed: Mapped[bool] = mapped_column(default=False)  # 실행 여부
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)

"""
API 요청/응답 Pydantic 스키마

포트폴리오, 주문, 매매 신호 관련 DTO를 정의합니다.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────
# 공통
# ─────────────────────────────────────────────

class HealthResponse(BaseModel):
    """헬스 체크 응답"""

    status: str = "ok"
    version: str
    env: str


class ErrorDetail(BaseModel):
    """에러 응답"""

    code: str
    message: str
    detail: dict | None = None


class ErrorResponse(BaseModel):
    """에러 응답 래퍼"""

    error: ErrorDetail


# ─────────────────────────────────────────────
# 포트폴리오
# ─────────────────────────────────────────────

class HoldingItem(BaseModel):
    """보유 종목"""

    stock_code: str = Field(description="종목 코드")
    stock_name: str = Field(description="종목명")
    quantity: int = Field(description="보유 수량")
    avg_price: float = Field(description="매입 평균가")
    current_price: float = Field(description="현재가")
    eval_amount: float = Field(description="평가 금액")
    profit_loss: float = Field(description="평가 손익")
    profit_loss_rate: float = Field(description="수익률 (%)")


class PortfolioSummary(BaseModel):
    """계좌 요약"""

    cash: float = Field(description="예수금")
    total_eval: float = Field(description="총 평가금액")
    total_purchase: float = Field(description="매입금액 합계")
    total_profit_loss: float = Field(description="평가손익 합계")
    net_asset: float = Field(description="순자산")


class PortfolioResponse(BaseModel):
    """포트폴리오 전체 응답"""

    holdings: list[HoldingItem] = Field(default_factory=list)
    summary: PortfolioSummary
    updated_at: str = Field(description="조회 시각 (ISO 8601)")


# ─────────────────────────────────────────────
# 주문
# ─────────────────────────────────────────────

class OrderType(str, Enum):
    """주문 종류"""

    BUY = "buy"
    SELL = "sell"


class OrderStatus(str, Enum):
    """주문 상태"""

    PENDING = "pending"
    EXECUTED = "executed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class OrderRequest(BaseModel):
    """주문 요청"""

    stock_code: str = Field(
        min_length=6,
        max_length=6,
        pattern=r"^\d{6}$",
        description="종목 코드 (6자리)",
    )
    order_type: OrderType = Field(description="buy 또는 sell")
    quantity: int = Field(gt=0, description="주문 수량")
    price: int | None = Field(
        default=None,
        ge=0,
        description="주문 가격 (None이면 시장가)",
    )


class OrderResponse(BaseModel):
    """주문 결과"""

    order_id: str = Field(description="주문 번호")
    stock_code: str
    order_type: str
    quantity: int
    price: str = Field(description="주문 가격 (시장가이면 '시장가')")
    status: str
    ordered_at: str = Field(description="주문 시각")


class OrderHistoryItem(BaseModel):
    """주문 내역 항목"""

    id: int
    stock_code: str
    stock_name: str | None = None
    order_type: str
    order_price: float | None = None
    quantity: int
    status: str
    executed_price: float | None = None
    executed_at: datetime | None = None
    created_at: datetime


class OrderHistoryResponse(BaseModel):
    """주문 내역 응답"""

    orders: list[OrderHistoryItem] = Field(default_factory=list)
    total: int = Field(description="전체 주문 수")
    page: int = Field(default=1)
    size: int = Field(default=20)


# ─────────────────────────────────────────────
# 매매 신호
# ─────────────────────────────────────────────

class MATypeEnum(str, Enum):
    """이동평균 종류"""

    SMA = "sma"
    EMA = "ema"


class SignalRequest(BaseModel):
    """매매 신호 생성 요청"""

    stock_code: str = Field(
        min_length=6,
        max_length=6,
        pattern=r"^\d{6}$",
        description="종목 코드 (6자리)",
    )
    short_window: int = Field(default=5, ge=2, description="단기 이동평균 기간")
    long_window: int = Field(default=20, ge=3, description="장기 이동평균 기간")
    ma_type: MATypeEnum = Field(default=MATypeEnum.SMA, description="이동평균 종류")


class SignalMetrics(BaseModel):
    """신호 지표"""

    current_short_ma: float
    current_long_ma: float
    ma_spread: float
    trend: str
    current_price: float


class SignalResponse(BaseModel):
    """매매 신호 응답"""

    stock_code: str
    signal: str = Field(description="buy / sell / hold")
    strength: float = Field(description="신호 강도 (0.0 ~ 1.0)")
    reason: str
    strategy_name: str
    metrics: SignalMetrics
    timestamp: str


class SignalHistoryItem(BaseModel):
    """신호 내역 항목"""

    id: int
    stock_code: str
    signal_type: str
    strength: float | None = None
    target_price: float | None = None
    stop_loss: float | None = None
    strategy_name: str | None = None
    reason: str | None = None
    is_executed: bool
    created_at: datetime


class SignalHistoryResponse(BaseModel):
    """신호 내역 응답"""

    signals: list[SignalHistoryItem] = Field(default_factory=list)
    total: int

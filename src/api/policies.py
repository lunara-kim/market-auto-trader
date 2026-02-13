"""주문 관련 FastAPI 엔드포인트

- 원샷(단일) 매수 정책 실행 (국내/해외)
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from config.settings import settings
from src.broker.kis_client import KISClient
from src.exceptions import ValidationError
from src.strategy.oneshot import OneShotOrderConfig, OneShotOrderService
from src.strategy.oneshot_overseas import (
    OneShotOverseasOrderConfig,
    OneShotOverseasOrderService,
    OneShotOverseasSellConfig,
    OneShotOverseasSellService,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/policies", tags=["policies"])


class OneShotOrderRequest(BaseModel):
    """원샷 주문 요청 스키마

    실제 매매 정책이지만, dry_run 플래그를 통해 주문 전 검증만 수행할 수도 있다.
    """

    stock_code: str = Field(..., description="6자리 종목 코드", min_length=6, max_length=6)
    quantity: int = Field(..., description="주문 수량 (1 이상)", ge=1)
    max_notional_krw: int = Field(
        ..., description="주문 금액 상한 (현재가 * 수량이 이 값을 초과하면 거부)", gt=0
    )
    explicit_price: int | None = Field(
        None,
        description="지정가 주문 가격. None이면 시장가 주문.",
    )
    dry_run: bool = Field(
        True,
        description="True면 실제 주문은 보내지 않고 금액/유효성 검증만 수행",
    )


class OneShotOrderResponse(BaseModel):
    """원샷 주문 응답 스키마"""

    summary: dict[str, Any]
    raw_result: dict[str, Any] | None = None


def _create_kis_client_from_settings() -> KISClient:
    """환경설정에서 한국투자증권 클라이언트 생성"""
    if not settings.kis_app_key or not settings.kis_app_secret or not settings.kis_account_no:
        raise ValidationError(
            "KIS API 설정이 누락되었습니다.",
            detail={
                "kis_app_key": bool(settings.kis_app_key),
                "kis_app_secret": bool(settings.kis_app_secret),
                "kis_account_no": bool(settings.kis_account_no),
            },
        )

    client = KISClient(
        app_key=settings.kis_app_key,
        app_secret=settings.kis_app_secret,
        account_no=settings.kis_account_no,
        mock=settings.kis_mock,
    )
    return client


@router.post("/oneshot", response_model=OneShotOrderResponse)
async def execute_oneshot_policy(payload: OneShotOrderRequest) -> OneShotOrderResponse:
    """원샷 매매 정책 실행 엔드포인트

    - dry_run=True(default): 현재가 조회 + 금액 상한 검증만 수행
    - dry_run=False: 실제 주문까지 수행

    이 엔드포인트는 "정책(policy)" 관점에서 단일 주문을 실행하는 용도로 설계되었으며,
    내부적으로는 OneShotOrderService를 사용한다.
    """

    # Pydantic 기본 검증 이후, 추가 도메인 검증은 서비스 레벨에서 수행
    logger.info(
        "원샷 정책 실행 요청: %s", asdict(OneShotOrderConfig(**payload.model_dump(exclude={"dry_run"})))
    )

    with _create_kis_client_from_settings() as client:
        service = OneShotOrderService(client)
        config = OneShotOrderConfig(
            stock_code=payload.stock_code,
            quantity=payload.quantity,
            max_notional_krw=payload.max_notional_krw,
            explicit_price=payload.explicit_price,
        )

        # 먼저 금액/유효성 검증
        summary = service.prepare_order(config)

        if payload.dry_run:
            logger.info("원샷 정책 dry_run 완료 (주문 미발송): %s", summary)
            return OneShotOrderResponse(summary=summary, raw_result=None)

        # 실제 주문 실행
        result = service.execute_order(config)

        return OneShotOrderResponse(**result)


# ───────────────────── Overseas Oneshot ─────────────────────


class OneShotOverseasOrderRequest(BaseModel):
    """해외 원샷 주문 요청 스키마"""

    ticker: str = Field(..., description="해외 종목 티커 (예: AAPL, TSLA)", min_length=1, max_length=10)
    exchange_code: str = Field(..., description="거래소 코드 (NASD, NYSE, AMEX)")
    quantity: int = Field(..., description="주문 수량 (1 이상)", ge=1)
    max_notional_usd: float = Field(
        ..., description="주문 금액 상한 USD (현재가 * 수량이 이 값을 초과하면 거부)", gt=0
    )
    explicit_price: float | None = Field(
        None,
        description="지정가 주문 가격 (USD). None이면 현재가 기반 주문.",
    )
    dry_run: bool = Field(
        True,
        description="True면 실제 주문은 보내지 않고 금액/유효성 검증만 수행",
    )


class OneShotOverseasOrderResponse(BaseModel):
    """해외 원샷 주문 응답 스키마"""

    summary: dict[str, Any]
    raw_result: dict[str, Any] | None = None


class OneShotOverseasSellOrderRequest(BaseModel):
    """해외 원샷 매도 주문 요청 스키마"""

    ticker: str = Field(..., description="해외 종목 티커 (예: AAPL, TSLA)", min_length=1, max_length=10)
    exchange_code: str = Field(..., description="거래소 코드 (NASD, NYSE, AMEX)")
    quantity: int = Field(..., description="매도 수량 (1 이상)", ge=1)
    max_notional_usd: float = Field(
        ..., description="매도 금액 상한 USD (현재가 * 수량이 이 값을 초과하면 거부)", gt=0
    )
    explicit_price: float | None = Field(
        None,
        description="지정가 매도 가격 (USD). None이면 현재가 기반 주문.",
    )
    dry_run: bool = Field(
        True,
        description="True면 실제 주문은 보내지 않고 금액/유효성 검증만 수행",
    )


class OneShotOverseasSellOrderResponse(BaseModel):
    """해외 원샷 매도 주문 응답 스키마"""

    summary: dict[str, Any]
    raw_result: dict[str, Any] | None = None


@router.post("/oneshot/overseas", response_model=OneShotOverseasOrderResponse)
async def execute_oneshot_overseas_policy(
    payload: OneShotOverseasOrderRequest,
) -> OneShotOverseasOrderResponse:
    """해외주식 원샷 매매 정책 실행 엔드포인트

    - dry_run=True(default): 현재가 조회 + 금액 상한 검증만 수행
    - dry_run=False: 실제 주문까지 수행

    해외주식(미국: NASD/NYSE/AMEX)에 대한 단일 매수 주문을 실행한다.
    """

    logger.info(
        "해외 원샷 정책 실행 요청: %s (%s) %d주",
        payload.ticker,
        payload.exchange_code,
        payload.quantity,
    )

    with _create_kis_client_from_settings() as client:
        service = OneShotOverseasOrderService(client)
        config = OneShotOverseasOrderConfig(
            ticker=payload.ticker,
            exchange_code=payload.exchange_code,
            quantity=payload.quantity,
            max_notional_usd=payload.max_notional_usd,
            explicit_price=payload.explicit_price,
        )

        # 먼저 금액/유효성 검증
        summary = service.prepare_order(config)

        if payload.dry_run:
            logger.info("해외 원샷 정책 dry_run 완료 (주문 미발송): %s", summary)
            return OneShotOverseasOrderResponse(summary=summary, raw_result=None)

        # 실제 주문 실행
        result = service.execute_order(config)

        return OneShotOverseasOrderResponse(**result)


@router.post("/oneshot/overseas/sell", response_model=OneShotOverseasSellOrderResponse)
async def execute_oneshot_overseas_sell_policy(
    payload: OneShotOverseasSellOrderRequest,
) -> OneShotOverseasSellOrderResponse:
    """해외주식 원샷 **매도** 정책 실행 엔드포인트

    - dry_run=True(default): 현재가 조회 + 금액 상한 검증만 수행
    - dry_run=False: 실제 매도 주문까지 수행

    해외주식(미국: NASD/NYSE/AMEX)에 대한 단일 매도 주문을 실행한다.
    """

    logger.info(
        "해외 원샷 매도 정책 실행 요청: %s (%s) %d주",
        payload.ticker,
        payload.exchange_code,
        payload.quantity,
    )

    with _create_kis_client_from_settings() as client:
        service = OneShotOverseasSellService(client)
        config = OneShotOverseasSellConfig(
            ticker=payload.ticker,
            exchange_code=payload.exchange_code,
            quantity=payload.quantity,
            max_notional_usd=payload.max_notional_usd,
            explicit_price=payload.explicit_price,
        )

        summary = service.prepare_sell(config)

        if payload.dry_run:
            logger.info("해외 원샷 매도 정책 dry_run 완료 (주문 미발송): %s", summary)
            return OneShotOverseasSellOrderResponse(summary=summary, raw_result=None)

        result = service.execute_sell(config)

        return OneShotOverseasSellOrderResponse(**result)

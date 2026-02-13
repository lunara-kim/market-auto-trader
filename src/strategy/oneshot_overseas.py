"""해외(미국) 주식 원샷(단일) 주문 전략/서비스

AAPL 1주 지정가 매수 같은 단발성 해외 주식 주문을
안전하게 실행하기 위한 도메인 서비스.

국내용 OneShotOrderService와 동일한 패턴(prepare → execute)을 따르되,
해외주식 특성(ticker, exchange_code, USD 기반 금액 체크)을 반영한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.broker.kis_client import VALID_EXCHANGE_CODES, KISClient
from src.exceptions import InsufficientFundsError, ValidationError
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class OneShotOverseasOrderConfig:
    """해외 원샷 주문 설정값

    Attributes:
        ticker: 해외 종목 티커 (예: "AAPL", "TSLA")
        exchange_code: 거래소 코드 ("NASD", "NYSE", "AMEX")
        quantity: 주문 수량 (1 이상 정수)
        max_notional_usd: 주문 금액 상한 USD (현재가 * 수량이 이 값을 초과하면 거부)
        explicit_price: 지정가 주문 시 가격 (USD). None이면 현재가 기반 주문.
    """

    ticker: str
    exchange_code: str
    quantity: int
    max_notional_usd: float
    explicit_price: float | None = None


class OneShotOverseasOrderService:
    """해외주식 단일 주문 실행 서비스 (매수 중심)

    - 해외 현재가 조회
    - 주문 금액(max_notional_usd) 가드 체크
    - 주문 요청 실행

    KISClient의 해외주식 메서드를 thin wrapper 형태로 감싸서
    테스트가 용이하도록 구성한다.
    """

    def __init__(self, kis_client: KISClient) -> None:
        if not isinstance(kis_client, KISClient):
            raise ValidationError(
                "kis_client는 KISClient 인스턴스여야 합니다.",
                detail={"type": type(kis_client).__name__},
            )
        self._client = kis_client

    # ───────────────────── Public API ─────────────────────

    def prepare_order(self, config: OneShotOverseasOrderConfig) -> dict[str, Any]:
        """현재가 기준 주문 정보를 계산하고 유효성 검증을 수행.

        Returns:
            dict: 로그/응답용 요약 정보
        """
        self._validate_config(config)

        # 해외 현재가 조회
        price_info = self._client.get_overseas_price(
            config.ticker, config.exchange_code
        )
        raw_price = price_info.get("last")
        try:
            current_price = float(raw_price)
        except (TypeError, ValueError):
            raise ValidationError(
                "해외 현재가(last)를 숫자로 변환할 수 없습니다.",
                detail={"ticker": config.ticker, "last": raw_price},
            )

        if current_price <= 0:
            raise ValidationError(
                "해외 현재가가 0 이하입니다.",
                detail={"ticker": config.ticker, "current_price": current_price},
            )

        # 실제 주문 가격: explicit_price가 있으면 사용, 없으면 현재가
        order_price = (
            config.explicit_price if config.explicit_price is not None else current_price
        )
        notional = order_price * config.quantity

        logger.info(
            "해외 원샷 주문 준비: %s (%s) %d주 × $%.2f = $%.2f (상한: $%.2f)",
            config.ticker,
            config.exchange_code,
            config.quantity,
            order_price,
            notional,
            config.max_notional_usd,
        )

        if notional > config.max_notional_usd:
            raise InsufficientFundsError(
                "해외 원샷 주문 금액이 설정한 상한을 초과합니다.",
                detail={
                    "ticker": config.ticker,
                    "exchange_code": config.exchange_code,
                    "quantity": config.quantity,
                    "current_price": current_price,
                    "order_price": order_price,
                    "notional": notional,
                    "max_notional_usd": config.max_notional_usd,
                },
            )

        return {
            "ticker": config.ticker,
            "exchange_code": config.exchange_code,
            "quantity": config.quantity,
            "current_price": current_price,
            "order_price": order_price,
            "notional": notional,
            "order_type": "limit"
            if config.explicit_price is not None
            else "market_price",
        }

    def execute_order(self, config: OneShotOverseasOrderConfig) -> dict[str, Any]:
        """해외 원샷 매수 주문 실제 실행.

        1. prepare_order()로 금액/유효성 검증
        2. 검증 통과 시 KISClient.place_overseas_order(order_type="buy") 호출
        """
        summary = self.prepare_order(config)

        # 해외주식은 지정가가 필수 → explicit_price가 없으면 현재가를 사용
        order_price = summary["order_price"]

        result = self._client.place_overseas_order(
            ticker=config.ticker,
            exchange_code=config.exchange_code,
            quantity=config.quantity,
            price=order_price,
            order_type="buy",
        )

        logger.info(
            "해외 원샷 매수 주문 실행 완료: %s (%s) %d주 (주문번호: %s)",
            config.ticker,
            config.exchange_code,
            config.quantity,
            result.get("ODNO", "N/A"),
        )

        return {
            "summary": summary,
            "raw_result": result,
        }

    # ───────────────────── Internal Helpers ─────────────────────

    @staticmethod
    def _validate_config(config: OneShotOverseasOrderConfig) -> None:
        """입력 설정값 검증"""
        if not config.ticker or not config.ticker.isalpha():
            raise ValidationError(
                "해외 종목 티커는 영문자로만 구성되어야 합니다.",
                detail={"ticker": config.ticker},
            )

        if config.exchange_code not in VALID_EXCHANGE_CODES:
            raise ValidationError(
                f"거래소 코드는 {VALID_EXCHANGE_CODES} 중 하나여야 합니다.",
                detail={"exchange_code": config.exchange_code},
            )

        if config.quantity < 1:
            raise ValidationError(
                "주문 수량은 1 이상이어야 합니다.",
                detail={"quantity": config.quantity},
            )

        if config.max_notional_usd <= 0:
            raise ValidationError(
                "max_notional_usd는 0보다 커야 합니다.",
                detail={"max_notional_usd": config.max_notional_usd},
            )

        if config.explicit_price is not None and config.explicit_price <= 0:
            raise ValidationError(
                "지정가 가격은 0보다 커야 합니다.",
                detail={"explicit_price": config.explicit_price},
            )


@dataclass
class OneShotOverseasSellConfig:
    """해외 원샷 매도 주문 설정값

    매수 설정과 동일한 필드를 사용하지만, 의미적으로 매도 정책임을 명시하기 위해
    별도 Config 클래스를 둔다.
    """

    ticker: str
    exchange_code: str
    quantity: int
    max_notional_usd: float
    explicit_price: float | None = None


class OneShotOverseasSellService:
    """해외주식 단일 매도 주문 실행 서비스

    내부적으로 OneShotOverseasOrderService의 검증/현재가 조회 로직을 재사용한다.
    """

    def __init__(self, kis_client: KISClient) -> None:
        if not isinstance(kis_client, KISClient):
            raise ValidationError(
                "kis_client는 KISClient 인스턴스여야 합니다.",
                detail={"type": type(kis_client).__name__},
            )
        self._client = kis_client
        self._order_service = OneShotOverseasOrderService(kis_client)

    def prepare_sell(self, config: OneShotOverseasSellConfig) -> dict[str, Any]:
        """매도 주문 전 현재가/금액 상한 검증 수행"""
        order_config = OneShotOverseasOrderConfig(
            ticker=config.ticker,
            exchange_code=config.exchange_code,
            quantity=config.quantity,
            max_notional_usd=config.max_notional_usd,
            explicit_price=config.explicit_price,
        )
        return self._order_service.prepare_order(order_config)

    def execute_sell(self, config: OneShotOverseasSellConfig) -> dict[str, Any]:
        """해외 원샷 매도 주문 실제 실행.

        1. prepare_sell()로 금액/유효성 검증
        2. 검증 통과 시 KISClient.place_overseas_order(order_type="sell") 호출
        """
        summary = self.prepare_sell(config)
        order_price = summary["order_price"]

        result = self._client.place_overseas_order(
            ticker=config.ticker,
            exchange_code=config.exchange_code,
            quantity=config.quantity,
            price=order_price,
            order_type="sell",
        )

        logger.info(
            "해외 원샷 매도 주문 실행 완료: %s (%s) %d주 (주문번호: %s)",
            config.ticker,
            config.exchange_code,
            config.quantity,
            result.get("ODNO", "N/A"),
        )

        return {
            "summary": summary,
            "raw_result": result,
        }

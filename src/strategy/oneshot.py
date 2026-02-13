"""원샷(단일) 주문 전략/서비스

AMDL 1주 시장가 매수 같은 단발성 테스트/사용자 지정 주문을
안전하게 실행하기 위한 얇은 도메인 서비스.

이 모듈은 이후 BaseStrategy 기반 일반 전략 시스템으로
승격하기 전, 기능 테스트 및 실전 환경 검증용으로 사용된다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.broker.kis_client import KISClient
from src.exceptions import InsufficientFundsError, ValidationError
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class OneShotOrderConfig:
    """원샷 주문 설정값

    Attributes:
        stock_code: 6자리 종목 코드 (예: "005930")
        quantity: 주문 수량 (1 이상 정수)
        max_notional_krw: 주문 금액 상한 (현재가 * 수량이 이 값을 초과하면 거부)
        explicit_price: 지정가 주문 시 가격. None이면 시장가 주문.
    """

    stock_code: str
    quantity: int
    max_notional_krw: int
    explicit_price: int | None = None


class OneShotOrderService:
    """단일 주문 실행 서비스

    - 현재가 조회
    - 주문 금액(max_notional_krw) 가드 체크
    - 주문 요청 실행

    실제 KISClient.place_order() 를 thin wrapper 형태로 감싸서
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

    def prepare_order(self, config: OneShotOrderConfig) -> dict[str, Any]:
        """현재가 기준 주문 정보를 계산하고 유효성 검증을 수행.

        Returns:
            dict: 로그/응답용 요약 정보
        """
        self._validate_config(config)

        # 현재가 조회
        price_info = self._client.get_price(config.stock_code)
        raw_price = price_info.get("stck_prpr")
        try:
            current_price = int(raw_price)
        except (TypeError, ValueError):  # pragma: no cover - 방어 코드
            raise ValidationError(
                "현재가(stck_prpr)를 정수로 변환할 수 없습니다.",
                detail={"stock_code": config.stock_code, "stck_prpr": raw_price},
            )

        notional = current_price * config.quantity
        logger.info(
            "원샷 주문 준비: %s %d주 × %d원 = %d원 (상한: %d원)",
            config.stock_code,
            config.quantity,
            current_price,
            notional,
            config.max_notional_krw,
        )

        if notional > config.max_notional_krw:
            # 잔고 부족과는 별개로, 전략 차원의 최대 허용 금액 초과
            raise InsufficientFundsError(
                "원샷 주문 금액이 설정한 상한을 초과합니다.",
                detail={
                    "stock_code": config.stock_code,
                    "quantity": config.quantity,
                    "current_price": current_price,
                    "notional": notional,
                    "max_notional_krw": config.max_notional_krw,
                },
            )

        return {
            "stock_code": config.stock_code,
            "quantity": config.quantity,
            "current_price": current_price,
            "notional": notional,
            "order_type": "market" if config.explicit_price is None else "limit",
            "limit_price": config.explicit_price,
        }

    def execute_order(self, config: OneShotOrderConfig) -> dict[str, Any]:
        """원샷 주문 실제 실행.

        1. prepare_order()로 금액/유효성 검증
        2. 검증 통과 시 KISClient.place_order() 호출
        """
        summary = self.prepare_order(config)

        result = self._client.place_order(
            stock_code=config.stock_code,
            order_type="buy",  # 원샷 서비스는 테스트용 매수 전용
            quantity=config.quantity,
            price=config.explicit_price,
        )

        logger.info(
            "원샷 주문 실행 완료: %s %d주 (주문번호: %s)",
            config.stock_code,
            config.quantity,
            result.get("ODNO", "N/A"),
        )

        # 호출자 입장에서 요약 + 원본 결과 둘 다 필요할 수 있으므로 합쳐서 반환
        return {
            "summary": summary,
            "raw_result": result,
        }

    # ───────────────────── Internal Helpers ─────────────────────

    @staticmethod
    def _validate_config(config: OneShotOrderConfig) -> None:
        """입력 설정값 검증"""
        if not config.stock_code or len(config.stock_code) != 6 or not config.stock_code.isdigit():
            raise ValidationError(
                "종목 코드는 6자리 숫자여야 합니다.",
                detail={"stock_code": config.stock_code},
            )

        if config.quantity < 1:
            raise ValidationError(
                "주문 수량은 1 이상이어야 합니다.",
                detail={"quantity": config.quantity},
            )

        if config.max_notional_krw <= 0:
            raise ValidationError(
                "max_notional_krw는 0보다 커야 합니다.",
                detail={"max_notional_krw": config.max_notional_krw},
            )

        if config.explicit_price is not None and config.explicit_price <= 0:
            raise ValidationError(
                "지정가 가격은 0보다 커야 합니다.",
                detail={"explicit_price": config.explicit_price},
            )

"""
한국투자증권 OpenAPI 클라이언트

한국투자증권의 REST API를 사용하여 주식 시세 조회 및 주문을 처리합니다.
"""

from __future__ import annotations

from typing import Any

from src.utils.logger import get_logger

logger = get_logger(__name__)


class KISClient:
    """한국투자증권 API 클라이언트"""

    def __init__(
        self,
        app_key: str,
        app_secret: str,
        account_no: str,
        *,
        mock: bool = True,
    ) -> None:
        """
        Args:
            app_key: 한국투자증권 앱 키
            app_secret: 한국투자증권 앱 시크릿
            account_no: 계좌번호
            mock: 모의투자 모드 여부
        """
        self.app_key = app_key
        self.app_secret = app_secret
        self.account_no = account_no
        self.mock = mock
        self.access_token: str | None = None
        logger.info(
            "KISClient 초기화 (모의투자: %s, 계좌: %s***)",
            mock,
            account_no[:4] if len(account_no) > 4 else "****",
        )

    def get_balance(self) -> dict[str, Any]:
        """
        계좌 잔고 조회

        Returns:
            계좌 잔고 정보 (보유 종목, 평가금액, 예수금 등)

        Raises:
            NotImplementedError: 아직 구현되지 않음
        """
        logger.warning("get_balance() 호출됨 — 아직 미구현")
        raise NotImplementedError("get_balance() 메서드는 구현 예정입니다.")

    def place_order(
        self,
        stock_code: str,
        order_type: str,
        quantity: int,
        price: int | None = None,
    ) -> dict[str, Any]:
        """
        주식 주문 실행

        Args:
            stock_code: 종목 코드 (예: "005930" — 삼성전자)
            order_type: 주문 유형 ("buy" 또는 "sell")
            quantity: 주문 수량
            price: 주문 가격 (None이면 시장가)

        Returns:
            주문 결과 정보

        Raises:
            NotImplementedError: 아직 구현되지 않음
        """
        logger.warning(
            "place_order() 호출됨 — 아직 미구현 (종목: %s, 유형: %s, 수량: %d)",
            stock_code,
            order_type,
            quantity,
        )
        raise NotImplementedError("place_order() 메서드는 구현 예정입니다.")

    def get_price(self, stock_code: str) -> dict[str, Any]:
        """
        실시간 주식 시세 조회

        Args:
            stock_code: 종목 코드 (예: "005930" — 삼성전자)

        Returns:
            현재가, 등락률, 거래량 등 시세 정보

        Raises:
            NotImplementedError: 아직 구현되지 않음
        """
        logger.warning("get_price() 호출됨 — 아직 미구현 (종목: %s)", stock_code)
        raise NotImplementedError("get_price() 메서드는 구현 예정입니다.")

"""OneShotOverseasOrderService 테스트

해외주식 원샷 주문 도메인 서비스에 대한 단위 테스트.
모든 외부 API 호출(KISClient)은 모킹하여 테스트합니다.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.broker.kis_client import KISClient
from src.exceptions import InsufficientFundsError, ValidationError
from src.strategy.oneshot_overseas import (
    OneShotOverseasOrderConfig,
    OneShotOverseasOrderService,
)


MOCK_APP_KEY = "test_app_key_12345"
MOCK_APP_SECRET = "test_app_secret_67890"
MOCK_ACCOUNT = "12345678-01"


@pytest.fixture
def kis_client() -> KISClient:
    """기본 KISClient 인스턴스"""
    return KISClient(MOCK_APP_KEY, MOCK_APP_SECRET, MOCK_ACCOUNT)


@pytest.fixture
def service(kis_client: KISClient) -> OneShotOverseasOrderService:
    return OneShotOverseasOrderService(kis_client)


class TestInit:
    """초기화 테스트"""

    def test_init_with_kis_client(self, kis_client: KISClient) -> None:
        svc = OneShotOverseasOrderService(kis_client)
        assert svc._client is kis_client

    def test_init_invalid_client_type(self) -> None:
        with pytest.raises(ValidationError, match="KISClient"):
            OneShotOverseasOrderService("not_a_client")  # type: ignore[arg-type]


class TestValidation:
    """입력 유효성 검증 테스트"""

    def test_invalid_ticker_raises(self, service: OneShotOverseasOrderService) -> None:
        config = OneShotOverseasOrderConfig(
            ticker="123",  # 숫자
            exchange_code="NASD",
            quantity=1,
            max_notional_usd=1000.0,
        )
        with pytest.raises(ValidationError, match="해외 종목 티커"):
            service.prepare_order(config)

    def test_empty_ticker_raises(self, service: OneShotOverseasOrderService) -> None:
        config = OneShotOverseasOrderConfig(
            ticker="",
            exchange_code="NASD",
            quantity=1,
            max_notional_usd=1000.0,
        )
        with pytest.raises(ValidationError, match="해외 종목 티커"):
            service.prepare_order(config)

    def test_invalid_exchange_code_raises(self, service: OneShotOverseasOrderService) -> None:
        config = OneShotOverseasOrderConfig(
            ticker="AAPL",
            exchange_code="KOSPI",
            quantity=1,
            max_notional_usd=1000.0,
        )
        with pytest.raises(ValidationError, match="거래소 코드"):
            service.prepare_order(config)

    def test_invalid_quantity_raises(self, service: OneShotOverseasOrderService) -> None:
        config = OneShotOverseasOrderConfig(
            ticker="AAPL",
            exchange_code="NASD",
            quantity=0,
            max_notional_usd=1000.0,
        )
        with pytest.raises(ValidationError, match="주문 수량은 1 이상"):
            service.prepare_order(config)

    def test_invalid_max_notional_raises(self, service: OneShotOverseasOrderService) -> None:
        config = OneShotOverseasOrderConfig(
            ticker="AAPL",
            exchange_code="NASD",
            quantity=1,
            max_notional_usd=0,
        )
        with pytest.raises(ValidationError, match="max_notional_usd는 0보다 커야"):
            service.prepare_order(config)

    def test_invalid_explicit_price_raises(self, service: OneShotOverseasOrderService) -> None:
        config = OneShotOverseasOrderConfig(
            ticker="AAPL",
            exchange_code="NASD",
            quantity=1,
            max_notional_usd=1000.0,
            explicit_price=0,
        )
        with pytest.raises(ValidationError, match="지정가 가격은 0보다 커야"):
            service.prepare_order(config)

    def test_negative_explicit_price_raises(self, service: OneShotOverseasOrderService) -> None:
        config = OneShotOverseasOrderConfig(
            ticker="AAPL",
            exchange_code="NASD",
            quantity=1,
            max_notional_usd=1000.0,
            explicit_price=-10.0,
        )
        with pytest.raises(ValidationError, match="지정가 가격은 0보다 커야"):
            service.prepare_order(config)


class TestPrepareOrder:
    """prepare_order 동작 테스트"""

    def test_prepare_order_success_market_price(
        self, service: OneShotOverseasOrderService, kis_client: KISClient
    ) -> None:
        """현재가 기반 주문 (explicit_price=None)"""
        kis_client.get_overseas_price = MagicMock(  # type: ignore[assignment]
            return_value={"last": "185.50"}
        )

        config = OneShotOverseasOrderConfig(
            ticker="AAPL",
            exchange_code="NASD",
            quantity=2,
            max_notional_usd=500.0,
        )

        summary = service.prepare_order(config)

        assert summary["ticker"] == "AAPL"
        assert summary["exchange_code"] == "NASD"
        assert summary["quantity"] == 2
        assert summary["current_price"] == 185.50
        assert summary["order_price"] == 185.50
        assert summary["notional"] == 371.0
        assert summary["order_type"] == "market_price"

    def test_prepare_order_success_limit(
        self, service: OneShotOverseasOrderService, kis_client: KISClient
    ) -> None:
        """지정가 주문"""
        kis_client.get_overseas_price = MagicMock(  # type: ignore[assignment]
            return_value={"last": "185.50"}
        )

        config = OneShotOverseasOrderConfig(
            ticker="AAPL",
            exchange_code="NASD",
            quantity=1,
            max_notional_usd=500.0,
            explicit_price=180.0,
        )

        summary = service.prepare_order(config)

        assert summary["order_type"] == "limit"
        assert summary["order_price"] == 180.0
        assert summary["notional"] == 180.0

    def test_prepare_order_exceeds_max_notional_raises(
        self, service: OneShotOverseasOrderService, kis_client: KISClient
    ) -> None:
        """금액 상한 초과 → InsufficientFundsError"""
        kis_client.get_overseas_price = MagicMock(  # type: ignore[assignment]
            return_value={"last": "500.00"}
        )

        config = OneShotOverseasOrderConfig(
            ticker="TSLA",
            exchange_code="NASD",
            quantity=2,
            max_notional_usd=800.0,  # 500 * 2 = 1000 > 800
        )

        with pytest.raises(InsufficientFundsError):
            service.prepare_order(config)

    def test_prepare_order_explicit_price_exceeds_max(
        self, service: OneShotOverseasOrderService, kis_client: KISClient
    ) -> None:
        """지정가 기준 금액 상한 초과"""
        kis_client.get_overseas_price = MagicMock(  # type: ignore[assignment]
            return_value={"last": "100.00"}
        )

        config = OneShotOverseasOrderConfig(
            ticker="AAPL",
            exchange_code="NASD",
            quantity=5,
            max_notional_usd=400.0,
            explicit_price=100.0,  # 100 * 5 = 500 > 400
        )

        with pytest.raises(InsufficientFundsError):
            service.prepare_order(config)

    def test_prepare_order_zero_price_raises(
        self, service: OneShotOverseasOrderService, kis_client: KISClient
    ) -> None:
        """현재가가 0인 경우 → ValidationError"""
        kis_client.get_overseas_price = MagicMock(  # type: ignore[assignment]
            return_value={"last": "0"}
        )

        config = OneShotOverseasOrderConfig(
            ticker="AAPL",
            exchange_code="NASD",
            quantity=1,
            max_notional_usd=500.0,
        )

        with pytest.raises(ValidationError, match="현재가가 0 이하"):
            service.prepare_order(config)

    def test_prepare_order_invalid_price_format_raises(
        self, service: OneShotOverseasOrderService, kis_client: KISClient
    ) -> None:
        """현재가를 숫자로 변환할 수 없는 경우"""
        kis_client.get_overseas_price = MagicMock(  # type: ignore[assignment]
            return_value={"last": "N/A"}
        )

        config = OneShotOverseasOrderConfig(
            ticker="AAPL",
            exchange_code="NASD",
            quantity=1,
            max_notional_usd=500.0,
        )

        with pytest.raises(ValidationError, match="숫자로 변환"):
            service.prepare_order(config)


class TestExecuteOrder:
    """execute_order 동작 테스트"""

    def test_execute_order_calls_client(
        self, service: OneShotOverseasOrderService, kis_client: KISClient
    ) -> None:
        """execute_order가 올바른 인자로 place_overseas_order를 호출"""
        kis_client.get_overseas_price = MagicMock(  # type: ignore[assignment]
            return_value={"last": "185.50"}
        )
        kis_client.place_overseas_order = MagicMock(  # type: ignore[assignment]
            return_value={"ODNO": "0000567890"}
        )

        config = OneShotOverseasOrderConfig(
            ticker="AAPL",
            exchange_code="NASD",
            quantity=3,
            max_notional_usd=1000.0,
        )

        result = service.execute_order(config)

        kis_client.place_overseas_order.assert_called_once_with(  # type: ignore[attr-defined]
            ticker="AAPL",
            exchange_code="NASD",
            quantity=3,
            price=185.50,
        )

        assert result["summary"]["notional"] == 185.50 * 3
        assert result["raw_result"]["ODNO"] == "0000567890"

    def test_execute_order_with_explicit_price(
        self, service: OneShotOverseasOrderService, kis_client: KISClient
    ) -> None:
        """지정가를 명시한 경우 해당 가격으로 주문"""
        kis_client.get_overseas_price = MagicMock(  # type: ignore[assignment]
            return_value={"last": "185.50"}
        )
        kis_client.place_overseas_order = MagicMock(  # type: ignore[assignment]
            return_value={"ODNO": "0000999999"}
        )

        config = OneShotOverseasOrderConfig(
            ticker="AAPL",
            exchange_code="NASD",
            quantity=1,
            max_notional_usd=500.0,
            explicit_price=180.0,
        )

        result = service.execute_order(config)

        kis_client.place_overseas_order.assert_called_once_with(  # type: ignore[attr-defined]
            ticker="AAPL",
            exchange_code="NASD",
            quantity=1,
            price=180.0,
        )

        assert result["summary"]["order_price"] == 180.0

    def test_execute_order_validation_failure_does_not_place(
        self, service: OneShotOverseasOrderService, kis_client: KISClient
    ) -> None:
        """금액 상한 초과 시 주문이 실행되지 않음"""
        kis_client.get_overseas_price = MagicMock(  # type: ignore[assignment]
            return_value={"last": "1000.00"}
        )
        kis_client.place_overseas_order = MagicMock()  # type: ignore[assignment]

        config = OneShotOverseasOrderConfig(
            ticker="AAPL",
            exchange_code="NASD",
            quantity=5,
            max_notional_usd=100.0,  # 1000 * 5 = 5000 >> 100
        )

        with pytest.raises(InsufficientFundsError):
            service.execute_order(config)

        kis_client.place_overseas_order.assert_not_called()  # type: ignore[attr-defined]

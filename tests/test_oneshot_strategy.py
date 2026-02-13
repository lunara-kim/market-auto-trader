"""OneShotOrderService 테스트

AMDL 1주 시장가 매수 같은 단일 테스트 주문을 위한
도메인 서비스에 대한 단위 테스트.

모든 외부 API 호출(KISClient)은 모킹하여 테스트합니다.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.broker.kis_client import KISClient
from src.exceptions import InsufficientFundsError, ValidationError
from src.strategy.oneshot import OneShotOrderConfig, OneShotOrderService


MOCK_APP_KEY = "test_app_key_12345"
MOCK_APP_SECRET = "test_app_secret_67890"
MOCK_ACCOUNT = "12345678-01"


@pytest.fixture
def kis_client() -> KISClient:
    """기본 KISClient 인스턴스 (HTTP 호출은 모킹 예정)"""
    client = KISClient(MOCK_APP_KEY, MOCK_APP_SECRET, MOCK_ACCOUNT)
    # 토큰은 tests/test_broker.py 와 동일하게 내부에서 _client.post 모킹으로 처리하므로
    # 여기서는 별도 설정 없이 사용
    return client


@pytest.fixture
def service(kis_client: KISClient) -> OneShotOrderService:
    return OneShotOrderService(kis_client)


class TestInit:
    """초기화 테스트"""

    def test_init_with_kis_client(self, kis_client: KISClient) -> None:
        svc = OneShotOrderService(kis_client)
        assert svc._client is kis_client

    def test_init_invalid_client_type(self) -> None:
        with pytest.raises(ValidationError, match="KISClient"):
            OneShotOrderService("not_a_client")  # type: ignore[arg-type]


class TestPrepareOrderValidation:
    """입력 유효성 검증 테스트"""

    def test_invalid_stock_code_raises(self, service: OneShotOrderService) -> None:
        config = OneShotOrderConfig(
            stock_code="12345",  # 5자리
            quantity=1,
            max_notional_krw=100_000,
        )
        with pytest.raises(ValidationError, match="종목 코드는 6자리"):
            service.prepare_order(config)

    def test_invalid_quantity_raises(self, service: OneShotOrderService) -> None:
        config = OneShotOrderConfig(
            stock_code="005930",
            quantity=0,
            max_notional_krw=100_000,
        )
        with pytest.raises(ValidationError, match="주문 수량은 1 이상"):
            service.prepare_order(config)

    def test_invalid_max_notional_raises(self, service: OneShotOrderService) -> None:
        config = OneShotOrderConfig(
            stock_code="005930",
            quantity=1,
            max_notional_krw=0,
        )
        with pytest.raises(ValidationError, match="max_notional_krw는 0보다 커야"):
            service.prepare_order(config)

    def test_invalid_explicit_price_raises(self, service: OneShotOrderService) -> None:
        config = OneShotOrderConfig(
            stock_code="005930",
            quantity=1,
            max_notional_krw=100_000,
            explicit_price=0,
        )
        with pytest.raises(ValidationError, match="지정가 가격은 0보다 커야"):
            service.prepare_order(config)


class TestPrepareOrder:
    """prepare_order 동작 테스트"""

    def test_prepare_order_success_market(self, service: OneShotOrderService, kis_client: KISClient) -> None:
        # 현재가 10,000원, 2주 → 20,000원
        kis_client.get_price = MagicMock(return_value={"stck_prpr": "10000"})  # type: ignore[assignment]

        config = OneShotOrderConfig(
            stock_code="005930",
            quantity=2,
            max_notional_krw=50_000,
        )

        summary = service.prepare_order(config)

        assert summary["stock_code"] == "005930"
        assert summary["quantity"] == 2
        assert summary["current_price"] == 10_000
        assert summary["notional"] == 20_000
        assert summary["order_type"] == "market"
        assert summary["limit_price"] is None

    def test_prepare_order_success_limit(self, service: OneShotOrderService, kis_client: KISClient) -> None:
        kis_client.get_price = MagicMock(return_value={"stck_prpr": "10000"})  # type: ignore[assignment]

        config = OneShotOrderConfig(
            stock_code="005930",
            quantity=1,
            max_notional_krw=100_000,
            explicit_price=9_500,
        )

        summary = service.prepare_order(config)

        assert summary["order_type"] == "limit"
        assert summary["limit_price"] == 9_500

    def test_prepare_order_exceeds_max_notional_raises(self, service: OneShotOrderService, kis_client: KISClient) -> None:
        kis_client.get_price = MagicMock(return_value={"stck_prpr": "100000"})  # type: ignore[assignment]

        config = OneShotOrderConfig(
            stock_code="005930",
            quantity=2,
            max_notional_krw=150_000,
        )

        with pytest.raises(InsufficientFundsError):
            service.prepare_order(config)


class TestExecuteOrder:
    """execute_order 동작 테스트"""

    def test_execute_order_calls_client_with_expected_args(
        self, service: OneShotOrderService, kis_client: KISClient
    ) -> None:
        # prepare_order 단계에서 사용할 현재가
        kis_client.get_price = MagicMock(return_value={"stck_prpr": "10000"})  # type: ignore[assignment]
        # place_order mock
        kis_client.place_order = MagicMock(return_value={"ODNO": "0000123456"})  # type: ignore[assignment]

        config = OneShotOrderConfig(
            stock_code="123456",
            quantity=3,
            max_notional_krw=100_000,
        )

        result = service.execute_order(config)

        kis_client.place_order.assert_called_once_with(  # type: ignore[attr-defined]
            stock_code="123456",
            order_type="buy",
            quantity=3,
            price=None,
        )

        assert result["summary"]["notional"] == 30_000
        assert result["raw_result"]["ODNO"] == "0000123456"

"""OneShotSellService 및 매도 엔드포인트 테스트

국내 주식 원샷 매도 서비스에 대한 단위 테스트 및 API 테스트.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.broker.kis_client import KISClient
from src.exceptions import InsufficientFundsError, ValidationError
from src.strategy.oneshot import OneShotSellConfig, OneShotSellService


MOCK_APP_KEY = "test_app_key_12345"
MOCK_APP_SECRET = "test_app_secret_67890"
MOCK_ACCOUNT = "12345678-01"


@pytest.fixture
def kis_client() -> KISClient:
    return KISClient(MOCK_APP_KEY, MOCK_APP_SECRET, MOCK_ACCOUNT)


@pytest.fixture
def sell_service(kis_client: KISClient) -> OneShotSellService:
    return OneShotSellService(kis_client)


# ───────────────────── Service Tests ─────────────────────


class TestOneShotSellServiceInit:
    def test_init_with_kis_client(self, kis_client: KISClient) -> None:
        svc = OneShotSellService(kis_client)
        assert svc._client is kis_client

    def test_init_invalid_client_type(self) -> None:
        with pytest.raises(ValidationError, match="KISClient"):
            OneShotSellService("not_a_client")  # type: ignore[arg-type]


class TestPrepareSell:
    def test_prepare_sell_success(self, sell_service: OneShotSellService) -> None:
        with patch.object(
            sell_service._client, "get_price", return_value={"stck_prpr": "50000"}
        ):
            result = sell_service.prepare_sell(
                OneShotSellConfig(
                    stock_code="005930",
                    quantity=10,
                    max_notional_krw=1_000_000,
                )
            )
        assert result["stock_code"] == "005930"
        assert result["quantity"] == 10
        assert result["current_price"] == 50000
        assert result["notional"] == 500000
        assert result["order_type"] == "market"

    def test_prepare_sell_limit_order(self, sell_service: OneShotSellService) -> None:
        with patch.object(
            sell_service._client, "get_price", return_value={"stck_prpr": "50000"}
        ):
            result = sell_service.prepare_sell(
                OneShotSellConfig(
                    stock_code="005930",
                    quantity=10,
                    max_notional_krw=1_000_000,
                    explicit_price=55000,
                )
            )
        assert result["order_type"] == "limit"
        assert result["limit_price"] == 55000

    def test_prepare_sell_exceeds_max_notional(self, sell_service: OneShotSellService) -> None:
        with patch.object(
            sell_service._client, "get_price", return_value={"stck_prpr": "50000"}
        ):
            with pytest.raises(InsufficientFundsError, match="상한을 초과"):
                sell_service.prepare_sell(
                    OneShotSellConfig(
                        stock_code="005930",
                        quantity=100,
                        max_notional_krw=100_000,
                    )
                )

    def test_prepare_sell_invalid_stock_code(self, sell_service: OneShotSellService) -> None:
        with pytest.raises(ValidationError, match="6자리 숫자"):
            sell_service.prepare_sell(
                OneShotSellConfig(
                    stock_code="ABC",
                    quantity=1,
                    max_notional_krw=1_000_000,
                )
            )

    def test_prepare_sell_invalid_quantity(self, sell_service: OneShotSellService) -> None:
        with pytest.raises(ValidationError, match="수량은 1 이상"):
            sell_service.prepare_sell(
                OneShotSellConfig(
                    stock_code="005930",
                    quantity=0,
                    max_notional_krw=1_000_000,
                )
            )

    def test_prepare_sell_invalid_max_notional(self, sell_service: OneShotSellService) -> None:
        with pytest.raises(ValidationError, match="max_notional_krw는 0보다"):
            sell_service.prepare_sell(
                OneShotSellConfig(
                    stock_code="005930",
                    quantity=1,
                    max_notional_krw=0,
                )
            )

    def test_prepare_sell_invalid_explicit_price(self, sell_service: OneShotSellService) -> None:
        with pytest.raises(ValidationError, match="지정가 가격은 0보다"):
            sell_service.prepare_sell(
                OneShotSellConfig(
                    stock_code="005930",
                    quantity=1,
                    max_notional_krw=1_000_000,
                    explicit_price=-100,
                )
            )


class TestExecuteSell:
    def test_execute_sell_success(self, sell_service: OneShotSellService) -> None:
        with (
            patch.object(
                sell_service._client,
                "get_price",
                return_value={"stck_prpr": "50000"},
            ),
            patch.object(
                sell_service._client,
                "place_order",
                return_value={"ODNO": "1234567890", "msg1": "정상처리"},
            ) as mock_place,
        ):
            result = sell_service.execute_sell(
                OneShotSellConfig(
                    stock_code="005930",
                    quantity=10,
                    max_notional_krw=1_000_000,
                )
            )

        assert result["summary"]["stock_code"] == "005930"
        assert result["raw_result"]["ODNO"] == "1234567890"
        mock_place.assert_called_once_with(
            stock_code="005930",
            order_type="sell",
            quantity=10,
            price=None,
        )

    def test_execute_sell_with_limit_price(self, sell_service: OneShotSellService) -> None:
        with (
            patch.object(
                sell_service._client,
                "get_price",
                return_value={"stck_prpr": "50000"},
            ),
            patch.object(
                sell_service._client,
                "place_order",
                return_value={"ODNO": "9999999999"},
            ) as mock_place,
        ):
            sell_service.execute_sell(
                OneShotSellConfig(
                    stock_code="005930",
                    quantity=5,
                    max_notional_krw=1_000_000,
                    explicit_price=55000,
                )
            )

        mock_place.assert_called_once_with(
            stock_code="005930",
            order_type="sell",
            quantity=5,
            price=55000,
        )


# ───────────────────── API Endpoint Tests ─────────────────────


@pytest.fixture
def api_client():
    from src.main import app

    return TestClient(app)


class TestOneShotSellEndpoint:
    ENDPOINT = "/api/v1/policies/oneshot/sell"

    def test_dry_run_success(self, api_client: TestClient) -> None:
        with patch(
            "src.api.policies._create_kis_client_from_settings"
        ) as mock_factory:
            mock_kis = MagicMock(spec=KISClient)
            mock_kis.get_price.return_value = {"stck_prpr": "50000"}
            mock_kis.__enter__ = MagicMock(return_value=mock_kis)
            mock_kis.__exit__ = MagicMock(return_value=False)
            mock_factory.return_value = mock_kis

            resp = api_client.post(
                self.ENDPOINT,
                json={
                    "stock_code": "005930",
                    "quantity": 10,
                    "max_notional_krw": 1_000_000,
                    "dry_run": True,
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["stock_code"] == "005930"
        assert data["raw_result"] is None
        mock_kis.place_order.assert_not_called()

    def test_execute_sell_success(self, api_client: TestClient) -> None:
        with patch(
            "src.api.policies._create_kis_client_from_settings"
        ) as mock_factory:
            mock_kis = MagicMock(spec=KISClient)
            mock_kis.get_price.return_value = {"stck_prpr": "50000"}
            mock_kis.place_order.return_value = {"ODNO": "1234567890"}
            mock_kis.__enter__ = MagicMock(return_value=mock_kis)
            mock_kis.__exit__ = MagicMock(return_value=False)
            mock_factory.return_value = mock_kis

            resp = api_client.post(
                self.ENDPOINT,
                json={
                    "stock_code": "005930",
                    "quantity": 10,
                    "max_notional_krw": 1_000_000,
                    "dry_run": False,
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["raw_result"]["ODNO"] == "1234567890"
        mock_kis.place_order.assert_called_once()

    def test_validation_error(self, api_client: TestClient) -> None:
        resp = api_client.post(
            self.ENDPOINT,
            json={
                "stock_code": "00",  # too short
                "quantity": 10,
                "max_notional_krw": 1_000_000,
            },
        )
        assert resp.status_code == 422

    def test_exceeds_max_notional(self, api_client: TestClient) -> None:
        with patch(
            "src.api.policies._create_kis_client_from_settings"
        ) as mock_factory:
            mock_kis = MagicMock(spec=KISClient)
            mock_kis.get_price.return_value = {"stck_prpr": "50000"}
            mock_kis.__enter__ = MagicMock(return_value=mock_kis)
            mock_kis.__exit__ = MagicMock(return_value=False)
            mock_factory.return_value = mock_kis

            resp = api_client.post(
                self.ENDPOINT,
                json={
                    "stock_code": "005930",
                    "quantity": 100,
                    "max_notional_krw": 100_000,
                    "dry_run": True,
                },
            )

        assert resp.status_code == 400

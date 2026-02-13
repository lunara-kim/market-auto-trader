"""해외주식 원샷 매매 정책 엔드포인트 테스트"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from config.settings import settings
from src.broker.kis_client import KISClient
from src.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_kis_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """테스트용 KIS 설정 주입"""
    monkeypatch.setattr(settings, "kis_app_key", "test_app_key")
    monkeypatch.setattr(settings, "kis_app_secret", "test_app_secret")
    monkeypatch.setattr(settings, "kis_account_no", "12345678-01")
    monkeypatch.setattr(settings, "kis_mock", True)


def _patch_kis_init(monkeypatch: pytest.MonkeyPatch) -> None:
    """KISClient.__init__ 을 모킹하여 실제 네트워크 호출 방지"""

    def _mock_init(self: KISClient, *args, **kwargs) -> None:  # type: ignore[override]
        self.app_key = "dummy"
        self.app_secret = "dummy"
        self.mock = True
        self.cano = "12345678"
        self.acnt_prdt_cd = "01"
        self._client = MagicMock()

    monkeypatch.setattr("src.broker.kis_client.KISClient.__init__", _mock_init)


def test_overseas_oneshot_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """dry_run=True일 때 실제 주문이 호출되지 않고 summary만 반환"""
    _patch_kis_init(monkeypatch)

    monkeypatch.setattr(
        "src.broker.kis_client.KISClient.get_overseas_price",
        MagicMock(return_value={"last": "185.50"}),
    )
    place_order_mock = MagicMock(return_value={"ODNO": "0000567890"})
    monkeypatch.setattr(
        "src.broker.kis_client.KISClient.place_overseas_order",
        place_order_mock,
    )

    payload = {
        "ticker": "AAPL",
        "exchange_code": "NASD",
        "quantity": 1,
        "max_notional_usd": 500.0,
        "explicit_price": None,
        "dry_run": True,
    }

    response = client.post("/api/v1/policies/oneshot/overseas", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert "summary" in data
    assert data["summary"]["ticker"] == "AAPL"
    assert data["summary"]["exchange_code"] == "NASD"
    assert data["summary"]["current_price"] == 185.50
    assert data["summary"]["notional"] == 185.50
    assert data["raw_result"] is None

    # dry_run이므로 실제 주문은 호출되지 않아야 함
    place_order_mock.assert_not_called()


def test_overseas_oneshot_live_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """dry_run=False일 때 place_overseas_order가 호출되고 raw_result 포함"""
    _patch_kis_init(monkeypatch)

    monkeypatch.setattr(
        "src.broker.kis_client.KISClient.get_overseas_price",
        MagicMock(return_value={"last": "250.00"}),
    )
    place_order_mock = MagicMock(return_value={"ODNO": "0000999999"})
    monkeypatch.setattr(
        "src.broker.kis_client.KISClient.place_overseas_order",
        place_order_mock,
    )

    payload = {
        "ticker": "TSLA",
        "exchange_code": "NASD",
        "quantity": 2,
        "max_notional_usd": 600.0,
        "explicit_price": None,
        "dry_run": False,
    }

    response = client.post("/api/v1/policies/oneshot/overseas", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert data["summary"]["notional"] == 500.0
    assert data["raw_result"]["ODNO"] == "0000999999"

    place_order_mock.assert_called_once_with(
        ticker="TSLA",
        exchange_code="NASD",
        quantity=2,
        price=250.0,
    )


def test_overseas_oneshot_with_explicit_price(monkeypatch: pytest.MonkeyPatch) -> None:
    """explicit_price 지정 시 해당 가격으로 주문"""
    _patch_kis_init(monkeypatch)

    monkeypatch.setattr(
        "src.broker.kis_client.KISClient.get_overseas_price",
        MagicMock(return_value={"last": "185.50"}),
    )
    place_order_mock = MagicMock(return_value={"ODNO": "0000111111"})
    monkeypatch.setattr(
        "src.broker.kis_client.KISClient.place_overseas_order",
        place_order_mock,
    )

    payload = {
        "ticker": "AAPL",
        "exchange_code": "NYSE",
        "quantity": 1,
        "max_notional_usd": 500.0,
        "explicit_price": 180.0,
        "dry_run": False,
    }

    response = client.post("/api/v1/policies/oneshot/overseas", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert data["summary"]["order_price"] == 180.0
    assert data["summary"]["order_type"] == "limit"

    place_order_mock.assert_called_once_with(
        ticker="AAPL",
        exchange_code="NYSE",
        quantity=1,
        price=180.0,
    )


def test_overseas_oneshot_insufficient_funds(monkeypatch: pytest.MonkeyPatch) -> None:
    """max_notional_usd 초과 시 400 + INSUFFICIENT_FUNDS 응답"""
    _patch_kis_init(monkeypatch)

    # 현재가 $500, 수량 2 → $1000, 상한 $800 → 초과
    monkeypatch.setattr(
        "src.broker.kis_client.KISClient.get_overseas_price",
        MagicMock(return_value={"last": "500.00"}),
    )

    payload = {
        "ticker": "TSLA",
        "exchange_code": "NASD",
        "quantity": 2,
        "max_notional_usd": 800.0,
        "explicit_price": None,
        "dry_run": False,
    }

    response = client.post("/api/v1/policies/oneshot/overseas", json=payload)
    assert response.status_code == 400

    data = response.json()
    assert data["error"]["code"] == "INSUFFICIENT_FUNDS"
    assert "detail" in data["error"]


def test_overseas_oneshot_default_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """dry_run 미지정 시 기본값 True (안전 모드)"""
    _patch_kis_init(monkeypatch)

    monkeypatch.setattr(
        "src.broker.kis_client.KISClient.get_overseas_price",
        MagicMock(return_value={"last": "100.00"}),
    )
    place_order_mock = MagicMock(return_value={"ODNO": "test"})
    monkeypatch.setattr(
        "src.broker.kis_client.KISClient.place_overseas_order",
        place_order_mock,
    )

    payload = {
        "ticker": "AMZN",
        "exchange_code": "NASD",
        "quantity": 1,
        "max_notional_usd": 500.0,
        # dry_run 미지정 → True
    }

    response = client.post("/api/v1/policies/oneshot/overseas", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["raw_result"] is None  # dry_run이므로 주문 미실행
    place_order_mock.assert_not_called()


def test_overseas_oneshot_invalid_exchange_code(monkeypatch: pytest.MonkeyPatch) -> None:
    """잘못된 거래소 코드 → 422 (validation)"""
    _patch_kis_init(monkeypatch)

    monkeypatch.setattr(
        "src.broker.kis_client.KISClient.get_overseas_price",
        MagicMock(return_value={"last": "100.00"}),
    )

    payload = {
        "ticker": "AAPL",
        "exchange_code": "KOSPI",  # 잘못된 코드
        "quantity": 1,
        "max_notional_usd": 500.0,
    }

    response = client.post("/api/v1/policies/oneshot/overseas", json=payload)
    # 서비스 레벨 ValidationError → 422
    assert response.status_code == 422

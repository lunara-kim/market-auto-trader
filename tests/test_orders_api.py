"""원샷 매매 정책 엔드포인트 테스트"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from config.settings import settings
from src.broker.kis_client import KISClient
from src.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_kis_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """테스트용 KIS 설정 주입

    실제 키가 없어도 클라이언트 생성이 가능하도록 더미 값을 설정한다.
    """

    monkeypatch.setattr(settings, "kis_app_key", "test_app_key")
    monkeypatch.setattr(settings, "kis_app_secret", "test_app_secret")
    monkeypatch.setattr(settings, "kis_account_no", "12345678-01")
    monkeypatch.setattr(settings, "kis_mock", True)


def test_oneshot_policy_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """dry_run=True일 때 실제 주문이 호출되지 않고 summary만 반환되는지 테스트"""

    # KISClient.get_price / place_order 모킹
    def _mock_init(self: KISClient, *args, **kwargs) -> None:  # type: ignore[override]
        # 실제 초기화는 건너뜀 (네트워크/토큰 발급 방지)
        self.app_key = "dummy"
        self.app_secret = "dummy"
        self.mock = True
        self.cano = "12345678"
        self.acnt_prdt_cd = "01"
        self._client = MagicMock()

    monkeypatch.setattr("src.broker.kis_client.KISClient.__init__", _mock_init)

    monkeypatch.setattr(
        "src.broker.kis_client.KISClient.get_price",
        MagicMock(return_value={"stck_prpr": "10000"}),
    )
    place_order_mock = MagicMock(return_value={"ODNO": "0000123456"})
    monkeypatch.setattr("src.broker.kis_client.KISClient.place_order", place_order_mock)

    payload = {
        "stock_code": "123456",
        "quantity": 1,
        "max_notional_krw": 150_000,
        "explicit_price": None,
        "dry_run": True,
    }

    response = client.post("/api/v1/policies/oneshot", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert "summary" in data
    assert data["summary"]["stock_code"] == "123456"
    assert data["summary"]["notional"] == 10_000
    assert data["raw_result"] is None

    # dry_run이므로 실제 주문은 호출되지 않아야 함
    place_order_mock.assert_not_called()


def test_oneshot_policy_live_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """dry_run=False일 때 place_order가 호출되고 raw_result가 포함되는지 테스트"""

    def _mock_init(self: KISClient, *args, **kwargs) -> None:  # type: ignore[override]
        self.app_key = "dummy"
        self.app_secret = "dummy"
        self.mock = True
        self.cano = "12345678"
        self.acnt_prdt_cd = "01"
        self._client = MagicMock()

    monkeypatch.setattr("src.broker.kis_client.KISClient.__init__", _mock_init)

    monkeypatch.setattr(
        "src.broker.kis_client.KISClient.get_price",
        MagicMock(return_value={"stck_prpr": "20000"}),
    )
    place_order_mock = MagicMock(return_value={"ODNO": "0000987654"})
    monkeypatch.setattr("src.broker.kis_client.KISClient.place_order", place_order_mock)

    payload = {
        "stock_code": "654321",
        "quantity": 2,
        "max_notional_krw": 50_000,
        "explicit_price": None,
        "dry_run": False,
    }

    response = client.post("/api/v1/policies/oneshot", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert data["summary"]["notional"] == 40_000
    assert data["raw_result"]["ODNO"] == "0000987654"

    place_order_mock.assert_called_once_with(
        stock_code="654321",
        order_type="buy",
        quantity=2,
        price=None,
    )


def test_oneshot_policy_insufficient_funds(monkeypatch: pytest.MonkeyPatch) -> None:
    """max_notional_krw를 초과하면 400 + ORDER_ERROR 형식으로 응답해야 한다"""

    def _mock_init(self: KISClient, *args, **kwargs) -> None:  # type: ignore[override]
        self.app_key = "dummy"
        self.app_secret = "dummy"
        self.mock = True
        self.cano = "12345678"
        self.acnt_prdt_cd = "01"
        self._client = MagicMock()

    monkeypatch.setattr("src.broker.kis_client.KISClient.__init__", _mock_init)

    # 현재가 100,000원, 수량 2 → 200,000원, 상한 150,000원 초과
    monkeypatch.setattr(
        "src.broker.kis_client.KISClient.get_price",
        MagicMock(return_value={"stck_prpr": "100000"}),
    )

    payload = {
        "stock_code": "111111",
        "quantity": 2,
        "max_notional_krw": 150_000,
        "explicit_price": None,
        "dry_run": False,
    }

    response = client.post("/api/v1/policies/oneshot", json=payload)
    assert response.status_code == 400

    data = response.json()
    assert data["error"]["code"] == "INSUFFICIENT_FUNDS"
    assert "detail" in data["error"]

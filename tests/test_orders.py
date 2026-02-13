"""
주문 API 테스트

KISClient와 DB 세션을 모킹하여 주문 엔드포인트를 검증합니다.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.api.dependencies import get_db, get_kis_client
from src.api.schemas import OrderRequest, OrderType
from src.main import app


def _mock_kis_client(order_result: dict | None = None) -> MagicMock:
    """KISClient 모킹"""
    mock = MagicMock()
    mock.place_order.return_value = order_result or {
        "ODNO": "0012345678",
        "ORD_TMD": "141500",
        "KRX_FWDG_ORD_ORGNO": "91234",
    }
    mock.close.return_value = None
    return mock


class FakeDBSession:
    """가짜 DB 세션 (add/commit/rollback만 지원)"""

    def __init__(self) -> None:
        self.added: list = []

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass

    async def execute(self, stmt):
        """빈 결과 반환"""

        class FakeResult:
            def scalars(self):
                return self

            def all(self):
                return []

            def scalar(self):
                return 0

        return FakeResult()


# ─────────────────────────────────────────────
# OrderRequest 스키마 검증
# ─────────────────────────────────────────────

class TestOrderRequest:
    """OrderRequest 입력 검증"""

    def test_valid_buy_market(self) -> None:
        req = OrderRequest(
            stock_code="005930",
            order_type=OrderType.BUY,
            quantity=10,
        )
        assert req.price is None

    def test_valid_sell_limit(self) -> None:
        req = OrderRequest(
            stock_code="035720",
            order_type=OrderType.SELL,
            quantity=5,
            price=50000,
        )
        assert req.price == 50000

    def test_invalid_stock_code_length(self) -> None:
        with pytest.raises(Exception):
            OrderRequest(
                stock_code="12345",  # 5자리
                order_type=OrderType.BUY,
                quantity=1,
            )

    def test_invalid_stock_code_non_digit(self) -> None:
        with pytest.raises(Exception):
            OrderRequest(
                stock_code="ABCDEF",  # 숫자가 아님
                order_type=OrderType.BUY,
                quantity=1,
            )

    def test_zero_quantity_rejected(self) -> None:
        with pytest.raises(Exception):
            OrderRequest(
                stock_code="005930",
                order_type=OrderType.BUY,
                quantity=0,
            )

    def test_negative_price_rejected(self) -> None:
        with pytest.raises(Exception):
            OrderRequest(
                stock_code="005930",
                order_type=OrderType.BUY,
                quantity=1,
                price=-100,
            )


# ─────────────────────────────────────────────
# POST /api/v1/orders 테스트
# ─────────────────────────────────────────────

class TestPlaceOrder:
    """POST /api/v1/orders 테스트"""

    def setup_method(self) -> None:
        self.client = TestClient(app)
        self.fake_db = FakeDBSession()

    def _override_deps(self, mock_client: MagicMock) -> None:
        app.dependency_overrides[get_kis_client] = lambda: mock_client
        app.dependency_overrides[get_db] = self._get_fake_db

    async def _get_fake_db(self):
        yield self.fake_db

    def teardown_method(self) -> None:
        app.dependency_overrides.clear()

    def test_buy_market_order(self) -> None:
        """시장가 매수 주문"""
        mock = _mock_kis_client()
        self._override_deps(mock)

        resp = self.client.post("/api/v1/orders", json={
            "stock_code": "005930",
            "order_type": "buy",
            "quantity": 10,
        })
        assert resp.status_code == 200

        data = resp.json()
        assert data["order_id"] == "0012345678"
        assert data["stock_code"] == "005930"
        assert data["order_type"] == "buy"
        assert data["quantity"] == 10
        assert data["price"] == "시장가"
        assert data["status"] == "executed"

        # KISClient가 올바른 인자로 호출됐는지
        mock.place_order.assert_called_once_with(
            stock_code="005930",
            order_type="buy",
            quantity=10,
            price=None,
        )

        # DB에 기록됐는지
        assert len(self.fake_db.added) == 1

    def test_sell_limit_order(self) -> None:
        """지정가 매도 주문"""
        mock = _mock_kis_client({
            "ODNO": "0098765432",
            "ORD_TMD": "100500",
        })
        self._override_deps(mock)

        resp = self.client.post("/api/v1/orders", json={
            "stock_code": "035720",
            "order_type": "sell",
            "quantity": 5,
            "price": 48000,
        })
        assert resp.status_code == 200

        data = resp.json()
        assert data["order_id"] == "0098765432"
        assert data["order_type"] == "sell"
        assert data["price"] == "48000"

        mock.place_order.assert_called_once_with(
            stock_code="035720",
            order_type="sell",
            quantity=5,
            price=48000,
        )

    def test_invalid_stock_code_rejected(self) -> None:
        """잘못된 종목코드 → 422"""
        mock = _mock_kis_client()
        self._override_deps(mock)

        resp = self.client.post("/api/v1/orders", json={
            "stock_code": "123",
            "order_type": "buy",
            "quantity": 10,
        })
        assert resp.status_code == 422

    def test_invalid_order_type_rejected(self) -> None:
        """잘못된 주문유형 → 422"""
        mock = _mock_kis_client()
        self._override_deps(mock)

        resp = self.client.post("/api/v1/orders", json={
            "stock_code": "005930",
            "order_type": "short",
            "quantity": 10,
        })
        assert resp.status_code == 422


# ─────────────────────────────────────────────
# GET /api/v1/orders 테스트
# ─────────────────────────────────────────────

class TestGetOrders:
    """GET /api/v1/orders 테스트"""

    def setup_method(self) -> None:
        self.client = TestClient(app)
        self.fake_db = FakeDBSession()

    def _override_db(self) -> None:
        async def _get_fake_db():
            yield self.fake_db

        app.dependency_overrides[get_db] = _get_fake_db

    def teardown_method(self) -> None:
        app.dependency_overrides.clear()

    def test_empty_orders(self) -> None:
        """주문 내역 없을 때"""
        self._override_db()

        resp = self.client.get("/api/v1/orders")
        assert resp.status_code == 200

        data = resp.json()
        assert data["orders"] == []
        assert data["total"] == 0
        assert data["page"] == 1
        assert data["size"] == 20

    def test_with_filters(self) -> None:
        """필터 파라미터 전달"""
        self._override_db()

        resp = self.client.get(
            "/api/v1/orders",
            params={"stock_code": "005930", "order_type": "buy", "page": 2, "size": 10},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 2
        assert data["size"] == 10

    def test_invalid_page_rejected(self) -> None:
        """page < 1 → 422"""
        self._override_db()

        resp = self.client.get("/api/v1/orders", params={"page": 0})
        assert resp.status_code == 422

    def test_oversized_page_rejected(self) -> None:
        """size > 100 → 422"""
        self._override_db()

        resp = self.client.get("/api/v1/orders", params={"size": 999})
        assert resp.status_code == 422

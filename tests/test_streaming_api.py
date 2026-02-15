"""
실시간 시세 스트리밍 WebSocket API 엔드포인트 테스트

WebSocket 연결, 구독/해제 메시지, 시세 브로드캐스트를 검증합니다.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from src.api.streaming import StreamingConnectionManager
from src.main import app
from src.streaming.websocket_client import PriceData


# ─────────────────── StreamingConnectionManager ─────────────────────


class TestStreamingConnectionManager:
    """StreamingConnectionManager 유닛 테스트"""

    @pytest.fixture
    def mgr(self) -> StreamingConnectionManager:
        """테스트용 매니저"""
        return StreamingConnectionManager()

    @pytest.fixture
    def mock_ws(self) -> AsyncMock:
        """모킹된 WebSocket"""
        ws = AsyncMock()
        ws.accept = AsyncMock()
        ws.send_text = AsyncMock()
        ws.receive_text = AsyncMock()
        return ws

    @pytest.mark.asyncio
    async def test_connect(self, mgr: StreamingConnectionManager, mock_ws: AsyncMock) -> None:
        """클라이언트 연결"""
        client_id = await mgr.connect(mock_ws)

        assert client_id > 0
        assert mgr.client_count == 1
        mock_ws.accept.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disconnect(self, mgr: StreamingConnectionManager, mock_ws: AsyncMock) -> None:
        """클라이언트 연결 해제"""
        client_id = await mgr.connect(mock_ws)
        mgr.disconnect(client_id)

        assert mgr.client_count == 0

    @pytest.mark.asyncio
    async def test_subscribe(self, mgr: StreamingConnectionManager, mock_ws: AsyncMock) -> None:
        """종목 구독"""
        client_id = await mgr.connect(mock_ws)
        await mgr.subscribe(client_id, ["005930", "000660"])

        subs = mgr.get_client_subscriptions(client_id)
        assert "005930" in subs
        assert "000660" in subs
        assert mgr.get_stock_subscriber_count("005930") == 1

    @pytest.mark.asyncio
    async def test_unsubscribe(self, mgr: StreamingConnectionManager, mock_ws: AsyncMock) -> None:
        """종목 구독 해제"""
        client_id = await mgr.connect(mock_ws)
        await mgr.subscribe(client_id, ["005930", "000660"])
        await mgr.unsubscribe(client_id, ["005930"])

        subs = mgr.get_client_subscriptions(client_id)
        assert "005930" not in subs
        assert "000660" in subs
        assert mgr.get_stock_subscriber_count("005930") == 0

    @pytest.mark.asyncio
    async def test_shared_subscription(self, mgr: StreamingConnectionManager) -> None:
        """여러 클라이언트가 같은 종목 구독"""
        ws1 = AsyncMock()
        ws1.accept = AsyncMock()
        ws2 = AsyncMock()
        ws2.accept = AsyncMock()

        client1 = await mgr.connect(ws1)
        client2 = await mgr.connect(ws2)

        await mgr.subscribe(client1, ["005930"])
        await mgr.subscribe(client2, ["005930"])

        assert mgr.get_stock_subscriber_count("005930") == 2

    @pytest.mark.asyncio
    async def test_broadcast_price(self, mgr: StreamingConnectionManager) -> None:
        """체결가 브로드캐스트"""
        ws1 = AsyncMock()
        ws1.accept = AsyncMock()
        ws1.send_text = AsyncMock()
        ws2 = AsyncMock()
        ws2.accept = AsyncMock()
        ws2.send_text = AsyncMock()

        client1 = await mgr.connect(ws1)
        client2 = await mgr.connect(ws2)

        await mgr.subscribe(client1, ["005930"])
        await mgr.subscribe(client2, ["005930"])

        price_data = PriceData(
            stock_code="005930",
            current_price=72000.0,
            change=-500.0,
            change_rate=-0.69,
            volume=1000,
            trade_time="153000",
        )

        await mgr.broadcast_price(price_data)

        assert ws1.send_text.await_count == 1
        assert ws2.send_text.await_count == 1

        # 전송된 데이터 검증
        sent = json.loads(ws1.send_text.call_args[0][0])
        assert sent["type"] == "price_update"
        assert sent["data"]["stock_code"] == "005930"
        assert sent["data"]["current_price"] == 72000.0

    @pytest.mark.asyncio
    async def test_broadcast_only_to_subscribers(
        self, mgr: StreamingConnectionManager,
    ) -> None:
        """구독한 클라이언트에게만 브로드캐스트"""
        ws1 = AsyncMock()
        ws1.accept = AsyncMock()
        ws1.send_text = AsyncMock()
        ws2 = AsyncMock()
        ws2.accept = AsyncMock()
        ws2.send_text = AsyncMock()

        client1 = await mgr.connect(ws1)
        client2 = await mgr.connect(ws2)

        await mgr.subscribe(client1, ["005930"])
        await mgr.subscribe(client2, ["000660"])

        price_data = PriceData(
            stock_code="005930",
            current_price=72000.0,
            change=0,
            change_rate=0,
            volume=100,
            trade_time="100000",
        )

        await mgr.broadcast_price(price_data)

        ws1.send_text.assert_awaited_once()
        ws2.send_text.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_broadcast_disconnects_failed_client(
        self, mgr: StreamingConnectionManager,
    ) -> None:
        """전송 실패 시 클라이언트 제거"""
        ws = AsyncMock()
        ws.accept = AsyncMock()
        ws.send_text = AsyncMock(side_effect=RuntimeError("연결 끊김"))

        client_id = await mgr.connect(ws)
        await mgr.subscribe(client_id, ["005930"])

        price_data = PriceData(
            stock_code="005930",
            current_price=72000.0,
            change=0,
            change_rate=0,
            volume=100,
            trade_time="100000",
        )

        await mgr.broadcast_price(price_data)

        assert mgr.client_count == 0

    @pytest.mark.asyncio
    async def test_disconnect_cleans_subscriptions(
        self, mgr: StreamingConnectionManager, mock_ws: AsyncMock,
    ) -> None:
        """연결 해제 시 구독 정리"""
        client_id = await mgr.connect(mock_ws)
        await mgr.subscribe(client_id, ["005930", "000660"])

        mgr.disconnect(client_id)

        assert mgr.get_stock_subscriber_count("005930") == 0
        assert mgr.get_stock_subscriber_count("000660") == 0

    def test_get_subscriptions_unknown_client(
        self, mgr: StreamingConnectionManager,
    ) -> None:
        """존재하지 않는 클라이언트 구독 조회"""
        subs = mgr.get_client_subscriptions(99999)
        assert subs == set()

    @pytest.mark.asyncio
    async def test_broadcast_no_subscribers(
        self, mgr: StreamingConnectionManager,
    ) -> None:
        """구독자 없는 종목 브로드캐스트"""
        price_data = PriceData(
            stock_code="999999",
            current_price=10000.0,
            change=0,
            change_rate=0,
            volume=0,
            trade_time="100000",
        )
        # 에러 없이 통과
        await mgr.broadcast_price(price_data)


# ─────────────────── WebSocket Endpoint ─────────────────────


class TestWebSocketEndpoint:
    """WebSocket 엔드포인트 통합 테스트"""

    def test_subscribe_flow(self) -> None:
        """구독 흐름 테스트"""
        client = TestClient(app)

        with client.websocket_connect("/api/v1/ws/prices") as ws:
            # 구독 메시지 전송
            ws.send_text(json.dumps({
                "action": "subscribe",
                "stock_codes": ["005930", "000660"],
            }))

            # 응답 확인
            resp = json.loads(ws.receive_text())
            assert resp["type"] == "subscribed"
            assert "005930" in resp["stock_codes"]
            assert "000660" in resp["stock_codes"]

    def test_unsubscribe_flow(self) -> None:
        """구독 해제 흐름 테스트"""
        client = TestClient(app)

        with client.websocket_connect("/api/v1/ws/prices") as ws:
            # 먼저 구독
            ws.send_text(json.dumps({
                "action": "subscribe",
                "stock_codes": ["005930"],
            }))
            ws.receive_text()

            # 구독 해제
            ws.send_text(json.dumps({
                "action": "unsubscribe",
                "stock_codes": ["005930"],
            }))

            resp = json.loads(ws.receive_text())
            assert resp["type"] == "unsubscribed"
            assert "005930" in resp["stock_codes"]

    def test_invalid_json(self) -> None:
        """잘못된 JSON 전송"""
        client = TestClient(app)

        with client.websocket_connect("/api/v1/ws/prices") as ws:
            ws.send_text("not json")
            resp = json.loads(ws.receive_text())
            assert resp["type"] == "error"
            assert "JSON" in resp["message"]

    def test_unknown_action(self) -> None:
        """알 수 없는 action"""
        client = TestClient(app)

        with client.websocket_connect("/api/v1/ws/prices") as ws:
            ws.send_text(json.dumps({
                "action": "unknown",
                "stock_codes": [],
            }))
            resp = json.loads(ws.receive_text())
            assert resp["type"] == "error"
            assert "알 수 없는" in resp["message"]

    def test_invalid_stock_codes_type(self) -> None:
        """stock_codes가 리스트가 아닌 경우"""
        client = TestClient(app)

        with client.websocket_connect("/api/v1/ws/prices") as ws:
            ws.send_text(json.dumps({
                "action": "subscribe",
                "stock_codes": "005930",  # 리스트가 아님
            }))
            resp = json.loads(ws.receive_text())
            assert resp["type"] == "error"
            assert "리스트" in resp["message"]

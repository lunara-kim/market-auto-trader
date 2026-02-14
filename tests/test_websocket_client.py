"""
KIS WebSocket 클라이언트 유닛 테스트

연결/해제, 구독/해제, 메시지 파싱, 에러 핸들링, 자동 재연결 로직을 검증합니다.
모킹으로 실제 API 호출 없이 테스트합니다.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.streaming.websocket_client import (
    ConnectionState,
    KISWebSocketClient,
    PriceData,
    TR_ID_REALTIME_PRICE,
)


# ─────────────────── Fixtures ─────────────────────


@pytest.fixture
def client() -> KISWebSocketClient:
    """기본 WebSocket 클라이언트"""
    return KISWebSocketClient(
        app_key="test_key",
        app_secret="test_secret",
        mock=True,
    )


@pytest.fixture
def mock_ws() -> AsyncMock:
    """모킹된 WebSocket 연결"""
    ws = AsyncMock()
    ws.send = AsyncMock()
    ws.recv = AsyncMock()
    ws.close = AsyncMock()
    return ws


# ─────────────────── PriceData ─────────────────────


class TestPriceData:
    """PriceData 모델 테스트"""

    def test_creation(self) -> None:
        """기본 생성"""
        data = PriceData(
            stock_code="005930",
            current_price=72000.0,
            change=-500.0,
            change_rate=-0.69,
            volume=1000,
            trade_time="153000",
        )
        assert data.stock_code == "005930"
        assert data.current_price == 72000.0
        assert data.volume == 1000

    def test_to_dict(self) -> None:
        """딕셔너리 변환"""
        data = PriceData(
            stock_code="005930",
            current_price=72000.0,
            change=-500.0,
            change_rate=-0.69,
            volume=1000,
            trade_time="153000",
            ask_price=72100.0,
            bid_price=71900.0,
        )
        d = data.to_dict()
        assert d["stock_code"] == "005930"
        assert d["current_price"] == 72000.0
        assert d["ask_price"] == 72100.0
        assert d["bid_price"] == 71900.0


# ─────────────────── 초기 상태 ─────────────────────


class TestInitialState:
    """초기 상태 테스트"""

    def test_default_state(self, client: KISWebSocketClient) -> None:
        """기본 상태 확인"""
        assert client.state == ConnectionState.DISCONNECTED
        assert client.is_connected is False
        assert client.subscriptions == set()

    def test_ws_url_mock(self, client: KISWebSocketClient) -> None:
        """모의투자 WebSocket URL"""
        assert "31000" in client.ws_url

    def test_ws_url_prod(self) -> None:
        """실전투자 WebSocket URL"""
        prod_client = KISWebSocketClient(
            app_key="key",
            app_secret="secret",
            mock=False,
        )
        assert "21000" in prod_client.ws_url

    def test_base_url_mock(self, client: KISWebSocketClient) -> None:
        """모의투자 REST URL"""
        assert "openapivts" in client.base_url

    def test_base_url_prod(self) -> None:
        """실전투자 REST URL"""
        prod_client = KISWebSocketClient(
            app_key="key",
            app_secret="secret",
            mock=False,
        )
        assert "openapi.koreainvestment" in prod_client.base_url


# ─────────────────── 접속키 발급 ─────────────────────


class TestApprovalKey:
    """접속키 발급 테스트"""

    @pytest.mark.asyncio
    async def test_get_approval_key_success(self, client: KISWebSocketClient) -> None:
        """접속키 발급 성공"""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"approval_key": "test_approval_key_123"}
        mock_resp.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=None)

        with patch("src.streaming.websocket_client.httpx.AsyncClient", return_value=mock_http):
            key = await client._get_approval_key()

        assert key == "test_approval_key_123"

    @pytest.mark.asyncio
    async def test_get_approval_key_empty(self, client: KISWebSocketClient) -> None:
        """접속키 발급 실패 (빈 키)"""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"approval_key": ""}
        mock_resp.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("src.streaming.websocket_client.httpx.AsyncClient", return_value=mock_http),
            pytest.raises(RuntimeError, match="접속키 발급 실패"),
        ):
            await client._get_approval_key()


# ─────────────────── 연결/해제 ─────────────────────


class TestConnection:
    """연결/해제 테스트"""

    @pytest.mark.asyncio
    async def test_connect_success(
        self, client: KISWebSocketClient, mock_ws: AsyncMock,
    ) -> None:
        """연결 성공"""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"approval_key": "test_key"}
        mock_resp.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("src.streaming.websocket_client.httpx.AsyncClient", return_value=mock_http),
            patch("src.streaming.websocket_client.websockets.connect", new_callable=AsyncMock, return_value=mock_ws),
        ):
            # recv에서 블로킹 방지
            mock_ws.recv = AsyncMock(side_effect=asyncio.CancelledError)

            await client.connect()

            assert client.state == ConnectionState.CONNECTED
            assert client.is_connected is True

        # cleanup
        await client.disconnect()

    @pytest.mark.asyncio
    async def test_connect_already_connected(
        self, client: KISWebSocketClient,
    ) -> None:
        """이미 연결 중일 때"""
        client._state = ConnectionState.CONNECTED
        # connect를 호출해도 에러 없이 무시됨
        await client.connect()
        assert client.state == ConnectionState.CONNECTED

    @pytest.mark.asyncio
    async def test_disconnect(
        self, client: KISWebSocketClient, mock_ws: AsyncMock,
    ) -> None:
        """연결 해제"""
        client._ws = mock_ws
        client._state = ConnectionState.CONNECTED
        client._subscriptions = {"005930", "000660"}
        client._running = True

        await client.disconnect()

        assert client.state == ConnectionState.DISCONNECTED
        assert client.is_connected is False
        assert client.subscriptions == set()
        mock_ws.close.assert_awaited_once()


# ─────────────────── 구독/해제 ─────────────────────


class TestSubscription:
    """구독/해제 테스트"""

    @pytest.mark.asyncio
    async def test_subscribe(
        self, client: KISWebSocketClient, mock_ws: AsyncMock,
    ) -> None:
        """종목 구독"""
        client._ws = mock_ws
        client._state = ConnectionState.CONNECTED
        client._approval_key = "test_key"
        client._running = True

        await client.subscribe("005930")

        assert "005930" in client.subscriptions
        mock_ws.send.assert_awaited_once()

        # 전송된 메시지 확인
        sent_data = json.loads(mock_ws.send.call_args[0][0])
        assert sent_data["header"]["tr_type"] == "1"
        assert sent_data["body"]["input"]["tr_key"] == "005930"

    @pytest.mark.asyncio
    async def test_subscribe_duplicate(
        self, client: KISWebSocketClient, mock_ws: AsyncMock,
    ) -> None:
        """중복 구독 시 무시"""
        client._ws = mock_ws
        client._state = ConnectionState.CONNECTED
        client._approval_key = "test_key"
        client._running = True
        client._subscriptions = {"005930"}

        await client.subscribe("005930")

        mock_ws.send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_subscribe_not_connected(
        self, client: KISWebSocketClient,
    ) -> None:
        """미연결 시 구독 에러"""
        with pytest.raises(RuntimeError, match="연결되지 않았습니다"):
            await client.subscribe("005930")

    @pytest.mark.asyncio
    async def test_unsubscribe(
        self, client: KISWebSocketClient, mock_ws: AsyncMock,
    ) -> None:
        """종목 구독 해제"""
        client._ws = mock_ws
        client._state = ConnectionState.CONNECTED
        client._approval_key = "test_key"
        client._running = True
        client._subscriptions = {"005930"}

        await client.unsubscribe("005930")

        assert "005930" not in client.subscriptions
        mock_ws.send.assert_awaited_once()

        sent_data = json.loads(mock_ws.send.call_args[0][0])
        assert sent_data["header"]["tr_type"] == "2"

    @pytest.mark.asyncio
    async def test_unsubscribe_not_subscribed(
        self, client: KISWebSocketClient, mock_ws: AsyncMock,
    ) -> None:
        """구독 중이 아닌 종목 해제 시 무시"""
        client._ws = mock_ws
        client._state = ConnectionState.CONNECTED
        client._running = True

        await client.unsubscribe("005930")

        mock_ws.send.assert_not_awaited()


# ─────────────────── 메시지 파싱 ─────────────────────


class TestMessageParsing:
    """메시지 파싱 테스트"""

    @pytest.mark.asyncio
    async def test_handle_pingpong(self, client: KISWebSocketClient) -> None:
        """PINGPONG 메시지 처리"""
        # 에러 없이 무시되어야 함
        await client._handle_message("PINGPONG")

    @pytest.mark.asyncio
    async def test_handle_json_subscribe_success(
        self, client: KISWebSocketClient,
    ) -> None:
        """JSON 구독 확인 메시지"""
        msg = json.dumps({
            "header": {
                "tr_id": TR_ID_REALTIME_PRICE,
                "msg_cd": "OPSP0000",
                "msg1": "구독 성공",
            },
        })
        # 에러 없이 처리
        await client._handle_message(msg)

    @pytest.mark.asyncio
    async def test_handle_json_unsubscribe_success(
        self, client: KISWebSocketClient,
    ) -> None:
        """JSON 구독 해제 확인 메시지"""
        msg = json.dumps({
            "header": {
                "tr_id": TR_ID_REALTIME_PRICE,
                "msg_cd": "OPSP0002",
                "msg1": "해제 성공",
            },
        })
        await client._handle_message(msg)

    @pytest.mark.asyncio
    async def test_handle_invalid_json(self, client: KISWebSocketClient) -> None:
        """잘못된 JSON"""
        await client._handle_message("{invalid json")

    @pytest.mark.asyncio
    async def test_handle_realtime_data(
        self, client: KISWebSocketClient,
    ) -> None:
        """실시간 체결가 데이터 파싱"""
        callback_data: list[PriceData] = []

        async def on_price(data: PriceData) -> None:
            callback_data.append(data)

        client.on_price_update(on_price)

        # KIS 실시간 데이터 포맷: 암호화여부|TR코드|데이터건수|데이터
        # 데이터 필드는 ^ 구분
        fields = ["005930", "field1", "153000", "72000", "+", "500", "f6", "f7", "1000", "f9", "f10", "0.69", "f12", "72100", "71900"]
        body = "^".join(fields)
        raw = f"0|{TR_ID_REALTIME_PRICE}|001|{body}"

        await client._handle_message(raw)

        assert len(callback_data) == 1
        assert callback_data[0].stock_code == "005930"
        assert callback_data[0].current_price == 72000.0
        assert callback_data[0].volume == 1000
        assert callback_data[0].trade_time == "153000"
        assert callback_data[0].ask_price == 72100.0

    @pytest.mark.asyncio
    async def test_handle_realtime_data_insufficient_fields(
        self, client: KISWebSocketClient,
    ) -> None:
        """필드 부족 시 무시"""
        callback_data: list[PriceData] = []

        async def on_price(data: PriceData) -> None:
            callback_data.append(data)

        client.on_price_update(on_price)

        # 필드 부족
        raw = f"0|{TR_ID_REALTIME_PRICE}|001|005930^field1^153000"
        await client._handle_message(raw)

        assert len(callback_data) == 0

    @pytest.mark.asyncio
    async def test_handle_realtime_data_wrong_tr_id(
        self, client: KISWebSocketClient,
    ) -> None:
        """잘못된 TR ID"""
        callback_data: list[PriceData] = []

        async def on_price(data: PriceData) -> None:
            callback_data.append(data)

        client.on_price_update(on_price)

        fields = ["005930"] + ["0"] * 14
        body = "^".join(fields)
        raw = f"0|WRONG_TR|001|{body}"
        await client._handle_message(raw)

        assert len(callback_data) == 0

    @pytest.mark.asyncio
    async def test_handle_bytes_message(self, client: KISWebSocketClient) -> None:
        """바이트 메시지 처리"""
        await client._handle_message(b"PINGPONG")

    @pytest.mark.asyncio
    async def test_handle_short_pipe_message(
        self, client: KISWebSocketClient,
    ) -> None:
        """짧은 파이프 메시지 (4개 미만)"""
        await client._handle_message("0|TR|1")


# ─────────────────── 콜백 ─────────────────────


class TestCallbacks:
    """콜백 등록 테스트"""

    def test_register_on_price_update(self, client: KISWebSocketClient) -> None:
        """체결가 콜백 등록"""
        async def callback(data: PriceData) -> None:
            pass

        client.on_price_update(callback)
        assert client._on_price_update is callback

    def test_register_on_connection_lost(self, client: KISWebSocketClient) -> None:
        """연결 끊김 콜백 등록"""
        async def callback() -> None:
            pass

        client.on_connection_lost(callback)
        assert client._on_connection_lost is callback

    def test_register_on_connected(self, client: KISWebSocketClient) -> None:
        """연결 성공 콜백 등록"""
        async def callback() -> None:
            pass

        client.on_connected(callback)
        assert client._on_connected is callback


# ─────────────────── 구독 메시지 빌드 ─────────────────────


class TestBuildSubscribeMessage:
    """구독 메시지 빌드 테스트"""

    def test_subscribe_message(self, client: KISWebSocketClient) -> None:
        """구독 메시지 생성"""
        client._approval_key = "test_key"
        msg = client._build_subscribe_message("005930", subscribe=True)

        assert msg["header"]["approval_key"] == "test_key"
        assert msg["header"]["tr_type"] == "1"
        assert msg["body"]["input"]["tr_id"] == TR_ID_REALTIME_PRICE
        assert msg["body"]["input"]["tr_key"] == "005930"

    def test_unsubscribe_message(self, client: KISWebSocketClient) -> None:
        """구독 해제 메시지 생성"""
        client._approval_key = "test_key"
        msg = client._build_subscribe_message("005930", subscribe=False)

        assert msg["header"]["tr_type"] == "2"


# ─────────────────── 재연결 ─────────────────────


class TestReconnect:
    """자동 재연결 테스트"""

    @pytest.mark.asyncio
    async def test_reconnect_success(
        self, client: KISWebSocketClient, mock_ws: AsyncMock,
    ) -> None:
        """재연결 성공"""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"approval_key": "new_key"}
        mock_resp.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=None)

        mock_ws.recv = AsyncMock(side_effect=asyncio.CancelledError)

        client._running = True
        client._reconnect_attempts = 0

        with (
            patch("src.streaming.websocket_client.httpx.AsyncClient", return_value=mock_http),
            patch("src.streaming.websocket_client.websockets.connect", new_callable=AsyncMock, return_value=mock_ws),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            await client._reconnect()

        assert client.state == ConnectionState.CONNECTED
        assert client._reconnect_attempts == 0

        await client.disconnect()

    @pytest.mark.asyncio
    async def test_reconnect_max_attempts(
        self, client: KISWebSocketClient,
    ) -> None:
        """최대 재연결 시도 초과"""
        client._running = True
        client._reconnect_attempts = 0

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"approval_key": ""}
        mock_resp.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("src.streaming.websocket_client.httpx.AsyncClient", return_value=mock_http),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            await client._reconnect()

        assert client.state == ConnectionState.DISCONNECTED
        assert client._running is False

    @pytest.mark.asyncio
    async def test_reconnect_restores_subscriptions(
        self, client: KISWebSocketClient, mock_ws: AsyncMock,
    ) -> None:
        """재연결 후 구독 복원"""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"approval_key": "new_key"}
        mock_resp.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=None)

        mock_ws.recv = AsyncMock(side_effect=asyncio.CancelledError)

        client._running = True
        client._subscriptions = {"005930", "000660"}

        with (
            patch("src.streaming.websocket_client.httpx.AsyncClient", return_value=mock_http),
            patch("src.streaming.websocket_client.websockets.connect", new_callable=AsyncMock, return_value=mock_ws),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            await client._reconnect()

        assert "005930" in client.subscriptions
        assert "000660" in client.subscriptions

        await client.disconnect()

    @pytest.mark.asyncio
    async def test_on_disconnect_triggers_reconnect(
        self, client: KISWebSocketClient,
    ) -> None:
        """연결 끊김 시 재연결 트리거"""
        client._running = True
        lost_called = False

        async def on_lost() -> None:
            nonlocal lost_called
            lost_called = True

        client.on_connection_lost(on_lost)

        with patch.object(client, "_reconnect", new_callable=AsyncMock) as mock_reconnect:
            await client._on_disconnect()

        assert lost_called is True
        mock_reconnect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_on_disconnect_no_reconnect_when_stopped(
        self, client: KISWebSocketClient,
    ) -> None:
        """running=False일 때 재연결하지 않음"""
        client._running = False

        with patch.object(client, "_reconnect", new_callable=AsyncMock) as mock_reconnect:
            await client._on_disconnect()

        mock_reconnect.assert_not_awaited()


# ─────────────────── Send ─────────────────────


class TestSend:
    """메시지 전송 테스트"""

    @pytest.mark.asyncio
    async def test_send_success(
        self, client: KISWebSocketClient, mock_ws: AsyncMock,
    ) -> None:
        """전송 성공"""
        client._ws = mock_ws
        await client._send("test message")
        mock_ws.send.assert_awaited_once_with("test message")

    @pytest.mark.asyncio
    async def test_send_not_connected(self, client: KISWebSocketClient) -> None:
        """미연결 시 전송 에러"""
        with pytest.raises(RuntimeError, match="연결되지 않았습니다"):
            await client._send("test")

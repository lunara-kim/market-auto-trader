"""
실시간 시세 스트리밍 WebSocket API

클라이언트가 종목코드를 구독하면 실시간 체결가를 푸시합니다.

구독 메시지:
    {"action": "subscribe", "stock_codes": ["005930", "000660"]}

해제 메시지:
    {"action": "unsubscribe", "stock_codes": ["005930"]}
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.streaming.websocket_client import KISWebSocketClient, PriceData
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["Streaming"])


# ───────────────────── Connection Manager ─────────────────────


@dataclass
class StreamingConnectionManager:
    """WebSocket 연결 및 구독 관리자

    여러 클라이언트가 같은 종목을 구독할 때 KIS WebSocket 구독을 공유합니다.
    """

    # client_id → WebSocket
    _clients: dict[int, WebSocket] = field(default_factory=dict, init=False)
    # client_id → 구독 종목 set
    _client_subscriptions: dict[int, set[str]] = field(default_factory=dict, init=False)
    # 종목 → 구독 client_id set
    _stock_subscribers: dict[str, set[int]] = field(default_factory=dict, init=False)
    # KIS WebSocket 클라이언트 (실제 운영 시 설정에서 주입)
    _kis_client: KISWebSocketClient | None = field(default=None, init=False)
    _kis_connected: bool = field(default=False, init=False)

    async def connect(self, websocket: WebSocket) -> int:
        """클라이언트 연결 수락

        Args:
            websocket: FastAPI WebSocket 객체

        Returns:
            클라이언트 ID
        """
        await websocket.accept()
        client_id = id(websocket)
        self._clients[client_id] = websocket
        self._client_subscriptions[client_id] = set()

        logger.info("클라이언트 연결: %d (총 %d명)", client_id, len(self._clients))
        return client_id

    def disconnect(self, client_id: int) -> None:
        """클라이언트 연결 해제

        Args:
            client_id: 클라이언트 ID
        """
        # 구독 정리
        subs = self._client_subscriptions.pop(client_id, set())
        for stock_code in subs:
            if stock_code in self._stock_subscribers:
                self._stock_subscribers[stock_code].discard(client_id)
                if not self._stock_subscribers[stock_code]:
                    del self._stock_subscribers[stock_code]
                    # TODO: KIS WebSocket에서도 구독 해제

        self._clients.pop(client_id, None)
        logger.info("클라이언트 해제: %d (총 %d명)", client_id, len(self._clients))

    async def subscribe(self, client_id: int, stock_codes: list[str]) -> None:
        """종목 구독

        Args:
            client_id: 클라이언트 ID
            stock_codes: 구독할 종목 코드 목록
        """
        for stock_code in stock_codes:
            # 클라이언트 구독 목록에 추가
            if client_id in self._client_subscriptions:
                self._client_subscriptions[client_id].add(stock_code)

            # 종목 구독자 목록에 추가
            if stock_code not in self._stock_subscribers:
                self._stock_subscribers[stock_code] = set()
            self._stock_subscribers[stock_code].add(client_id)

            logger.debug(
                "구독: client=%d, stock=%s (구독자 %d명)",
                client_id,
                stock_code,
                len(self._stock_subscribers[stock_code]),
            )

    async def unsubscribe(self, client_id: int, stock_codes: list[str]) -> None:
        """종목 구독 해제

        Args:
            client_id: 클라이언트 ID
            stock_codes: 해제할 종목 코드 목록
        """
        for stock_code in stock_codes:
            if client_id in self._client_subscriptions:
                self._client_subscriptions[client_id].discard(stock_code)

            if stock_code in self._stock_subscribers:
                self._stock_subscribers[stock_code].discard(client_id)
                if not self._stock_subscribers[stock_code]:
                    del self._stock_subscribers[stock_code]

            logger.debug("구독 해제: client=%d, stock=%s", client_id, stock_code)

    async def broadcast_price(self, price_data: PriceData) -> None:
        """체결가 브로드캐스트

        해당 종목을 구독 중인 모든 클라이언트에게 시세를 전송합니다.

        Args:
            price_data: 실시간 체결가 데이터
        """
        stock_code = price_data.stock_code
        subscribers = self._stock_subscribers.get(stock_code, set())

        if not subscribers:
            return

        message = json.dumps({
            "type": "price_update",
            "data": price_data.to_dict(),
        })

        disconnected: list[int] = []

        for client_id in subscribers:
            ws = self._clients.get(client_id)
            if ws:
                try:
                    await ws.send_text(message)
                except Exception:
                    disconnected.append(client_id)

        for client_id in disconnected:
            self.disconnect(client_id)

    def get_client_subscriptions(self, client_id: int) -> set[str]:
        """클라이언트의 구독 종목 목록 조회"""
        return self._client_subscriptions.get(client_id, set()).copy()

    def get_stock_subscriber_count(self, stock_code: str) -> int:
        """종목의 구독자 수 조회"""
        return len(self._stock_subscribers.get(stock_code, set()))

    @property
    def client_count(self) -> int:
        """현재 연결된 클라이언트 수"""
        return len(self._clients)


# 전역 매니저 인스턴스
manager = StreamingConnectionManager()


# ───────────────────── WebSocket Endpoint ─────────────────────


@router.websocket("/api/v1/ws/prices")
async def websocket_prices(websocket: WebSocket) -> None:
    """실시간 시세 WebSocket 엔드포인트

    클라이언트가 구독 메시지를 보내면 해당 종목의 실시간 체결가를 푸시합니다.

    구독:
        {"action": "subscribe", "stock_codes": ["005930", "000660"]}

    해제:
        {"action": "unsubscribe", "stock_codes": ["005930"]}
    """
    client_id = await manager.connect(websocket)

    try:
        while True:
            raw = await websocket.receive_text()

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": "유효하지 않은 JSON 형식입니다",
                }))
                continue

            action = data.get("action")
            stock_codes = data.get("stock_codes", [])

            if not isinstance(stock_codes, list):
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": "stock_codes는 리스트여야 합니다",
                }))
                continue

            if action == "subscribe":
                await manager.subscribe(client_id, stock_codes)
                await websocket.send_text(json.dumps({
                    "type": "subscribed",
                    "stock_codes": stock_codes,
                    "total_subscriptions": list(
                        manager.get_client_subscriptions(client_id),
                    ),
                }))

            elif action == "unsubscribe":
                await manager.unsubscribe(client_id, stock_codes)
                await websocket.send_text(json.dumps({
                    "type": "unsubscribed",
                    "stock_codes": stock_codes,
                    "total_subscriptions": list(
                        manager.get_client_subscriptions(client_id),
                    ),
                }))

            else:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": f"알 수 없는 action: {action}",
                }))

    except WebSocketDisconnect:
        manager.disconnect(client_id)
    except Exception:
        logger.exception("WebSocket 에러: client=%d", client_id)
        manager.disconnect(client_id)

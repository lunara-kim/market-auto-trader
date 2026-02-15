"""
한국투자증권 WebSocket 실시간 시세 클라이언트

KIS WebSocket API를 통해 실시간 체결가를 수신합니다.

프로토콜 흐름:
    1. POST /oauth2/Approval → 웹소켓 접속키 발급
    2. WebSocket 연결 (wss://ops.koreainvestment.com:21000 or :31000)
    3. JSON 구독 메시지 전송 → 실시간 데이터 수신
    4. 연결 유지 (heartbeat), 자동 재연결 (exponential backoff)

References:
    - https://apiportal.koreainvestment.com/apiservice/apiservice-domestic-stock-real2
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import httpx
import websockets
from websockets.asyncio.client import ClientConnection

from config.settings import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


# ───────────────────── Constants ─────────────────────

BASE_URL_PROD = "https://openapi.koreainvestment.com:9443"
BASE_URL_MOCK = "https://openapivts.koreainvestment.com:29443"

# 실시간 체결가 TR 코드
TR_ID_REALTIME_PRICE = "H0STCNT0"  # 국내 실시간 체결

# 재연결 설정
RECONNECT_BASE_DELAY = 1.0  # 초
RECONNECT_MAX_DELAY = 60.0  # 최대 대기 시간
RECONNECT_MAX_ATTEMPTS = 10

# Heartbeat (PINGPONG)
HEARTBEAT_INTERVAL = 30.0  # 초


class ConnectionState(str, Enum):
    """WebSocket 연결 상태"""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"


@dataclass
class PriceData:
    """실시간 체결가 데이터"""

    stock_code: str
    current_price: float
    change: float
    change_rate: float
    volume: int
    trade_time: str
    ask_price: float = 0.0
    bid_price: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            "stock_code": self.stock_code,
            "current_price": self.current_price,
            "change": self.change,
            "change_rate": self.change_rate,
            "volume": self.volume,
            "trade_time": self.trade_time,
            "ask_price": self.ask_price,
            "bid_price": self.bid_price,
        }


# 콜백 타입 정의
PriceCallback = Callable[[PriceData], Coroutine[Any, Any, None]]
ConnectionCallback = Callable[[], Coroutine[Any, Any, None]]


@dataclass
class KISWebSocketClient:
    """한국투자증권 WebSocket 실시간 시세 클라이언트

    Args:
        app_key: 한투 앱 키
        app_secret: 한투 앱 시크릿
        mock: 모의투자 여부
    """

    app_key: str = ""
    app_secret: str = ""
    mock: bool = True

    # 내부 상태
    _ws: ClientConnection | None = field(default=None, init=False, repr=False)
    _state: ConnectionState = field(default=ConnectionState.DISCONNECTED, init=False)
    _approval_key: str = field(default="", init=False, repr=False)
    _subscriptions: set[str] = field(default_factory=set, init=False)
    _reconnect_attempts: int = field(default=0, init=False)
    _running: bool = field(default=False, init=False)
    _receive_task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)
    _heartbeat_task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)

    # 콜백
    _on_price_update: PriceCallback | None = field(default=None, init=False, repr=False)
    _on_connection_lost: ConnectionCallback | None = field(default=None, init=False, repr=False)
    _on_connected: ConnectionCallback | None = field(default=None, init=False, repr=False)

    # ───────────────── Properties ─────────────────

    @property
    def state(self) -> ConnectionState:
        """현재 연결 상태"""
        return self._state

    @property
    def subscriptions(self) -> set[str]:
        """현재 구독 중인 종목 코드"""
        return self._subscriptions.copy()

    @property
    def is_connected(self) -> bool:
        """연결 여부"""
        return self._state == ConnectionState.CONNECTED and self._ws is not None

    @property
    def ws_url(self) -> str:
        """WebSocket URL"""
        if self.mock:
            return settings.kis_ws_url_mock
        return settings.kis_ws_url_prod

    @property
    def base_url(self) -> str:
        """REST API Base URL"""
        if self.mock:
            return BASE_URL_MOCK
        return BASE_URL_PROD

    # ───────────────── Callback Registration ─────────────────

    def on_price_update(self, callback: PriceCallback) -> None:
        """체결가 수신 콜백 등록"""
        self._on_price_update = callback

    def on_connection_lost(self, callback: ConnectionCallback) -> None:
        """연결 끊김 콜백 등록"""
        self._on_connection_lost = callback

    def on_connected(self, callback: ConnectionCallback) -> None:
        """연결 성공 콜백 등록"""
        self._on_connected = callback

    # ───────────────── Approval Key ─────────────────

    async def _get_approval_key(self) -> str:
        """웹소켓 접속키 발급

        POST /oauth2/Approval 호출하여 WebSocket 접속키를 발급받습니다.

        Returns:
            접속키 문자열

        Raises:
            RuntimeError: 접속키 발급 실패 시
        """
        url = f"{self.base_url}/oauth2/Approval"
        body = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "secretkey": self.app_secret,
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=body)
            resp.raise_for_status()
            data = resp.json()

        approval_key = data.get("approval_key", "")
        if not approval_key:
            msg = f"접속키 발급 실패: {data}"
            raise RuntimeError(msg)

        logger.info("WebSocket 접속키 발급 완료")
        return approval_key

    # ───────────────── Connection ─────────────────

    async def connect(self) -> None:
        """WebSocket 연결

        접속키 발급 → WebSocket 연결 → 메시지 수신 루프 시작
        """
        if self._state in (ConnectionState.CONNECTED, ConnectionState.CONNECTING):
            logger.warning("이미 연결 중이거나 연결됨: %s", self._state)
            return

        self._state = ConnectionState.CONNECTING
        self._running = True

        try:
            # 1. 접속키 발급
            self._approval_key = await self._get_approval_key()

            # 2. WebSocket 연결
            self._ws = await websockets.connect(self.ws_url)
            self._state = ConnectionState.CONNECTED
            self._reconnect_attempts = 0

            logger.info(
                "WebSocket 연결 성공: %s (모의=%s)",
                self.ws_url,
                self.mock,
            )

            # 3. 연결 콜백 호출
            if self._on_connected:
                await self._on_connected()

            # 4. 수신 루프 & heartbeat 시작
            self._receive_task = asyncio.create_task(self._receive_loop())
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        except Exception:
            self._state = ConnectionState.DISCONNECTED
            logger.exception("WebSocket 연결 실패")
            raise

    async def disconnect(self) -> None:
        """WebSocket 연결 해제"""
        self._running = False

        if self._receive_task and not self._receive_task.done():
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass

        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        if self._ws:
            await self._ws.close()
            self._ws = None

        self._state = ConnectionState.DISCONNECTED
        self._subscriptions.clear()
        logger.info("WebSocket 연결 해제 완료")

    # ───────────────── Subscribe / Unsubscribe ─────────────────

    async def subscribe(self, stock_code: str) -> None:
        """종목 실시간 체결가 구독

        Args:
            stock_code: 종목 코드 (6자리)
        """
        if not self.is_connected:
            msg = "WebSocket이 연결되지 않았습니다"
            raise RuntimeError(msg)

        if stock_code in self._subscriptions:
            logger.debug("이미 구독 중: %s", stock_code)
            return

        message = self._build_subscribe_message(stock_code, subscribe=True)
        await self._send(json.dumps(message))
        self._subscriptions.add(stock_code)
        logger.info("종목 구독 시작: %s", stock_code)

    async def unsubscribe(self, stock_code: str) -> None:
        """종목 실시간 체결가 구독 해제

        Args:
            stock_code: 종목 코드 (6자리)
        """
        if not self.is_connected:
            msg = "WebSocket이 연결되지 않았습니다"
            raise RuntimeError(msg)

        if stock_code not in self._subscriptions:
            logger.debug("구독 중이 아님: %s", stock_code)
            return

        message = self._build_subscribe_message(stock_code, subscribe=False)
        await self._send(json.dumps(message))
        self._subscriptions.discard(stock_code)
        logger.info("종목 구독 해제: %s", stock_code)

    def _build_subscribe_message(
        self, stock_code: str, *, subscribe: bool = True,
    ) -> dict[str, Any]:
        """KIS WebSocket 구독/해제 메시지 생성

        Args:
            stock_code: 종목 코드
            subscribe: True=구독, False=해제
        """
        return {
            "header": {
                "approval_key": self._approval_key,
                "custtype": "P",
                "tr_type": "1" if subscribe else "2",
                "content-type": "utf-8",
            },
            "body": {
                "input": {
                    "tr_id": TR_ID_REALTIME_PRICE,
                    "tr_key": stock_code,
                },
            },
        }

    # ───────────────── Message Handling ─────────────────

    async def _receive_loop(self) -> None:
        """메시지 수신 루프"""
        try:
            while self._running and self._ws:
                try:
                    raw = await self._ws.recv()
                    await self._handle_message(raw)
                except websockets.ConnectionClosed:
                    logger.warning("WebSocket 연결 끊김")
                    break
                except Exception:
                    logger.exception("메시지 수신 중 에러")
                    continue
        finally:
            if self._running:
                await self._on_disconnect()

    async def _handle_message(self, raw: str | bytes) -> None:
        """수신 메시지 처리

        KIS WebSocket은 두 가지 포맷으로 메시지를 전송합니다:
        1. JSON 형식: 구독 확인, 에러 응답
        2. 파이프(|) 구분 텍스트: 실시간 시세 데이터
        """
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")

        # PINGPONG 응답 처리
        if raw.startswith("PINGPONG"):
            return

        # JSON 메시지 (구독 확인 등)
        if raw.startswith("{"):
            try:
                data = json.loads(raw)
                self._handle_json_message(data)
            except json.JSONDecodeError:
                logger.warning("JSON 파싱 실패: %s", raw[:100])
            return

        # 파이프 구분 실시간 데이터
        await self._handle_realtime_data(raw)

    def _handle_json_message(self, data: dict[str, Any]) -> None:
        """JSON 메시지 처리 (구독 확인/에러)"""
        header = data.get("header", {})
        tr_id = header.get("tr_id", "")
        msg_cd = header.get("msg_cd", "")
        msg = header.get("msg1", "")

        if msg_cd == "OPSP0000":
            logger.info("구독 성공: tr_id=%s, %s", tr_id, msg)
        elif msg_cd == "OPSP0002":
            logger.info("구독 해제 성공: tr_id=%s, %s", tr_id, msg)
        else:
            logger.debug("JSON 메시지: tr_id=%s, msg_cd=%s, msg=%s", tr_id, msg_cd, msg)

    async def _handle_realtime_data(self, raw: str) -> None:
        """파이프 구분 실시간 체결가 데이터 처리

        KIS 실시간 체결가 데이터 포맷 (H0STCNT0):
        - 헤더: 암호화여부|TR코드|데이터건수
        - 바디: 파이프(|) 구분 필드

        체결가 데이터 주요 필드 (인덱스):
        - 0: 종목코드
        - 2: 체결시간 (HHMMSS)
        - 3: 현재가
        - 4: 전일대비 부호
        - 5: 전일대비
        - 8: 체결거래량
        - 11: 전일대비율
        - 13: 매도호가
        - 14: 매수호가
        """
        try:
            parts = raw.split("|")
            if len(parts) < 4:
                return

            # 헤더 파싱: 암호화여부|TR코드|데이터건수|데이터
            tr_id = parts[1]
            if tr_id != TR_ID_REALTIME_PRICE:
                return

            body = parts[3]
            fields = body.split("^")

            if len(fields) < 15:
                logger.debug("필드 수 부족: %d", len(fields))
                return

            price_data = PriceData(
                stock_code=fields[0],
                trade_time=fields[2],
                current_price=float(fields[3]),
                change=float(fields[5]),
                change_rate=float(fields[11]),
                volume=int(fields[8]),
                ask_price=float(fields[13]),
                bid_price=float(fields[14]),
            )

            if self._on_price_update:
                await self._on_price_update(price_data)

        except (IndexError, ValueError):
            logger.debug("실시간 데이터 파싱 실패: %s", raw[:100])

    # ───────────────── Heartbeat & Reconnect ─────────────────

    async def _heartbeat_loop(self) -> None:
        """Heartbeat 루프 (PINGPONG)"""
        try:
            while self._running and self._ws:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                if self._ws and self._running:
                    try:
                        await self._send("PINGPONG")
                    except Exception:
                        logger.warning("Heartbeat 전송 실패")
                        break
        except asyncio.CancelledError:
            pass

    async def _send(self, data: str) -> None:
        """WebSocket 메시지 전송

        Args:
            data: 전송할 메시지 문자열
        """
        if not self._ws:
            msg = "WebSocket이 연결되지 않았습니다"
            raise RuntimeError(msg)
        await self._ws.send(data)

    async def _on_disconnect(self) -> None:
        """연결 끊김 처리"""
        self._state = ConnectionState.DISCONNECTED

        if self._on_connection_lost:
            await self._on_connection_lost()

        if self._running:
            await self._reconnect()

    async def _reconnect(self) -> None:
        """자동 재연결 (exponential backoff)"""
        saved_subs = self._subscriptions.copy()
        self._subscriptions.clear()

        while self._running and self._reconnect_attempts < RECONNECT_MAX_ATTEMPTS:
            self._state = ConnectionState.RECONNECTING
            self._reconnect_attempts += 1

            delay = min(
                RECONNECT_BASE_DELAY * (2 ** (self._reconnect_attempts - 1)),
                RECONNECT_MAX_DELAY,
            )

            logger.info(
                "재연결 시도 %d/%d (%.1f초 후)",
                self._reconnect_attempts,
                RECONNECT_MAX_ATTEMPTS,
                delay,
            )

            await asyncio.sleep(delay)

            try:
                self._approval_key = await self._get_approval_key()
                self._ws = await websockets.connect(self.ws_url)
                self._state = ConnectionState.CONNECTED
                self._reconnect_attempts = 0

                logger.info("WebSocket 재연결 성공")

                if self._on_connected:
                    await self._on_connected()

                # 기존 구독 복원
                for stock_code in saved_subs:
                    await self.subscribe(stock_code)

                # 수신 루프 & heartbeat 재시작
                self._receive_task = asyncio.create_task(self._receive_loop())
                self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
                return

            except Exception:
                logger.warning(
                    "재연결 실패 (%d/%d)",
                    self._reconnect_attempts,
                    RECONNECT_MAX_ATTEMPTS,
                )

        if self._running:
            logger.error("최대 재연결 시도 횟수 초과 (%d회)", RECONNECT_MAX_ATTEMPTS)
            self._state = ConnectionState.DISCONNECTED
            self._running = False

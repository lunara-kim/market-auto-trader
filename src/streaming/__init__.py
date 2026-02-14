"""
실시간 시세 스트리밍 모듈

한국투자증권 WebSocket API를 통한 실시간 체결가 스트리밍을 제공합니다.
"""

from __future__ import annotations

from src.streaming.websocket_client import KISWebSocketClient

__all__ = ["KISWebSocketClient"]

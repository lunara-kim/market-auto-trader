"""
API 스키마 Pydantic 모델 테스트
"""

from __future__ import annotations

import pytest

from src.api.schemas import (
    ErrorDetail,
    ErrorResponse,
    HealthResponse,
    HoldingItem,
    MATypeEnum,
    OrderHistoryResponse,
    OrderRequest,
    OrderResponse,
    OrderType,
    PortfolioResponse,
    PortfolioSummary,
    SignalHistoryResponse,
    SignalMetrics,
    SignalRequest,
    SignalResponse,
)


class TestHealthResponse:
    """HealthResponse 모델 테스트"""

    def test_default(self) -> None:
        r = HealthResponse(version="0.3.0", env="test")
        assert r.status == "ok"
        assert r.version == "0.3.0"

    def test_serialization(self) -> None:
        r = HealthResponse(version="0.3.0", env="production")
        d = r.model_dump()
        assert d["status"] == "ok"
        assert d["env"] == "production"


class TestErrorResponse:
    """ErrorResponse 모델 테스트"""

    def test_basic(self) -> None:
        err = ErrorResponse(
            error=ErrorDetail(code="NOT_FOUND", message="리소스를 찾을 수 없습니다")
        )
        assert err.error.code == "NOT_FOUND"
        assert err.error.detail is None

    def test_with_detail(self) -> None:
        err = ErrorResponse(
            error=ErrorDetail(
                code="VALIDATION",
                message="잘못된 입력",
                detail={"field": "stock_code"},
            )
        )
        assert err.error.detail == {"field": "stock_code"}


class TestPortfolioModels:
    """포트폴리오 관련 모델 테스트"""

    def test_holding_item(self) -> None:
        item = HoldingItem(
            stock_code="005930",
            stock_name="삼성전자",
            quantity=10,
            avg_price=65000.0,
            current_price=68000.0,
            eval_amount=680000.0,
            profit_loss=30000.0,
            profit_loss_rate=4.62,
        )
        assert item.stock_code == "005930"
        assert item.profit_loss_rate == 4.62

    def test_portfolio_summary(self) -> None:
        s = PortfolioSummary(
            cash=5000000.0,
            total_eval=5920000.0,
            total_purchase=900000.0,
            total_profit_loss=20000.0,
            net_asset=5920000.0,
        )
        assert s.net_asset == 5920000.0

    def test_portfolio_response(self) -> None:
        r = PortfolioResponse(
            holdings=[],
            summary=PortfolioSummary(
                cash=0, total_eval=0, total_purchase=0,
                total_profit_loss=0, net_asset=0,
            ),
            updated_at="2026-02-13T12:00:00Z",
        )
        assert len(r.holdings) == 0


class TestOrderModels:
    """주문 관련 모델 테스트"""

    def test_order_request_market(self) -> None:
        req = OrderRequest(
            stock_code="005930",
            order_type=OrderType.BUY,
            quantity=10,
        )
        assert req.price is None

    def test_order_request_limit(self) -> None:
        req = OrderRequest(
            stock_code="005930",
            order_type=OrderType.SELL,
            quantity=5,
            price=70000,
        )
        assert req.price == 70000

    def test_order_response(self) -> None:
        r = OrderResponse(
            order_id="123456",
            stock_code="005930",
            order_type="buy",
            quantity=10,
            price="시장가",
            status="executed",
            ordered_at="2026-02-13T12:00:00",
        )
        assert r.order_id == "123456"

    def test_order_history_response_empty(self) -> None:
        r = OrderHistoryResponse(orders=[], total=0)
        assert r.page == 1
        assert r.size == 20


class TestSignalModels:
    """매매 신호 관련 모델 테스트"""

    def test_signal_request_defaults(self) -> None:
        req = SignalRequest(stock_code="005930")
        assert req.short_window == 5
        assert req.long_window == 20
        assert req.ma_type == MATypeEnum.SMA

    def test_signal_response(self) -> None:
        r = SignalResponse(
            stock_code="005930",
            signal="buy",
            strength=0.75,
            reason="골든크로스",
            strategy_name="MA_Crossover_SMA(5,20)",
            metrics=SignalMetrics(
                current_short_ma=67000,
                current_long_ma=65000,
                ma_spread=3.08,
                trend="uptrend",
                current_price=68000,
            ),
            timestamp="2026-02-13T12:00:00Z",
        )
        assert r.signal == "buy"
        assert r.metrics.trend == "uptrend"

    def test_signal_history_response_empty(self) -> None:
        r = SignalHistoryResponse(signals=[], total=0)
        assert r.total == 0

    def test_ma_type_enum(self) -> None:
        assert MATypeEnum.SMA.value == "sma"
        assert MATypeEnum.EMA.value == "ema"

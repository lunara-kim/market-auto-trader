"""
대시보드 API 엔드포인트 테스트

PnL, Performance, Summary 엔드포인트를 검증합니다.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.api.dashboard import _calculate_holdings_pnl
from src.api.dependencies import get_kis_client
from src.main import app

client = TestClient(app)


# ─────────────────── Helper ─────────────────────


def _create_mock_kis_client(
    stocks: list[dict] | None = None,
    summary: dict | None = None,
) -> MagicMock:
    """모킹된 KISClient"""
    kis = MagicMock()
    balance = {
        "stocks": stocks if stocks is not None else [
            {
                "stock_code": "005930",
                "stock_name": "삼성전자",
                "quantity": 10,
                "avg_price": 70000.0,
                "current_price": 72000.0,
            },
            {
                "stock_code": "000660",
                "stock_name": "SK하이닉스",
                "quantity": 5,
                "avg_price": 130000.0,
                "current_price": 125000.0,
            },
        ],
        "summary": summary if summary is not None else {
            "total_eval": 1345000.0,
            "total_purchase": 1350000.0,
            "cash": 500000.0,
        },
    }
    kis.get_balance.return_value = balance
    return kis


def _mock_kis_dependency(kis: MagicMock):  # noqa: ANN202
    """KISClient 의존성 오버라이드 제너레이터"""
    def _gen():  # type: ignore[no-untyped-def]
        yield kis
    return _gen


# ─────────────────── _calculate_holdings_pnl ─────────────────────


class TestCalculateHoldingsPnl:
    """보유종목별 PnL 계산 테스트"""

    def test_basic_calculation(self) -> None:
        """기본 계산"""
        stocks = [
            {
                "stock_code": "005930",
                "stock_name": "삼성전자",
                "quantity": 10,
                "avg_price": 70000.0,
                "current_price": 72000.0,
            },
        ]
        holdings = _calculate_holdings_pnl(stocks, total_eval=720000.0)

        assert len(holdings) == 1
        h = holdings[0]
        assert h.stock_code == "005930"
        assert h.current_price == 72000.0
        assert h.avg_price == 70000.0
        assert h.quantity == 10
        assert h.eval_amount == 720000.0
        assert h.purchase_amount == 700000.0
        assert h.profit_loss == 20000.0
        assert h.profit_loss_rate == pytest.approx(2.86, abs=0.01)
        assert h.weight == 100.0

    def test_loss_calculation(self) -> None:
        """손실 계산"""
        stocks = [
            {
                "stock_code": "000660",
                "stock_name": "SK하이닉스",
                "quantity": 5,
                "avg_price": 130000.0,
                "current_price": 125000.0,
            },
        ]
        holdings = _calculate_holdings_pnl(stocks, total_eval=625000.0)

        h = holdings[0]
        assert h.profit_loss == -25000.0
        assert h.profit_loss_rate < 0

    def test_zero_avg_price(self) -> None:
        """매입가 0인 경우"""
        stocks = [
            {
                "stock_code": "005930",
                "stock_name": "삼성전자",
                "quantity": 10,
                "avg_price": 0,
                "current_price": 72000.0,
            },
        ]
        holdings = _calculate_holdings_pnl(stocks, total_eval=720000.0)

        assert holdings[0].profit_loss_rate == 0.0

    def test_zero_total_eval(self) -> None:
        """총 평가금액 0인 경우"""
        stocks = [
            {
                "stock_code": "005930",
                "stock_name": "삼성전자",
                "quantity": 0,
                "avg_price": 70000.0,
                "current_price": 72000.0,
            },
        ]
        holdings = _calculate_holdings_pnl(stocks, total_eval=0)

        assert holdings[0].weight == 0.0

    def test_empty_stocks(self) -> None:
        """보유종목 없음"""
        holdings = _calculate_holdings_pnl([], total_eval=0)
        assert holdings == []

    def test_weight_calculation(self) -> None:
        """비중 계산"""
        stocks = [
            {
                "stock_code": "005930",
                "stock_name": "삼성전자",
                "quantity": 10,
                "avg_price": 70000.0,
                "current_price": 60000.0,
            },
            {
                "stock_code": "000660",
                "stock_name": "SK하이닉스",
                "quantity": 10,
                "avg_price": 40000.0,
                "current_price": 40000.0,
            },
        ]
        total_eval = 600000.0 + 400000.0
        holdings = _calculate_holdings_pnl(stocks, total_eval=total_eval)

        assert holdings[0].weight == 60.0
        assert holdings[1].weight == 40.0


# ─────────────────── PnL Endpoint ─────────────────────


class TestPnLEndpoint:
    """GET /api/v1/dashboard/pnl 테스트"""

    def test_get_pnl(self) -> None:
        """PnL 조회 성공"""
        kis = _create_mock_kis_client()
        app.dependency_overrides[get_kis_client] = _mock_kis_dependency(kis)

        try:
            response = client.get("/api/v1/dashboard/pnl")
            assert response.status_code == 200

            data = response.json()
            assert "holdings" in data
            assert len(data["holdings"]) == 2
            assert "total_eval_amount" in data
            assert "total_purchase_amount" in data
            assert "total_profit_loss" in data
            assert "total_profit_loss_rate" in data
            assert "daily_change" in data
            assert "updated_at" in data
        finally:
            app.dependency_overrides.pop(get_kis_client, None)

    def test_pnl_holding_fields(self) -> None:
        """PnL 보유종목 필드 확인"""
        kis = _create_mock_kis_client()
        app.dependency_overrides[get_kis_client] = _mock_kis_dependency(kis)

        try:
            response = client.get("/api/v1/dashboard/pnl")
            data = response.json()

            holding = data["holdings"][0]
            assert "stock_code" in holding
            assert "stock_name" in holding
            assert "current_price" in holding
            assert "avg_price" in holding
            assert "quantity" in holding
            assert "eval_amount" in holding
            assert "purchase_amount" in holding
            assert "profit_loss" in holding
            assert "profit_loss_rate" in holding
            assert "weight" in holding
        finally:
            app.dependency_overrides.pop(get_kis_client, None)

    def test_pnl_empty_portfolio(self) -> None:
        """빈 포트폴리오"""
        kis = _create_mock_kis_client(
            stocks=[],
            summary={"total_eval": 0, "total_purchase": 0, "cash": 1000000},
        )
        app.dependency_overrides[get_kis_client] = _mock_kis_dependency(kis)

        try:
            response = client.get("/api/v1/dashboard/pnl")
            assert response.status_code == 200

            data = response.json()
            assert data["holdings"] == []
            assert data["total_eval_amount"] == 0
            assert data["total_profit_loss_rate"] == 0
        finally:
            app.dependency_overrides.pop(get_kis_client, None)


# ─────────────────── Performance Endpoint ─────────────────────


class TestPerformanceEndpoint:
    """GET /api/v1/dashboard/performance 테스트"""

    def test_get_performance_daily(self) -> None:
        """일별 수익률 추이"""
        kis = _create_mock_kis_client()
        app.dependency_overrides[get_kis_client] = _mock_kis_dependency(kis)

        try:
            response = client.get("/api/v1/dashboard/performance?period=daily&days=30")
            assert response.status_code == 200

            data = response.json()
            assert data["period"] == "daily"
            assert "items" in data
            assert len(data["items"]) >= 1
            assert "start_date" in data
            assert "end_date" in data

            item = data["items"][0]
            assert "date" in item
            assert "total_eval" in item
            assert "profit_loss" in item
            assert "profit_loss_rate" in item
            assert "daily_return" in item
        finally:
            app.dependency_overrides.pop(get_kis_client, None)

    def test_get_performance_weekly(self) -> None:
        """주별 수익률 추이"""
        kis = _create_mock_kis_client()
        app.dependency_overrides[get_kis_client] = _mock_kis_dependency(kis)

        try:
            response = client.get("/api/v1/dashboard/performance?period=weekly")
            assert response.status_code == 200

            data = response.json()
            assert data["period"] == "weekly"
        finally:
            app.dependency_overrides.pop(get_kis_client, None)

    def test_get_performance_invalid_period(self) -> None:
        """잘못된 기간"""
        kis = _create_mock_kis_client()
        app.dependency_overrides[get_kis_client] = _mock_kis_dependency(kis)

        try:
            response = client.get("/api/v1/dashboard/performance?period=invalid")
            assert response.status_code == 422
        finally:
            app.dependency_overrides.pop(get_kis_client, None)

    def test_get_performance_default_params(self) -> None:
        """기본 파라미터"""
        kis = _create_mock_kis_client()
        app.dependency_overrides[get_kis_client] = _mock_kis_dependency(kis)

        try:
            response = client.get("/api/v1/dashboard/performance")
            assert response.status_code == 200

            data = response.json()
            assert data["period"] == "daily"
        finally:
            app.dependency_overrides.pop(get_kis_client, None)


# ─────────────────── Summary Endpoint ─────────────────────


class TestSummaryEndpoint:
    """GET /api/v1/dashboard/summary 테스트"""

    def test_get_summary(self) -> None:
        """대시보드 요약 조회"""
        kis = _create_mock_kis_client()
        app.dependency_overrides[get_kis_client] = _mock_kis_dependency(kis)

        try:
            response = client.get("/api/v1/dashboard/summary")
            assert response.status_code == 200

            data = response.json()
            assert "total_eval_amount" in data
            assert "total_purchase_amount" in data
            assert "total_profit_loss" in data
            assert "total_profit_loss_rate" in data
            assert "cash" in data
            assert "net_asset" in data
            assert "holding_count" in data
            assert "profit_count" in data
            assert "loss_count" in data
            assert "even_count" in data
            assert "top_holdings" in data
            assert "daily_change" in data
            assert "updated_at" in data
        finally:
            app.dependency_overrides.pop(get_kis_client, None)

    def test_summary_holding_counts(self) -> None:
        """종목 수 확인"""
        kis = _create_mock_kis_client()
        app.dependency_overrides[get_kis_client] = _mock_kis_dependency(kis)

        try:
            response = client.get("/api/v1/dashboard/summary")
            data = response.json()

            assert data["holding_count"] == 2
            # 삼성전자: 수익, SK하이닉스: 손실
            assert data["profit_count"] == 1
            assert data["loss_count"] == 1
            assert data["even_count"] == 0
        finally:
            app.dependency_overrides.pop(get_kis_client, None)

    def test_summary_net_asset(self) -> None:
        """순자산 계산"""
        kis = _create_mock_kis_client()
        app.dependency_overrides[get_kis_client] = _mock_kis_dependency(kis)

        try:
            response = client.get("/api/v1/dashboard/summary")
            data = response.json()

            # net_asset = total_eval + cash = 1345000 + 500000
            assert data["net_asset"] == 1845000.0
        finally:
            app.dependency_overrides.pop(get_kis_client, None)

    def test_summary_top_holdings(self) -> None:
        """상위 보유종목"""
        kis = _create_mock_kis_client()
        app.dependency_overrides[get_kis_client] = _mock_kis_dependency(kis)

        try:
            response = client.get("/api/v1/dashboard/summary")
            data = response.json()

            assert len(data["top_holdings"]) <= 5
            assert len(data["top_holdings"]) == 2
        finally:
            app.dependency_overrides.pop(get_kis_client, None)

    def test_summary_empty_portfolio(self) -> None:
        """빈 포트폴리오"""
        kis = _create_mock_kis_client(
            stocks=[],
            summary={"total_eval": 0, "total_purchase": 0, "cash": 1000000},
        )
        app.dependency_overrides[get_kis_client] = _mock_kis_dependency(kis)

        try:
            response = client.get("/api/v1/dashboard/summary")
            assert response.status_code == 200

            data = response.json()
            assert data["holding_count"] == 0
            assert data["profit_count"] == 0
            assert data["loss_count"] == 0
            assert data["net_asset"] == 1000000.0
        finally:
            app.dependency_overrides.pop(get_kis_client, None)

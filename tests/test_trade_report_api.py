"""
src/api/trade_report.py API 엔드포인트 테스트
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.dependencies import get_kis_client
from src.broker.kis_client import KISClient
from src.db import get_session_factory
from src.main import app
from src.models.schema import Base, Order


# ───────────────────── Fixtures ─────────────────────


@pytest.fixture
def test_db_session():
    """테스트용 SQLite in-memory DB 세션"""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    TestSessionFactory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )

    yield TestSessionFactory

    Base.metadata.drop_all(engine)


@pytest.fixture
def mock_kis_client():
    """Mock KISClient"""
    client = MagicMock(spec=KISClient)
    client.get_balance.return_value = {
        "stocks": [
            {
                "stock_code": "005930",
                "stock_name": "삼성전자",
                "quantity": 10,
                "avg_price": 70000,
                "current_price": 72000,
            },
            {
                "stock_code": "000660",
                "stock_name": "SK하이닉스",
                "quantity": 5,
                "avg_price": 120000,
                "current_price": 115000,
            },
        ],
    }
    return client


@pytest.fixture
def client(test_db_session, mock_kis_client):
    """TestClient with dependency overrides"""
    app.dependency_overrides[get_session_factory] = lambda: test_db_session
    app.dependency_overrides[get_kis_client] = lambda: mock_kis_client

    yield TestClient(app)

    app.dependency_overrides.clear()


@pytest.fixture
def sample_orders(test_db_session):
    """테스트용 샘플 주문 데이터 생성"""
    session = test_db_session()

    # 2026-02-15 주문
    orders = [
        Order(
            stock_code="005930",
            stock_name="삼성전자",
            order_type="buy",
            quantity=10,
            order_price=70000,
            status="executed",
            executed_price=70000,
            executed_at=datetime(2026, 2, 15, 9, 30, tzinfo=timezone.utc),
            created_at=datetime(2026, 2, 15, 9, 30, tzinfo=timezone.utc),
        ),
        Order(
            stock_code="000660",
            stock_name="SK하이닉스",
            order_type="buy",
            quantity=5,
            order_price=120000,
            status="executed",
            executed_price=120000,
            executed_at=datetime(2026, 2, 15, 10, 0, tzinfo=timezone.utc),
            created_at=datetime(2026, 2, 15, 10, 0, tzinfo=timezone.utc),
        ),
        Order(
            stock_code="005930",
            stock_name="삼성전자",
            order_type="sell",
            quantity=5,
            order_price=72000,
            status="executed",
            executed_price=72000,
            executed_at=datetime(2026, 2, 15, 14, 0, tzinfo=timezone.utc),
            created_at=datetime(2026, 2, 15, 14, 0, tzinfo=timezone.utc),
        ),
        Order(
            stock_code="035720",
            stock_name="카카오",
            order_type="buy",
            quantity=20,
            order_price=50000,
            status="pending",
            executed_price=None,
            executed_at=None,
            created_at=datetime(2026, 2, 15, 15, 0, tzinfo=timezone.utc),
        ),
    ]

    for order in orders:
        session.add(order)

    session.commit()
    session.close()


# ───────────────────── API 테스트 ─────────────────────


def test_get_daily_report_basic(client: TestClient, sample_orders) -> None:
    """일일 리포트 조회 - 기본"""
    response = client.get("/api/v1/report/daily?date=2026-02-15")

    assert response.status_code == 200
    data = response.json()

    assert "summary" in data
    assert "realized_pnl" in data
    assert "text_report" in data

    summary = data["summary"]
    assert summary["date"] == "2026-02-15"
    assert summary["total_orders"] == 4
    assert summary["executed_orders"] == 3
    assert summary["buy_count"] == 2
    assert summary["sell_count"] == 1


def test_get_daily_report_amounts(client: TestClient, sample_orders) -> None:
    """일일 리포트 조회 - 거래 금액 확인"""
    response = client.get("/api/v1/report/daily?date=2026-02-15")

    assert response.status_code == 200
    data = response.json()

    summary = data["summary"]
    # 매수: 70000*10 + 120000*5 = 1,300,000
    assert summary["total_buy_amount"] == 1_300_000
    # 매도: 72000*5 = 360,000
    assert summary["total_sell_amount"] == 360_000


def test_get_daily_report_no_date_param(client: TestClient, sample_orders) -> None:
    """일일 리포트 조회 - 날짜 미지정 (오늘)"""
    response = client.get("/api/v1/report/daily")

    assert response.status_code == 200
    data = response.json()

    assert "summary" in data
    # 오늘 날짜와 비교
    today = datetime.now().date().isoformat()
    assert data["summary"]["date"] == today


def test_get_daily_report_realized_pnl(client: TestClient, sample_orders) -> None:
    """일일 리포트 조회 - 실현 손익 확인"""
    response = client.get("/api/v1/report/daily?date=2026-02-15")

    assert response.status_code == 200
    data = response.json()

    pnl = data["realized_pnl"]
    assert "total_realized_pnl" in pnl
    assert "by_stock" in pnl

    # 005930: 매수 700000, 매도 360000 → -340000
    assert pnl["by_stock"]["005930"]["buy_amount"] == 700_000
    assert pnl["by_stock"]["005930"]["sell_amount"] == 360_000
    assert pnl["by_stock"]["005930"]["realized_pnl"] == -340_000


def test_get_portfolio_snapshot_basic(client: TestClient, mock_kis_client: MagicMock) -> None:
    """포트폴리오 스냅샷 조회 - 기본"""
    response = client.get("/api/v1/report/portfolio")

    assert response.status_code == 200
    data = response.json()

    assert "holdings" in data
    assert "total_evaluation" in data
    assert "total_profit_loss" in data

    assert len(data["holdings"]) == 2


def test_get_portfolio_snapshot_calculations(
    client: TestClient,
    mock_kis_client: MagicMock,
) -> None:
    """포트폴리오 스냅샷 조회 - 계산 확인"""
    response = client.get("/api/v1/report/portfolio")

    assert response.status_code == 200
    data = response.json()

    holdings = data["holdings"]

    # 삼성전자
    samsung = holdings[0]
    assert samsung["stock_code"] == "005930"
    assert samsung["stock_name"] == "삼성전자"
    assert samsung["quantity"] == 10
    assert samsung["avg_price"] == 70000
    assert samsung["current_price"] == 72000
    assert samsung["evaluation"] == 720_000
    assert samsung["profit_loss"] == 20_000
    assert samsung["profit_loss_rate"] == 2.86

    # SK하이닉스
    sk = holdings[1]
    assert sk["stock_code"] == "000660"
    assert sk["evaluation"] == 575_000
    assert sk["profit_loss"] == -25_000
    assert sk["profit_loss_rate"] == -4.17


def test_get_portfolio_snapshot_totals(
    client: TestClient,
    mock_kis_client: MagicMock,
) -> None:
    """포트폴리오 스냅샷 조회 - 합계 확인"""
    response = client.get("/api/v1/report/portfolio")

    assert response.status_code == 200
    data = response.json()

    # 총 평가: 720000 + 575000 = 1,295,000
    assert data["total_evaluation"] == 1_295_000

    # 총 손익: 20000 + (-25000) = -5,000
    assert data["total_profit_loss"] == -5_000


def test_get_portfolio_snapshot_empty(client: TestClient, mock_kis_client: MagicMock) -> None:
    """포트폴리오 스냅샷 조회 - 빈 포트폴리오"""
    mock_kis_client.get_balance.return_value = {"stocks": []}

    response = client.get("/api/v1/report/portfolio")

    assert response.status_code == 200
    data = response.json()

    assert data["holdings"] == []
    assert data["total_evaluation"] == 0
    assert data["total_profit_loss"] == 0

"""
데이터 파이프라인 API 테스트

FastAPI 엔드포인트를 테스트합니다.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.main import app
from src.models.schema import Base, MarketData


# ───────────────────── Fixtures ─────────────────────


@pytest.fixture
def test_engine():
    """인메모리 SQLite DB 엔진 (StaticPool로 연결 공유)"""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def session_factory(test_engine):
    """테스트용 세션 팩토리"""
    return sessionmaker(bind=test_engine)


@pytest.fixture
def client(session_factory):
    """FastAPI 테스트 클라이언트"""
    from src.api.dependencies import get_kis_client
    from src.broker.kis_client import KISClient
    from src.db import get_session_factory

    mock_client = MagicMock(spec=KISClient)
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    app.dependency_overrides[get_kis_client] = lambda: mock_client
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def mock_kis_client():
    """KISClient 모킹 (app.dependency_overrides 경유)"""
    from src.api.dependencies import get_kis_client
    from src.broker.kis_client import KISClient

    mock_client = MagicMock(spec=KISClient)
    app.dependency_overrides[get_kis_client] = lambda: mock_client
    yield mock_client
    app.dependency_overrides.pop(get_kis_client, None)


@pytest.fixture
def sample_data(session_factory):
    """샘플 시세 데이터 (DB에 미리 저장)"""
    with session_factory() as session:
        data_list = [
            MarketData(
                stock_code="005930",
                date=datetime(2026, 2, 17),
                open_price=71000.0,
                high_price=71800.0,
                low_price=70800.0,
                close_price=71500.0,
                volume=10234567,
            ),
            MarketData(
                stock_code="005930",
                date=datetime(2026, 2, 18),
                open_price=71500.0,
                high_price=72200.0,
                low_price=71300.0,
                close_price=72000.0,
                volume=11234567,
            ),
            MarketData(
                stock_code="005930",
                date=datetime(2026, 2, 19),
                open_price=72000.0,
                high_price=72500.0,
                low_price=71800.0,
                close_price=72300.0,
                volume=12345678,
            ),
        ]
        for data in data_list:
            session.add(data)
        session.commit()


# ───────────────────── Tests: POST /api/v1/data/collect ─────────────────────


def test_collect_data_success(client, mock_kis_client):
    """데이터 수집 성공"""
    # MarketDataCollector.fetch_stock_price 모킹
    with patch("src.data.collector.MarketDataCollector.fetch_stock_price") as mock_fetch:
        mock_fetch.return_value = [
            {
                "date": "2026-02-17",
                "open": 71000,
                "high": 71800,
                "low": 70800,
                "close": 71500,
                "volume": 10234567,
            },
        ]

        response = client.post(
            "/api/v1/data/collect",
            json={
                "stock_codes": ["005930"],
                "start_date": "2026-02-17",
                "end_date": "2026-02-17",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success_count"] == 1
    assert data["fail_count"] == 0
    assert data["skipped_count"] == 0


def test_collect_data_validation_error(client):
    """잘못된 요청 (빈 종목 리스트)"""
    response = client.post(
        "/api/v1/data/collect",
        json={
            "stock_codes": [],  # 빈 리스트
            "start_date": "2026-02-17",
            "end_date": "2026-02-17",
        },
    )

    assert response.status_code == 422


def test_collect_data_skip_duplicates(client, mock_kis_client, sample_data):
    """중복 데이터는 스킵"""
    with patch("src.data.collector.MarketDataCollector.fetch_stock_price") as mock_fetch:
        mock_fetch.return_value = [
            {
                "date": "2026-02-17",
                "open": 71000,
                "high": 71800,
                "low": 70800,
                "close": 71500,
                "volume": 10234567,
            },
        ]

        response = client.post(
            "/api/v1/data/collect",
            json={
                "stock_codes": ["005930"],
                "start_date": "2026-02-17",
                "end_date": "2026-02-17",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success_count"] == 0
    assert data["skipped_count"] == 1


# ───────────────────── Tests: GET /api/v1/data/cache/stats ─────────────────────


def test_get_cache_stats_empty(client):
    """빈 캐시 통계"""
    response = client.get("/api/v1/data/cache/stats")

    assert response.status_code == 200
    data = response.json()
    assert data["total_records"] == 0
    assert data["stock_count"] == 0
    assert data["by_stock"] == {}


def test_get_cache_stats_with_data(client, sample_data):
    """캐시 통계 조회"""
    response = client.get("/api/v1/data/cache/stats")

    assert response.status_code == 200
    data = response.json()
    assert data["total_records"] == 3
    assert data["stock_count"] == 1
    assert data["by_stock"]["005930"] == 3


# ───────────────────── Tests: GET /api/v1/data/quality/{stock_code} ─────────────────────


def test_get_quality_report_no_data(client):
    """데이터 없는 종목 품질 리포트"""
    response = client.get(
        "/api/v1/data/quality/999999",
        params={
            "start_date": "2026-02-17",
            "end_date": "2026-02-19",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["stock_code"] == "999999"
    assert data["total_records"] == 0
    assert len(data["issues"]) == 0


def test_get_quality_report_with_data(client, sample_data):
    """정상 데이터 품질 리포트"""
    response = client.get(
        "/api/v1/data/quality/005930",
        params={
            "start_date": "2026-02-17",
            "end_date": "2026-02-19",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["stock_code"] == "005930"
    assert data["total_records"] == 3
    assert data["summary"]["total_issues"] >= 0


def test_get_quality_report_default_dates(client, sample_data):
    """날짜 미지정 시 기본값 (당월)"""
    response = client.get("/api/v1/data/quality/005930")

    assert response.status_code == 200
    data = response.json()
    assert data["stock_code"] == "005930"


def test_get_quality_report_invalid_data(client, session_factory):
    """잘못된 데이터 품질 이슈 감지"""
    # 잘못된 데이터 삽입 (high < low)
    with session_factory() as session:
        invalid_data = MarketData(
            stock_code="999999",
            date=datetime(2026, 2, 17),
            open_price=71000.0,
            high_price=70000.0,  # 고가 < 저가
            low_price=71000.0,
            close_price=70500.0,
            volume=10234567,
        )
        session.add(invalid_data)
        session.commit()

    response = client.get(
        "/api/v1/data/quality/999999",
        params={
            "start_date": "2026-02-17",
            "end_date": "2026-02-17",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total_records"] == 1
    assert len(data["issues"]) >= 1
    assert data["summary"]["critical"] >= 1


# ───────────────────── Tests: DELETE /api/v1/data/cache/{stock_code} ─────────────────────


def test_invalidate_cache_all(client, sample_data):
    """전체 캐시 무효화"""
    response = client.delete("/api/v1/data/cache/005930")

    assert response.status_code == 200
    data = response.json()
    assert data["deleted_count"] == 3

    # DB 확인
    stats_response = client.get("/api/v1/data/cache/stats")
    stats = stats_response.json()
    assert stats["total_records"] == 0


def test_invalidate_cache_range(client, sample_data):
    """특정 기간만 무효화"""
    response = client.delete(
        "/api/v1/data/cache/005930",
        params={
            "start_date": "2026-02-18",
            "end_date": "2026-02-18",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["deleted_count"] == 1

    # DB 확인 (2건 남음)
    stats_response = client.get("/api/v1/data/cache/stats")
    stats = stats_response.json()
    assert stats["total_records"] == 2


def test_invalidate_cache_no_match(client):
    """존재하지 않는 종목 무효화"""
    response = client.delete("/api/v1/data/cache/999999")

    assert response.status_code == 200
    data = response.json()
    assert data["deleted_count"] == 0

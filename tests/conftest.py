"""
테스트 공통 Fixture 정의

pytest conftest.py - 모든 테스트에서 공유하는 fixture들을 정의합니다.
"""

import pytest
from fastapi.testclient import TestClient
from src.main import app
from src.broker.kis_client import KISClient
from src.data.collector import MarketDataCollector


@pytest.fixture
def client():
    """FastAPI 테스트 클라이언트"""
    return TestClient(app)


@pytest.fixture
def kis_client():
    """KISClient 테스트 인스턴스 (모의투자 모드)"""
    return KISClient(
        app_key="test_app_key",
        app_secret="test_app_secret",
        account_no="12345678-01",
        mock=True,
    )


@pytest.fixture
def kis_client_real():
    """KISClient 테스트 인스턴스 (실전 모드)"""
    return KISClient(
        app_key="real_app_key",
        app_secret="real_app_secret",
        account_no="99999999-01",
        mock=False,
    )


@pytest.fixture
def collector():
    """MarketDataCollector 테스트 인스턴스"""
    return MarketDataCollector()

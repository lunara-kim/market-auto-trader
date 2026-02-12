"""
헬스 체크 엔드포인트 테스트
"""

from fastapi.testclient import TestClient

from src.main import app

client = TestClient(app)


def test_health_check():
    """헬스 체크 엔드포인트가 정상 동작하는지 확인"""
    response = client.get("/health")
    assert response.status_code == 200

    data = response.json()
    assert "status" in data
    assert data["status"] == "ok"
    assert "env" in data


def test_portfolio_not_implemented():
    """포트폴리오 엔드포인트가 501을 반환하는지 확인"""
    response = client.get("/api/v1/portfolio")
    assert response.status_code == 501

    data = response.json()
    assert "status" in data
    assert data["status"] == "not_implemented"


def test_signal_not_implemented():
    """신호 생성 엔드포인트가 501을 반환하는지 확인"""
    response = client.post("/api/v1/signal")
    assert response.status_code == 501

    data = response.json()
    assert "status" in data
    assert data["status"] == "not_implemented"

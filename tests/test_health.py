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
    assert data["status"] == "ok"
    assert "version" in data
    assert "env" in data


def test_portfolio_returns_error():
    """포트폴리오 엔드포인트가 일관된 에러 형식을 반환하는지 확인"""
    response = client.get("/api/v1/portfolio")
    assert response.status_code == 404

    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "NOT_FOUND"
    assert "message" in data["error"]


def test_signal_returns_error():
    """신호 생성 엔드포인트가 일관된 에러 형식을 반환하는지 확인"""
    response = client.post("/api/v1/signal")
    assert response.status_code == 404

    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "NOT_FOUND"

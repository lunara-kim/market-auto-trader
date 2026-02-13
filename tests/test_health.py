"""
헬스 체크 및 기본 라우트 테스트
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


def test_health_response_schema():
    """헬스 체크 응답이 스키마를 따르는지 확인"""
    response = client.get("/health")
    data = response.json()
    assert data["version"] == "0.3.0"
    assert data["env"] in ("development", "production", "test")


def test_portfolio_requires_credentials():
    """포트폴리오 엔드포인트 — 인증 미설정 시 에러"""
    response = client.get("/api/v1/portfolio")
    # KIS 인증 정보 미설정 → ValidationError (422)
    assert response.status_code == 422
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "VALIDATION_ERROR"


def test_signals_post_requires_body():
    """신호 생성 — 요청 본문 없이 호출 시 에러"""
    response = client.post("/api/v1/signals")
    assert response.status_code == 422  # FastAPI validation


def test_nonexistent_route_returns_500():
    """존재하지 않는 라우트 → 안전한 에러 응답"""
    response = client.get("/api/v1/nonexistent")
    # 우리의 unhandled_error_handler가 500으로 처리하거나 404
    assert response.status_code in (404, 500)


def test_openapi_schema_available():
    """OpenAPI 스키마 접근 가능"""
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "Market Auto Trader"
    assert schema["info"]["version"] == "0.3.0"


def test_swagger_ui_available():
    """Swagger UI 접근 가능"""
    response = client.get("/docs")
    assert response.status_code == 200


def test_redoc_available():
    """ReDoc 접근 가능"""
    response = client.get("/redoc")
    assert response.status_code == 200


def test_openapi_tags():
    """OpenAPI 태그 정의 확인"""
    response = client.get("/openapi.json")
    schema = response.json()
    tag_names = [t["name"] for t in schema.get("tags", [])]
    assert "System" in tag_names
    assert "Portfolio" in tag_names
    assert "Orders" in tag_names
    assert "Signals" in tag_names

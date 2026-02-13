"""
헬스 체크 및 API 라우트 통합 테스트

FastAPI TestClient를 사용하여 각 엔드포인트의 응답 코드,
응답 구조, OpenAPI 문서 정상 생성 여부를 검증합니다.
"""


class TestHealthEndpoint:
    """헬스 체크 엔드포인트 테스트"""

    def test_health_check_status(self, client):
        """헬스 체크가 200 OK를 반환하는지 확인"""
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_check_body(self, client):
        """헬스 체크 응답에 status=ok과 env 필드가 있는지 확인"""
        data = client.get("/health").json()
        assert data["status"] == "ok"
        assert "env" in data

    def test_health_check_response_keys(self, client):
        """헬스 체크 응답이 정확히 status, env 키만 포함하는지 확인"""
        data = client.get("/health").json()
        assert set(data.keys()) == {"status", "env"}


class TestPortfolioEndpoint:
    """포트폴리오 엔드포인트 테스트"""

    def test_portfolio_returns_501(self, client):
        """포트폴리오 엔드포인트가 501을 반환하는지 확인"""
        response = client.get("/api/v1/portfolio")
        assert response.status_code == 501

    def test_portfolio_response_body(self, client):
        """포트폴리오 응답에 message, status 필드 확인"""
        data = client.get("/api/v1/portfolio").json()
        assert "message" in data
        assert data["status"] == "not_implemented"


class TestSignalEndpoint:
    """매매 신호 엔드포인트 테스트"""

    def test_signal_returns_501(self, client):
        """신호 생성 엔드포인트가 501을 반환하는지 확인"""
        response = client.post("/api/v1/signal")
        assert response.status_code == 501

    def test_signal_response_body(self, client):
        """신호 응답에 message, status 필드 확인"""
        data = client.post("/api/v1/signal").json()
        assert "message" in data
        assert data["status"] == "not_implemented"


class TestOpenAPIDocs:
    """OpenAPI 문서 테스트"""

    def test_openapi_schema_available(self, client):
        """OpenAPI 스키마가 정상 생성되는지 확인"""
        response = client.get("/openapi.json")
        assert response.status_code == 200
        schema = response.json()
        assert schema["info"]["title"] == "Market Auto Trader"
        assert schema["info"]["version"] == "0.1.0"

    def test_openapi_has_tags(self, client):
        """OpenAPI 스키마에 태그가 정의되어 있는지 확인"""
        schema = client.get("/openapi.json").json()
        tag_names = [t["name"] for t in schema.get("tags", [])]
        assert "System" in tag_names
        assert "Portfolio" in tag_names
        assert "Signal" in tag_names

    def test_docs_page_accessible(self, client):
        """Swagger UI (/docs) 페이지가 접근 가능한지 확인"""
        response = client.get("/docs")
        assert response.status_code == 200

    def test_redoc_page_accessible(self, client):
        """ReDoc (/redoc) 페이지가 접근 가능한지 확인"""
        response = client.get("/redoc")
        assert response.status_code == 200

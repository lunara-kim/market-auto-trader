"""
커스텀 예외 및 에러 핸들러 테스트
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.exceptions import (
    AppError,
    BrokerAuthError,
    BrokerError,
    InsufficientFundsError,
    NotFoundError,
    OrderError,
    StrategyError,
    ValidationError,
    register_exception_handlers,
)


def _make_app_with_route(exc: Exception) -> TestClient:
    """테스트용 앱을 생성하고, /test 에서 주어진 예외를 발생시킨다."""
    test_app = FastAPI()
    register_exception_handlers(test_app)

    @test_app.get("/test")
    async def _raise():
        raise exc

    return TestClient(test_app, raise_server_exceptions=False)


# ────────────── 예외 클래스 기본 동작 ──────────────


class TestExceptionClasses:
    def test_app_error_defaults(self):
        err = AppError()
        assert err.status_code == 500
        assert err.code == "INTERNAL_ERROR"
        assert "내부 오류" in err.message

    def test_custom_message(self):
        err = NotFoundError("종목을 찾을 수 없습니다.")
        assert err.message == "종목을 찾을 수 없습니다."
        assert err.status_code == 404

    def test_detail_kwarg(self):
        err = ValidationError(detail={"field": "stock_code"})
        assert err.detail == {"field": "stock_code"}

    def test_inheritance(self):
        """BrokerAuthError → BrokerError → AppError"""
        err = BrokerAuthError()
        assert isinstance(err, BrokerError)
        assert isinstance(err, AppError)

    def test_all_status_codes(self):
        cases = [
            (NotFoundError(), 404),
            (ValidationError(), 422),
            (BrokerError(), 502),
            (BrokerAuthError(), 401),
            (StrategyError(), 500),
            (OrderError(), 400),
            (InsufficientFundsError(), 400),
        ]
        for exc, expected_code in cases:
            assert exc.status_code == expected_code, f"{exc.__class__.__name__}"


# ────────────── FastAPI 핸들러 통합 ──────────────


class TestExceptionHandlers:
    def test_not_found_response(self):
        client = _make_app_with_route(NotFoundError("없음"))
        resp = client.get("/test")
        assert resp.status_code == 404
        body = resp.json()
        assert body["error"]["code"] == "NOT_FOUND"
        assert body["error"]["message"] == "없음"

    def test_broker_error_response(self):
        client = _make_app_with_route(
            BrokerError(detail={"api": "get_balance"})
        )
        resp = client.get("/test")
        assert resp.status_code == 502
        assert resp.json()["error"]["detail"]["api"] == "get_balance"

    def test_unhandled_exception_returns_500(self):
        client = _make_app_with_route(RuntimeError("boom"))
        resp = client.get("/test")
        assert resp.status_code == 500
        body = resp.json()
        assert body["error"]["code"] == "INTERNAL_ERROR"
        # 내부 오류 메시지는 노출하지 않음
        assert "boom" not in body["error"]["message"]

    def test_error_body_no_detail_when_none(self):
        client = _make_app_with_route(NotFoundError())
        resp = client.get("/test")
        body = resp.json()
        assert "detail" not in body["error"]

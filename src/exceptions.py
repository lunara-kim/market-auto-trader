"""
커스텀 예외 클래스 및 FastAPI 예외 핸들러

모든 비즈니스 예외는 AppError를 상속하며,
HTTP 응답은 일관된 JSON 형식으로 반환됩니다.

응답 형식::

    {
        "error": {
            "code": "NOT_FOUND",
            "message": "요청한 리소스를 찾을 수 없습니다.",
            "detail": { ... }  // optional
        }
    }
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


# ───────────────────────── Base ─────────────────────────


class AppError(Exception):
    """애플리케이션 최상위 예외"""

    status_code: int = 500
    code: str = "INTERNAL_ERROR"
    message: str = "서버 내부 오류가 발생했습니다."

    def __init__(
        self,
        message: str | None = None,
        *,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.__class__.message
        self.detail = detail
        super().__init__(self.message)


# ───────────────────── Concrete Errors ──────────────────


class NotFoundError(AppError):
    """리소스를 찾을 수 없음 (404)"""

    status_code = 404
    code = "NOT_FOUND"
    message = "요청한 리소스를 찾을 수 없습니다."


class ValidationError(AppError):
    """입력 검증 실패 (422)"""

    status_code = 422
    code = "VALIDATION_ERROR"
    message = "입력 데이터가 유효하지 않습니다."


class BrokerError(AppError):
    """한국투자증권 API 관련 오류 (502)"""

    status_code = 502
    code = "BROKER_ERROR"
    message = "증권사 API 요청에 실패했습니다."


class BrokerAuthError(BrokerError):
    """증권사 인증 실패 (401)"""

    status_code = 401
    code = "BROKER_AUTH_ERROR"
    message = "증권사 API 인증에 실패했습니다."


class StrategyError(AppError):
    """매매 전략 실행 오류 (500)"""

    status_code = 500
    code = "STRATEGY_ERROR"
    message = "매매 전략 실행 중 오류가 발생했습니다."


class DataCollectionError(AppError):
    """시장 데이터 수집 오류 (502)"""

    status_code = 502
    code = "DATA_COLLECTION_ERROR"
    message = "시장 데이터 수집에 실패했습니다."


class DataPipelineError(AppError):
    """데이터 파이프라인 실행 오류 (500)"""

    status_code = 500
    code = "DATA_PIPELINE_ERROR"
    message = "데이터 파이프라인 실행 중 오류가 발생했습니다."


class OrderError(AppError):
    """주문 처리 오류 (400)"""

    status_code = 400
    code = "ORDER_ERROR"
    message = "주문 처리에 실패했습니다."


class DuplicateOrderError(OrderError):
    """중복 주문 (409)"""

    status_code = 409
    code = "DUPLICATE_ORDER"
    message = "동일한 주문이 이미 존재합니다."


class InsufficientFundsError(OrderError):
    """잔고 부족 (400)"""

    status_code = 400
    code = "INSUFFICIENT_FUNDS"
    message = "주문에 필요한 잔고가 부족합니다."


class AlertError(AppError):
    """알림 관련 오류 (400)"""

    status_code = 400
    code = "ALERT_ERROR"
    message = "알림 처리에 실패했습니다."


# ──────────────────── Exception Handlers ────────────────


def _error_body(code: str, message: str, detail: Any = None) -> dict:
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    if detail is not None:
        body["error"]["detail"] = detail
    return body


async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    """AppError 계열 예외를 일관된 JSON으로 변환"""
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_body(exc.code, exc.message, exc.detail),
    )


async def unhandled_error_handler(
    _request: Request, _exc: Exception
) -> JSONResponse:
    """예상치 못한 예외에 대한 안전한 500 응답"""
    return JSONResponse(
        status_code=500,
        content=_error_body("INTERNAL_ERROR", "서버 내부 오류가 발생했습니다."),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """FastAPI 앱에 예외 핸들러를 등록합니다."""
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_error_handler)

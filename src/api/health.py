"""
고도화된 헬스체크 엔드포인트

단순 "ok" 응답이 아닌, 실제 의존 서비스 상태까지 점검합니다:
- DB 연결 상태 (PostgreSQL ping)
- 한투 API 연결 상태 (선택적)
- 시스템 정보 (업타임, 메모리 등)
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import text

from config.settings import settings
from src.db import engine
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["System"])

# 앱 시작 시각 (업타임 계산용)
_app_start_time: float = time.monotonic()
_app_start_datetime: datetime = datetime.now(UTC)


class ComponentStatus(str, Enum):
    """개별 컴포넌트 상태"""

    UP = "up"
    DOWN = "down"
    DEGRADED = "degraded"
    UNCONFIGURED = "unconfigured"


class OverallStatus(str, Enum):
    """전체 서비스 상태"""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class ComponentHealth(BaseModel):
    """개별 컴포넌트 상태 상세"""

    status: ComponentStatus
    latency_ms: float | None = Field(default=None, description="응답 시간 (ms)")
    message: str | None = Field(default=None, description="상태 메시지")
    details: dict[str, Any] | None = Field(default=None, description="추가 정보")


class DetailedHealthResponse(BaseModel):
    """상세 헬스체크 응답"""

    status: OverallStatus = Field(description="전체 상태")
    version: str = Field(description="앱 버전")
    env: str = Field(description="실행 환경")
    uptime_seconds: float = Field(description="업타임 (초)")
    started_at: str = Field(description="시작 시각 (ISO 8601)")
    checked_at: str = Field(description="점검 시각 (ISO 8601)")
    components: dict[str, ComponentHealth] = Field(description="컴포넌트별 상태")


async def _check_database() -> ComponentHealth:
    """PostgreSQL DB 연결 상태 확인"""
    start = time.monotonic()
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            row = result.scalar()
            if row != 1:  # pragma: no cover
                return ComponentHealth(
                    status=ComponentStatus.DEGRADED,
                    latency_ms=round((time.monotonic() - start) * 1000, 2),
                    message="DB 응답이 예상과 다릅니다",
                )

        latency = round((time.monotonic() - start) * 1000, 2)
        return ComponentHealth(
            status=ComponentStatus.UP,
            latency_ms=latency,
            message="PostgreSQL 정상",
            details={
                "pool_size": engine.pool.size(),
                "checked_in": engine.pool.checkedin(),
                "checked_out": engine.pool.checkedout(),
                "overflow": engine.pool.overflow(),
            },
        )
    except Exception as e:
        latency = round((time.monotonic() - start) * 1000, 2)
        logger.warning("DB 헬스체크 실패: %s", e)
        return ComponentHealth(
            status=ComponentStatus.DOWN,
            latency_ms=latency,
            message=f"DB 연결 실패: {type(e).__name__}",
        )


def _check_broker() -> ComponentHealth:
    """한투 API 설정 상태 확인 (실제 API 호출은 하지 않음)

    실제 토큰 발급 호출은 rate limit (1분당 1회)이 있으므로
    헬스체크에서는 설정값 존재 여부만 확인합니다.
    """
    has_key = bool(settings.kis_app_key)
    has_secret = bool(settings.kis_app_secret)
    has_account = bool(settings.kis_account_no)

    if not any([has_key, has_secret, has_account]):
        return ComponentHealth(
            status=ComponentStatus.UNCONFIGURED,
            message="한투 API 키가 설정되지 않았습니다",
            details={
                "app_key": has_key,
                "app_secret": has_secret,
                "account_no": has_account,
                "mock_mode": settings.kis_mock,
            },
        )

    if not all([has_key, has_secret, has_account]):
        return ComponentHealth(
            status=ComponentStatus.DEGRADED,
            message="한투 API 설정이 불완전합니다",
            details={
                "app_key": has_key,
                "app_secret": has_secret,
                "account_no": has_account,
                "mock_mode": settings.kis_mock,
            },
        )

    return ComponentHealth(
        status=ComponentStatus.UP,
        message=f"한투 API 설정 완료 ({'모의투자' if settings.kis_mock else '실전투자'})",
        details={
            "mock_mode": settings.kis_mock,
        },
    )


def _determine_overall_status(
    components: dict[str, ComponentHealth],
) -> OverallStatus:
    """컴포넌트 상태를 종합하여 전체 상태를 결정

    - 모든 컴포넌트가 UP/UNCONFIGURED → HEALTHY
    - 하나라도 DEGRADED → DEGRADED
    - 필수 컴포넌트(database)가 DOWN → UNHEALTHY
    """
    critical_components = {"database"}

    for name, health in components.items():
        if health.status == ComponentStatus.DOWN and name in critical_components:
            return OverallStatus.UNHEALTHY

    statuses = [h.status for h in components.values()]
    if ComponentStatus.DEGRADED in statuses or ComponentStatus.DOWN in statuses:
        return OverallStatus.DEGRADED

    return OverallStatus.HEALTHY


@router.get(
    "/health/detailed",
    response_model=DetailedHealthResponse,
    summary="상세 헬스체크",
    description=(
        "DB 연결, 한투 API 설정 등 의존 서비스 상태를 포함한 상세 헬스체크.\n\n"
        "`include_broker=true`로 한투 API 설정 상태도 확인할 수 있습니다."
    ),
)
async def detailed_health_check(
    include_broker: bool = Query(
        default=True,
        description="한투 API 설정 상태 포함 여부",
    ),
) -> DetailedHealthResponse:
    """상세 헬스체크"""

    components: dict[str, ComponentHealth] = {}

    # DB 상태 확인
    components["database"] = await _check_database()

    # 한투 API 상태 확인 (선택)
    if include_broker:
        components["broker"] = _check_broker()

    # 전체 상태 결정
    overall = _determine_overall_status(components)

    now = datetime.now(UTC)
    uptime = time.monotonic() - _app_start_time

    return DetailedHealthResponse(
        status=overall,
        version="0.3.0",
        env=settings.app_env,
        uptime_seconds=round(uptime, 2),
        started_at=_app_start_datetime.isoformat(),
        checked_at=now.isoformat(),
        components=components,
    )

"""
긴급 정지 API 엔드포인트
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from src.strategy.safety import DailyLossGuard, EmergencyStop, SafetyCheck

router = APIRouter(
    prefix="/api/v1/safety",
    tags=["Safety"],
)

# 모듈 수준 싱글턴
_emergency_stop = EmergencyStop()
_daily_loss_guard = DailyLossGuard(_emergency_stop)
_safety_check = SafetyCheck(_emergency_stop, _daily_loss_guard)


def get_emergency_stop() -> EmergencyStop:
    """EmergencyStop 싱글턴 반환 (다른 모듈에서 참조용)"""
    return _emergency_stop


def get_daily_loss_guard() -> DailyLossGuard:
    return _daily_loss_guard


def get_safety_check() -> SafetyCheck:
    return _safety_check


class EmergencyStopRequest(BaseModel):
    reason: str = "수동 긴급 정지"


class SafetyStatusResponse(BaseModel):
    emergency_stopped: bool
    stopped_at: str | None = None
    reason: str = ""
    daily_loss: dict[str, Any] = {}


@router.post(
    "/emergency-stop",
    response_model=SafetyStatusResponse,
    summary="긴급 정지",
)
def emergency_stop(req: EmergencyStopRequest | None = None) -> SafetyStatusResponse:
    reason = req.reason if req else "수동 긴급 정지"
    _emergency_stop.stop(reason)
    return SafetyStatusResponse(
        **_emergency_stop.status(),
        daily_loss=_daily_loss_guard.status(),
    )


@router.post(
    "/resume",
    response_model=SafetyStatusResponse,
    summary="재개",
)
def resume() -> SafetyStatusResponse:
    _emergency_stop.resume()
    return SafetyStatusResponse(
        **_emergency_stop.status(),
        daily_loss=_daily_loss_guard.status(),
    )


@router.get(
    "/status",
    response_model=SafetyStatusResponse,
    summary="안전장치 상태",
)
def safety_status() -> SafetyStatusResponse:
    return SafetyStatusResponse(
        **_emergency_stop.status(),
        daily_loss=_daily_loss_guard.status(),
    )

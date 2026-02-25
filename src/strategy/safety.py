"""
긴급 정지 + 안전장치 모듈

EmergencyStop: 모든 자동매매 즉시 중지/재개
DailyLossGuard: 일일 손실 한도 초과 시 자동 정지
SafetyCheck: 매 주문 전 안전 체크
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from src.utils.logger import get_logger

logger = get_logger(__name__)


class EmergencyStop:
    """긴급 정지 — 모든 자동매매 즉시 중지/재개"""

    def __init__(self) -> None:
        self._stopped = False
        self._lock = threading.Lock()
        self._stopped_at: str | None = None
        self._reason: str = ""

    def stop(self, reason: str = "수동 긴급 정지") -> None:
        """긴급 정지 발동"""
        with self._lock:
            self._stopped = True
            self._stopped_at = datetime.now(tz=timezone.utc).isoformat()
            self._reason = reason
        logger.warning("🚨 긴급 정지 발동: %s", reason)

    def resume(self) -> None:
        """재개"""
        with self._lock:
            self._stopped = False
            self._stopped_at = None
            self._reason = ""
        logger.info("✅ 자동매매 재개")

    def is_stopped(self) -> bool:
        """정지 상태 확인"""
        with self._lock:
            return self._stopped

    def status(self) -> dict[str, Any]:
        """상태 조회"""
        with self._lock:
            return {
                "emergency_stopped": self._stopped,
                "stopped_at": self._stopped_at,
                "reason": self._reason,
            }


class DailyLossGuard:
    """일일 손실 한도 감시 — 초과 시 EmergencyStop 트리거"""

    def __init__(
        self,
        emergency_stop: EmergencyStop,
        max_daily_loss_pct: float = 0.03,
    ) -> None:
        self._emergency_stop = emergency_stop
        self._max_daily_loss_pct = max_daily_loss_pct
        self._daily_pnl: float = 0.0
        self._initial_asset: float = 0.0
        self._current_date: date | None = None

    def reset_daily(self, initial_asset: float) -> None:
        """일일 초기화 (장 시작 시 호출)"""
        self._daily_pnl = 0.0
        self._initial_asset = initial_asset
        self._current_date = date.today()
        logger.info(
            "DailyLossGuard 초기화: 자산 %s원, 한도 %.1f%%",
            f"{initial_asset:,.0f}",
            self._max_daily_loss_pct * 100,
        )

    def record_pnl(self, pnl: float) -> bool:
        """손익 기록. 한도 초과 시 True 반환 + 긴급 정지"""
        # 날짜 변경 체크
        today = date.today()
        if self._current_date != today:
            self._daily_pnl = 0.0
            self._current_date = today

        self._daily_pnl += pnl

        if self._initial_asset > 0:
            loss_pct = abs(self._daily_pnl) / self._initial_asset
            if self._daily_pnl < 0 and loss_pct >= self._max_daily_loss_pct:
                reason = (
                    f"일일 손실 한도 초과: {self._daily_pnl:+,.0f}원 "
                    f"({loss_pct:.2%} >= {self._max_daily_loss_pct:.2%})"
                )
                self._emergency_stop.stop(reason)
                return True
        return False

    @property
    def daily_pnl(self) -> float:
        return self._daily_pnl

    def status(self) -> dict[str, Any]:
        """상태 조회"""
        loss_pct = (
            abs(self._daily_pnl) / self._initial_asset
            if self._initial_asset > 0 and self._daily_pnl < 0
            else 0.0
        )
        return {
            "daily_pnl": self._daily_pnl,
            "initial_asset": self._initial_asset,
            "loss_pct": loss_pct,
            "max_daily_loss_pct": self._max_daily_loss_pct,
            "limit_remaining": (
                self._initial_asset * self._max_daily_loss_pct + self._daily_pnl
                if self._initial_asset > 0
                else 0.0
            ),
        }


@dataclass
class SafetyCheckResult:
    """안전 체크 결과"""

    safe: bool
    reasons: list[str] = field(default_factory=list)


class SafetyCheck:
    """매 주문 전 안전 체크"""

    def __init__(
        self,
        emergency_stop: EmergencyStop,
        daily_loss_guard: DailyLossGuard,
    ) -> None:
        self._emergency_stop = emergency_stop
        self._daily_loss_guard = daily_loss_guard

    def check(self, order_amount: float = 0, available_cash: float = 0) -> SafetyCheckResult:
        """주문 전 안전 체크

        Returns:
            SafetyCheckResult(safe=True/False, reasons=[...])
        """
        reasons: list[str] = []

        # 1. 긴급 정지 상태
        if self._emergency_stop.is_stopped():
            reasons.append("긴급 정지 상태입니다")

        # 2. 일일 손실 한도 (이미 초과이면 emergency_stop 발동 상태)
        guard_status = self._daily_loss_guard.status()
        if guard_status["limit_remaining"] <= 0 and guard_status["initial_asset"] > 0:
            reasons.append("일일 손실 한도를 초과했습니다")

        # 3. 잔고 체크
        if order_amount > 0 and available_cash < order_amount:
            reasons.append(
                f"잔고 부족: 주문 {order_amount:,.0f}원 > 가용 {available_cash:,.0f}원"
            )

        return SafetyCheckResult(safe=len(reasons) == 0, reasons=reasons)

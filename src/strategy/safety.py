"""안전장치(SafetyCheck)

일일 손실 제한, 긴급 정지 등 기본적인 리스크 가드를 제공합니다.

현재 버전은 AutoTrader와 기존 테스트와의 하위호환을 위해 최소 구현만 포함합니다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class SafetyCheckResult:
    safe: bool
    reasons: list[str] = field(default_factory=list)


class SafetyCheck:
    """기본 안전장치

    - emergency_stop: True인 경우 모든 신규 주문 차단
    - 가용 현금보다 큰 주문 금액 차단
    """

    def __init__(self, emergency_stop: bool = False) -> None:
        self.emergency_stop = emergency_stop

    def check(self, *, order_amount: float, available_cash: float) -> SafetyCheckResult:
        reasons: list[str] = []

        if self.emergency_stop:
            reasons.append("emergency_stop 활성화")

        if order_amount > available_cash:
            reasons.append("가용 현금 부족")

        safe = not reasons
        if not safe:
            logger.warning(
                "SafetyCheck 차단: order_amount=%.0f, available_cash=%.0f, reasons=%s",
                order_amount,
                available_cash,
                ", ".join(reasons),
            )

        return SafetyCheckResult(safe=safe, reasons=reasons)

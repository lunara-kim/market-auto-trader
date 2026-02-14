"""
알림 매니저 모듈

알림 규칙 관리 및 조건 판정 로직을 제공합니다.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from src.utils.logger import get_logger

logger = get_logger(__name__)


class AlertCondition(str, Enum):
    """알림 조건 타입"""

    STOP_LOSS = "stop_loss"  # 손절가 도달
    TARGET_PRICE = "target_price"  # 목표가 도달
    PRICE_DROP_PCT = "price_drop_pct"  # 전일 대비 하락률 (%)
    PRICE_RISE_PCT = "price_rise_pct"  # 전일 대비 상승률 (%)
    VOLUME_SPIKE = "volume_spike"  # 거래량 급증 (평균 대비 배수)


class AlertRule(BaseModel):
    """알림 규칙 Pydantic 모델"""

    id: int | None = None
    stock_code: str = Field(..., min_length=1, max_length=20)
    stock_name: str | None = None
    condition: AlertCondition
    threshold: float = Field(..., gt=0)
    is_active: bool = True
    last_triggered_at: datetime | None = None
    cooldown_minutes: int = Field(default=60, ge=0)
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class AlertManager:
    """알림 매니저 — 알림 규칙 관리 및 조건 판정"""

    def __init__(self) -> None:
        self._rules: dict[int, AlertRule] = {}
        self._next_id: int = 1

    def add_rule(self, rule: AlertRule) -> AlertRule:
        """알림 규칙 추가"""
        if rule.id is None:
            rule.id = self._next_id
            self._next_id += 1

        if rule.created_at is None:
            rule.created_at = datetime.now(UTC)

        self._rules[rule.id] = rule
        logger.info(
            "알림 규칙 추가: ID=%s, 종목=%s, 조건=%s, 임계값=%s",
            rule.id,
            rule.stock_code,
            rule.condition.value,
            rule.threshold,
        )
        return rule

    def remove_rule(self, rule_id: int) -> bool:
        """알림 규칙 삭제"""
        if rule_id in self._rules:
            del self._rules[rule_id]
            logger.info("알림 규칙 삭제: ID=%s", rule_id)
            return True
        return False

    def get_rules(self) -> list[AlertRule]:
        """모든 알림 규칙 조회"""
        return list(self._rules.values())

    def get_active_rules(self, stock_code: str | None = None) -> list[AlertRule]:
        """활성화된 알림 규칙 조회"""
        rules = [r for r in self._rules.values() if r.is_active]
        if stock_code:
            rules = [r for r in rules if r.stock_code == stock_code]
        return rules

    def check_alerts(
        self,
        stock_code: str,
        current_price: float,
        *,
        volume: int | None = None,
        previous_close: float | None = None,
    ) -> list[AlertRule]:
        """
        특정 종목에 대해 알림 조건을 체크합니다.

        Args:
            stock_code: 종목 코드
            current_price: 현재가
            volume: 현재 거래량 (VOLUME_SPIKE 판정 시 사용)
            previous_close: 전일 종가 (등락률 계산 시 사용)

        Returns:
            트리거된 알림 규칙 리스트
        """
        triggered: list[AlertRule] = []
        active_rules = self.get_active_rules(stock_code)

        for rule in active_rules:
            # Cooldown 체크
            if not self._is_ready_to_trigger(rule):
                continue

            # 조건별 판정
            is_triggered = self._evaluate_condition(
                rule=rule,
                current_price=current_price,
                volume=volume,
                previous_close=previous_close,
            )

            if is_triggered:
                rule.last_triggered_at = datetime.now(UTC)
                triggered.append(rule)
                logger.info(
                    "알림 트리거: 종목=%s, 조건=%s, 현재가=%s, 임계값=%s",
                    stock_code,
                    rule.condition.value,
                    current_price,
                    rule.threshold,
                )

        return triggered

    def _is_ready_to_trigger(self, rule: AlertRule) -> bool:
        """Cooldown이 지났는지 확인"""
        if rule.last_triggered_at is None:
            return True

        elapsed = datetime.now(UTC) - rule.last_triggered_at
        cooldown = timedelta(minutes=rule.cooldown_minutes)
        return elapsed >= cooldown

    def _evaluate_condition(
        self,
        rule: AlertRule,
        current_price: float,
        volume: int | None,
        previous_close: float | None,
    ) -> bool:
        """알림 조건 판정"""
        condition = rule.condition
        threshold = rule.threshold

        if condition == AlertCondition.STOP_LOSS:
            # 현재가가 손절가(threshold) 이하로 떨어진 경우
            return current_price <= threshold

        elif condition == AlertCondition.TARGET_PRICE:
            # 현재가가 목표가(threshold) 이상으로 올라간 경우
            return current_price >= threshold

        elif condition == AlertCondition.PRICE_DROP_PCT:
            # 전일 대비 하락률이 threshold% 이상인 경우
            if previous_close is None or previous_close <= 0:
                return False
            drop_pct = ((previous_close - current_price) / previous_close) * 100
            return drop_pct >= threshold

        elif condition == AlertCondition.PRICE_RISE_PCT:
            # 전일 대비 상승률이 threshold% 이상인 경우
            if previous_close is None or previous_close <= 0:
                return False
            rise_pct = ((current_price - previous_close) / previous_close) * 100
            return rise_pct >= threshold

        elif condition == AlertCondition.VOLUME_SPIKE:
            # 거래량이 평균의 threshold배 이상인 경우
            # (실제로는 평균 거래량 필요, 여기서는 단순 비교)
            if volume is None:
                return False
            # 실제 구현에서는 평균 거래량 조회 필요
            # 여기서는 threshold를 절대값으로 사용
            return volume >= threshold

        return False

"""AlertManager 유닛 테스트"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.notification.alert_manager import AlertCondition, AlertManager, AlertRule


@pytest.fixture
def manager() -> AlertManager:
    """AlertManager 인스턴스 생성"""
    return AlertManager()


@pytest.fixture
def sample_rule() -> AlertRule:
    """샘플 알림 규칙"""
    return AlertRule(
        stock_code="005930",
        stock_name="삼성전자",
        condition=AlertCondition.STOP_LOSS,
        threshold=70000.0,
        cooldown_minutes=30,
    )


def test_add_rule(manager: AlertManager, sample_rule: AlertRule) -> None:
    """알림 규칙 추가 테스트"""
    added = manager.add_rule(sample_rule)

    assert added.id is not None
    assert added.stock_code == "005930"
    assert added.condition == AlertCondition.STOP_LOSS
    assert added.threshold == 70000.0
    assert added.created_at is not None


def test_remove_rule(manager: AlertManager, sample_rule: AlertRule) -> None:
    """알림 규칙 삭제 테스트"""
    added = manager.add_rule(sample_rule)
    assert added.id is not None

    result = manager.remove_rule(added.id)
    assert result is True

    # 다시 삭제하면 False
    result = manager.remove_rule(added.id)
    assert result is False


def test_get_rules(manager: AlertManager, sample_rule: AlertRule) -> None:
    """모든 알림 규칙 조회 테스트"""
    manager.add_rule(sample_rule)

    rule2 = AlertRule(
        stock_code="000660",
        stock_name="SK하이닉스",
        condition=AlertCondition.TARGET_PRICE,
        threshold=150000.0,
    )
    manager.add_rule(rule2)

    rules = manager.get_rules()
    assert len(rules) == 2
    assert rules[0].stock_code == "005930"
    assert rules[1].stock_code == "000660"


def test_get_active_rules(manager: AlertManager, sample_rule: AlertRule) -> None:
    """활성화된 알림 규칙 조회 테스트"""
    manager.add_rule(sample_rule)

    rule2 = AlertRule(
        stock_code="000660",
        condition=AlertCondition.TARGET_PRICE,
        threshold=150000.0,
        is_active=False,
    )
    manager.add_rule(rule2)

    active = manager.get_active_rules()
    assert len(active) == 1
    assert active[0].stock_code == "005930"

    # 종목 코드 필터링
    active_samsung = manager.get_active_rules(stock_code="005930")
    assert len(active_samsung) == 1


def test_check_alerts_stop_loss(manager: AlertManager) -> None:
    """손절가 알림 테스트"""
    rule = AlertRule(
        stock_code="005930",
        condition=AlertCondition.STOP_LOSS,
        threshold=70000.0,
    )
    manager.add_rule(rule)

    # 손절가 이하로 떨어진 경우
    triggered = manager.check_alerts(
        stock_code="005930",
        current_price=69000.0,
    )
    assert len(triggered) == 1
    assert triggered[0].condition == AlertCondition.STOP_LOSS

    # 손절가보다 높은 경우
    triggered = manager.check_alerts(
        stock_code="005930",
        current_price=71000.0,
    )
    assert len(triggered) == 0


def test_check_alerts_target_price(manager: AlertManager) -> None:
    """목표가 알림 테스트"""
    rule = AlertRule(
        stock_code="005930",
        condition=AlertCondition.TARGET_PRICE,
        threshold=80000.0,
    )
    manager.add_rule(rule)

    # 목표가 이상으로 올라간 경우
    triggered = manager.check_alerts(
        stock_code="005930",
        current_price=81000.0,
    )
    assert len(triggered) == 1

    # 목표가보다 낮은 경우
    triggered = manager.check_alerts(
        stock_code="005930",
        current_price=79000.0,
    )
    assert len(triggered) == 0


def test_check_alerts_price_drop_pct(manager: AlertManager) -> None:
    """하락률 알림 테스트"""
    rule = AlertRule(
        stock_code="005930",
        condition=AlertCondition.PRICE_DROP_PCT,
        threshold=5.0,  # 5% 하락
    )
    manager.add_rule(rule)

    # 전일 종가 대비 5% 이상 하락
    triggered = manager.check_alerts(
        stock_code="005930",
        current_price=66500.0,
        previous_close=70000.0,
    )
    assert len(triggered) == 1

    # 5% 미만 하락
    triggered = manager.check_alerts(
        stock_code="005930",
        current_price=67000.0,
        previous_close=70000.0,
    )
    assert len(triggered) == 0

    # previous_close가 없으면 트리거 안됨
    triggered = manager.check_alerts(
        stock_code="005930",
        current_price=66500.0,
    )
    assert len(triggered) == 0


def test_check_alerts_price_rise_pct(manager: AlertManager) -> None:
    """상승률 알림 테스트"""
    rule = AlertRule(
        stock_code="005930",
        condition=AlertCondition.PRICE_RISE_PCT,
        threshold=3.0,  # 3% 상승
    )
    manager.add_rule(rule)

    # 전일 종가 대비 3% 이상 상승
    triggered = manager.check_alerts(
        stock_code="005930",
        current_price=72100.0,
        previous_close=70000.0,
    )
    assert len(triggered) == 1

    # 3% 미만 상승
    triggered = manager.check_alerts(
        stock_code="005930",
        current_price=71500.0,
        previous_close=70000.0,
    )
    assert len(triggered) == 0


def test_check_alerts_volume_spike(manager: AlertManager) -> None:
    """거래량 급증 알림 테스트"""
    rule = AlertRule(
        stock_code="005930",
        condition=AlertCondition.VOLUME_SPIKE,
        threshold=1000000.0,  # 100만주 이상
    )
    manager.add_rule(rule)

    # 거래량이 임계값 이상
    triggered = manager.check_alerts(
        stock_code="005930",
        current_price=70000.0,
        volume=1500000,
    )
    assert len(triggered) == 1

    # 거래량이 임계값 미만
    triggered = manager.check_alerts(
        stock_code="005930",
        current_price=70000.0,
        volume=800000,
    )
    assert len(triggered) == 0

    # volume이 없으면 트리거 안됨
    triggered = manager.check_alerts(
        stock_code="005930",
        current_price=70000.0,
    )
    assert len(triggered) == 0


def test_cooldown_mechanism(manager: AlertManager) -> None:
    """Cooldown 메커니즘 테스트"""
    rule = AlertRule(
        stock_code="005930",
        condition=AlertCondition.STOP_LOSS,
        threshold=70000.0,
        cooldown_minutes=30,
    )
    added = manager.add_rule(rule)

    # 첫 번째 트리거
    triggered = manager.check_alerts(
        stock_code="005930",
        current_price=69000.0,
    )
    assert len(triggered) == 1
    assert triggered[0].last_triggered_at is not None

    # 즉시 다시 체크하면 cooldown으로 트리거 안됨
    triggered = manager.check_alerts(
        stock_code="005930",
        current_price=68000.0,
    )
    assert len(triggered) == 0

    # Cooldown 시간이 지나면 다시 트리거
    # last_triggered_at을 과거로 설정
    added.last_triggered_at = datetime.now(UTC) - timedelta(minutes=31)
    triggered = manager.check_alerts(
        stock_code="005930",
        current_price=68000.0,
    )
    assert len(triggered) == 1


def test_multiple_alerts_same_stock(manager: AlertManager) -> None:
    """같은 종목에 여러 알림 규칙이 있을 때"""
    rule1 = AlertRule(
        stock_code="005930",
        condition=AlertCondition.STOP_LOSS,
        threshold=70000.0,
    )
    rule2 = AlertRule(
        stock_code="005930",
        condition=AlertCondition.PRICE_DROP_PCT,
        threshold=5.0,
    )
    manager.add_rule(rule1)
    manager.add_rule(rule2)

    # 두 조건 모두 충족
    triggered = manager.check_alerts(
        stock_code="005930",
        current_price=66000.0,
        previous_close=70000.0,
    )
    assert len(triggered) == 2


def test_inactive_rule_not_triggered(manager: AlertManager) -> None:
    """비활성화된 규칙은 트리거되지 않음"""
    rule = AlertRule(
        stock_code="005930",
        condition=AlertCondition.STOP_LOSS,
        threshold=70000.0,
        is_active=False,
    )
    manager.add_rule(rule)

    triggered = manager.check_alerts(
        stock_code="005930",
        current_price=69000.0,
    )
    assert len(triggered) == 0


def test_different_stock_codes(manager: AlertManager) -> None:
    """다른 종목 코드는 트리거되지 않음"""
    rule = AlertRule(
        stock_code="005930",
        condition=AlertCondition.STOP_LOSS,
        threshold=70000.0,
    )
    manager.add_rule(rule)

    # 다른 종목 코드로 체크
    triggered = manager.check_alerts(
        stock_code="000660",
        current_price=69000.0,
    )
    assert len(triggered) == 0

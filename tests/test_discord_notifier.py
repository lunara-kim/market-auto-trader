"""DiscordNotifier 테스트"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.notification.alert_manager import AlertCondition, AlertRule
from src.notification.discord_notifier import DiscordNotifier


@pytest.fixture
def notifier() -> DiscordNotifier:
    """DiscordNotifier 인스턴스 생성"""
    return DiscordNotifier(webhook_url="https://discord.com/api/webhooks/test")


@pytest.fixture
def sample_alert_rule() -> AlertRule:
    """샘플 알림 규칙"""
    return AlertRule(
        id=1,
        stock_code="005930",
        stock_name="삼성전자",
        condition=AlertCondition.STOP_LOSS,
        threshold=70000.0,
        is_active=True,
        cooldown_minutes=60,
        created_at=datetime.now(UTC),
        last_triggered_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_send_alert_success(
    notifier: DiscordNotifier,
    sample_alert_rule: AlertRule,
) -> None:
    """알림 전송 성공 테스트"""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        mock_client_class.return_value = mock_client

        await notifier.send_alert(
            alert_rule=sample_alert_rule,
            current_price=69000.0,
            message="손절가 도달",
        )

        # post 호출 확인
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args

        # URL 확인
        assert call_args[0][0] == "https://discord.com/api/webhooks/test"

        # payload 확인
        payload = call_args.kwargs["json"]
        assert "embeds" in payload
        assert len(payload["embeds"]) == 1

        embed = payload["embeds"][0]
        assert "삼성전자" in embed["title"] or "005930" in embed["title"]
        assert embed["color"] == 0xFF0000  # 손절은 빨간색


@pytest.mark.asyncio
async def test_send_alert_target_price(notifier: DiscordNotifier) -> None:
    """목표가 알림 전송 테스트 (녹색)"""
    rule = AlertRule(
        id=2,
        stock_code="000660",
        stock_name="SK하이닉스",
        condition=AlertCondition.TARGET_PRICE,
        threshold=150000.0,
        is_active=True,
        cooldown_minutes=60,
        created_at=datetime.now(UTC),
        last_triggered_at=datetime.now(UTC),
    )

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        mock_client_class.return_value = mock_client

        await notifier.send_alert(
            alert_rule=rule,
            current_price=151000.0,
            message="목표가 도달",
        )

        payload = mock_client.post.call_args.kwargs["json"]
        embed = payload["embeds"][0]
        assert embed["color"] == 0x00FF00  # 목표가는 녹색


@pytest.mark.asyncio
async def test_send_alert_http_error(
    notifier: DiscordNotifier,
    sample_alert_rule: AlertRule,
) -> None:
    """HTTP 오류 발생 시 예외 처리 테스트"""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            side_effect=httpx.HTTPError("Network error")
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        mock_client_class.return_value = mock_client

        # 예외가 발생해도 에러 로그만 남기고 정상 종료
        await notifier.send_alert(
            alert_rule=sample_alert_rule,
            current_price=69000.0,
            message="손절가 도달",
        )


@pytest.mark.asyncio
async def test_send_alert_no_webhook_url() -> None:
    """Webhook URL이 없을 때 테스트"""
    notifier = DiscordNotifier(webhook_url="")

    rule = AlertRule(
        stock_code="005930",
        condition=AlertCondition.STOP_LOSS,
        threshold=70000.0,
    )

    # URL이 없으면 로그만 남기고 종료
    await notifier.send_alert(
        alert_rule=rule,
        current_price=69000.0,
        message="손절가 도달",
    )


@pytest.mark.asyncio
async def test_send_daily_summary(notifier: DiscordNotifier) -> None:
    """일일 요약 전송 테스트"""
    summary_data: dict[str, Any] = {
        "date": "2026-02-14",
        "total_alerts": 3,
        "triggered_rules": [
            {
                "stock_code": "005930",
                "stock_name": "삼성전자",
                "condition": "stop_loss",
                "threshold": 70000.0,
            },
            {
                "stock_code": "000660",
                "stock_name": "SK하이닉스",
                "condition": "target_price",
                "threshold": 150000.0,
            },
        ],
        "portfolio_summary": {
            "total_value": 10000000.0,
            "profit_loss_rate": 5.2,
        },
    }

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        mock_client_class.return_value = mock_client

        await notifier.send_daily_summary(summary_data)

        # post 호출 확인
        mock_client.post.assert_called_once()
        payload = mock_client.post.call_args.kwargs["json"]

        embed = payload["embeds"][0]
        assert "2026-02-14" in embed["title"]
        assert "3개의 알림" in embed["description"]
        assert embed["color"] == 0x3498DB


@pytest.mark.asyncio
async def test_build_alert_embed_fields(
    notifier: DiscordNotifier,
    sample_alert_rule: AlertRule,
) -> None:
    """Embed 필드 구조 테스트"""
    embed = notifier._build_alert_embed(
        alert_rule=sample_alert_rule,
        current_price=69000.0,
        message="테스트 메시지",
    )

    assert "title" in embed
    assert "description" in embed
    assert "fields" in embed
    assert "color" in embed

    fields = embed["fields"]
    field_names = [f["name"] for f in fields]

    assert "종목 코드" in field_names
    assert "현재가" in field_names
    assert "조건" in field_names
    assert "메시지" in field_names


@pytest.mark.asyncio
async def test_format_condition_stop_loss(notifier: DiscordNotifier) -> None:
    """손절가 조건 포맷팅 테스트"""
    rule = AlertRule(
        stock_code="005930",
        condition=AlertCondition.STOP_LOSS,
        threshold=70000.0,
    )

    formatted = notifier._format_condition(rule)
    assert "손절가" in formatted
    assert "70,000원" in formatted or "70000" in formatted


@pytest.mark.asyncio
async def test_format_condition_target_price(notifier: DiscordNotifier) -> None:
    """목표가 조건 포맷팅 테스트"""
    rule = AlertRule(
        stock_code="005930",
        condition=AlertCondition.TARGET_PRICE,
        threshold=80000.0,
    )

    formatted = notifier._format_condition(rule)
    assert "목표가" in formatted


@pytest.mark.asyncio
async def test_format_condition_price_drop_pct(notifier: DiscordNotifier) -> None:
    """하락률 조건 포맷팅 테스트"""
    rule = AlertRule(
        stock_code="005930",
        condition=AlertCondition.PRICE_DROP_PCT,
        threshold=5.0,
    )

    formatted = notifier._format_condition(rule)
    assert "하락률" in formatted
    assert "5" in formatted


@pytest.mark.asyncio
async def test_format_condition_price_rise_pct(notifier: DiscordNotifier) -> None:
    """상승률 조건 포맷팅 테스트"""
    rule = AlertRule(
        stock_code="005930",
        condition=AlertCondition.PRICE_RISE_PCT,
        threshold=3.0,
    )

    formatted = notifier._format_condition(rule)
    assert "상승률" in formatted


@pytest.mark.asyncio
async def test_format_condition_volume_spike(notifier: DiscordNotifier) -> None:
    """거래량 조건 포맷팅 테스트"""
    rule = AlertRule(
        stock_code="005930",
        condition=AlertCondition.VOLUME_SPIKE,
        threshold=1000000.0,
    )

    formatted = notifier._format_condition(rule)
    assert "거래량" in formatted


@pytest.mark.asyncio
async def test_build_summary_embed_structure(notifier: DiscordNotifier) -> None:
    """일일 요약 Embed 구조 테스트"""
    summary_data: dict[str, Any] = {
        "date": "2026-02-14",
        "total_alerts": 5,
        "triggered_rules": [],
        "portfolio_summary": {},
    }

    embed = notifier._build_summary_embed(summary_data)

    assert "title" in embed
    assert "description" in embed
    assert "fields" in embed
    assert "2026-02-14" in embed["title"]
    assert "5개의 알림" in embed["description"]


@pytest.mark.asyncio
async def test_build_summary_embed_with_rules(notifier: DiscordNotifier) -> None:
    """트리거된 규칙이 포함된 요약 Embed 테스트"""
    summary_data: dict[str, Any] = {
        "date": "2026-02-14",
        "total_alerts": 2,
        "triggered_rules": [
            {
                "stock_code": "005930",
                "stock_name": "삼성전자",
                "condition": "stop_loss",
                "threshold": 70000.0,
            },
        ],
    }

    embed = notifier._build_summary_embed(summary_data)
    assert len(embed["fields"]) >= 1


@pytest.mark.asyncio
async def test_condition_emoji_mapping() -> None:
    """조건별 이모지 매핑 테스트"""
    notifier = DiscordNotifier(webhook_url="https://test.com")

    rule_stop_loss = AlertRule(
        stock_code="005930",
        condition=AlertCondition.STOP_LOSS,
        threshold=70000.0,
        last_triggered_at=datetime.now(UTC),
    )

    embed = notifier._build_alert_embed(rule_stop_loss, 69000.0, "")
    assert "🔴" in embed["title"]

    rule_target_price = AlertRule(
        stock_code="005930",
        condition=AlertCondition.TARGET_PRICE,
        threshold=80000.0,
        last_triggered_at=datetime.now(UTC),
    )

    embed = notifier._build_alert_embed(rule_target_price, 81000.0, "")
    assert "🟢" in embed["title"]

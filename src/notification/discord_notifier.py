"""
Discord 알림 모듈

Discord Webhook을 통해 알림 메시지를 전송합니다.
"""

from __future__ import annotations

from typing import Any

import httpx

from config.settings import settings
from src.notification.alert_manager import AlertRule
from src.utils.logger import get_logger

logger = get_logger(__name__)


class DiscordNotifier:
    """Discord Webhook 알림기"""

    def __init__(self, webhook_url: str | None = None) -> None:
        """
        Args:
            webhook_url: Discord Webhook URL (None이면 settings에서 가져옴)
        """
        self.webhook_url = webhook_url or settings.discord_webhook_url

    async def send_alert(
        self,
        alert_rule: AlertRule,
        current_price: float,
        message: str,
    ) -> None:
        """
        알림 메시지를 Discord로 전송합니다.

        Args:
            alert_rule: 트리거된 알림 규칙
            current_price: 현재가
            message: 추가 메시지
        """
        if not self.webhook_url:
            logger.warning("Discord Webhook URL이 설정되지 않았습니다.")
            return

        embed = self._build_alert_embed(alert_rule, current_price, message)
        payload = {"embeds": [embed]}

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.webhook_url,
                    json=payload,
                    timeout=10.0,
                )
                response.raise_for_status()
                logger.info(
                    "Discord 알림 전송 완료: 종목=%s, 조건=%s",
                    alert_rule.stock_code,
                    alert_rule.condition.value,
                )
        except httpx.HTTPError as e:
            logger.error("Discord 알림 전송 실패: %s", e)

    async def send_daily_summary(self, summary_data: dict[str, Any]) -> None:
        """
        일일 요약 보고서를 Discord로 전송합니다.

        Args:
            summary_data: 요약 데이터
                - date: 날짜
                - total_alerts: 총 알림 수
                - triggered_rules: 트리거된 규칙 리스트
                - portfolio_summary: 포트폴리오 요약
        """
        if not self.webhook_url:
            logger.warning("Discord Webhook URL이 설정되지 않았습니다.")
            return

        embed = self._build_summary_embed(summary_data)
        payload = {"embeds": [embed]}

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.webhook_url,
                    json=payload,
                    timeout=10.0,
                )
                response.raise_for_status()
                logger.info("Discord 일일 요약 전송 완료")
        except httpx.HTTPError as e:
            logger.error("Discord 일일 요약 전송 실패: %s", e)

    def _build_alert_embed(
        self,
        alert_rule: AlertRule,
        current_price: float,
        message: str,
    ) -> dict[str, Any]:
        """알림 Embed 생성"""
        condition_emoji = {
            "stop_loss": "🔴",
            "target_price": "🟢",
            "price_drop_pct": "📉",
            "price_rise_pct": "📈",
            "volume_spike": "📊",
        }

        emoji = condition_emoji.get(alert_rule.condition.value, "⚠️")
        title = f"{emoji} {alert_rule.stock_name or alert_rule.stock_code} 알림"

        fields = [
            {
                "name": "종목 코드",
                "value": alert_rule.stock_code,
                "inline": True,
            },
            {
                "name": "현재가",
                "value": f"{current_price:,.0f}원",
                "inline": True,
            },
            {
                "name": "조건",
                "value": self._format_condition(alert_rule),
                "inline": False,
            },
        ]

        if message:
            fields.append({
                "name": "메시지",
                "value": message,
                "inline": False,
            })

        color = 0xFF0000 if "loss" in alert_rule.condition.value else 0x00FF00

        return {
            "title": title,
            "description": "알림 조건이 충족되었습니다.",
            "color": color,
            "fields": fields,
            "timestamp": alert_rule.last_triggered_at.isoformat()
            if alert_rule.last_triggered_at
            else None,
        }

    def _build_summary_embed(self, summary_data: dict[str, Any]) -> dict[str, Any]:
        """일일 요약 Embed 생성"""
        date = summary_data.get("date", "")
        total_alerts = summary_data.get("total_alerts", 0)
        triggered_rules = summary_data.get("triggered_rules", [])

        description = f"총 {total_alerts}개의 알림이 발생했습니다."

        fields = []
        if triggered_rules:
            for idx, rule in enumerate(triggered_rules[:10], 1):  # 최대 10개만 표시
                fields.append({
                    "name": f"{idx}. {rule.get('stock_name', rule.get('stock_code'))}",
                    "value": f"조건: {rule.get('condition')} / 임계값: {rule.get('threshold')}",
                    "inline": False,
                })

        portfolio_summary = summary_data.get("portfolio_summary", {})
        if portfolio_summary:
            fields.append({
                "name": "포트폴리오",
                "value": (
                    f"총 평가액: {portfolio_summary.get('total_value', 0):,.0f}원\n"
                    f"수익률: {portfolio_summary.get('profit_loss_rate', 0):.2f}%"
                ),
                "inline": False,
            })

        return {
            "title": f"📋 {date} 일일 요약",
            "description": description,
            "color": 0x3498DB,
            "fields": fields,
        }

    def _format_condition(self, alert_rule: AlertRule) -> str:
        """조건 포맷팅"""
        condition = alert_rule.condition.value
        threshold = alert_rule.threshold

        if condition == "stop_loss":
            return f"손절가: {threshold:,.0f}원 이하"
        elif condition == "target_price":
            return f"목표가: {threshold:,.0f}원 이상"
        elif condition == "price_drop_pct":
            return f"하락률: {threshold:.1f}% 이상"
        elif condition == "price_rise_pct":
            return f"상승률: {threshold:.1f}% 이상"
        elif condition == "volume_spike":
            return f"거래량: {threshold:,.0f} 이상"
        return f"{condition}: {threshold}"

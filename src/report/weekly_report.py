"""
주간 투자 성과 리포트 생성기

거래 기록을 분석하여 주간 성과 마크다운 리포트를 생성합니다.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from src.report.trade_logger import TradeLog, TradeLogger
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class WeeklyStats:
    """주간 통계"""

    week_start: date
    week_end: date
    total_trades: int = 0
    buy_count: int = 0
    sell_count: int = 0
    total_buy_amount: int = 0
    total_sell_amount: int = 0
    realized_pnl: int = 0
    weekly_return_pct: float = 0.0
    win_count: int = 0
    loss_count: int = 0
    win_rate: float = 0.0
    best_trade: dict[str, Any] = field(default_factory=dict)
    worst_trade: dict[str, Any] = field(default_factory=dict)
    by_stock: dict[str, dict[str, Any]] = field(default_factory=dict)
    signal_count: int = 0
    buy_signal_count: int = 0
    signal_accuracy: float = 0.0
    suggestions: list[str] = field(default_factory=list)


class WeeklyReportGenerator:
    """주간 투자 성과 리포트 생성기"""

    def __init__(self, trade_logger: TradeLogger) -> None:
        self._logger = trade_logger

    def get_week_range(self, weeks_ago: int = 0) -> tuple[date, date]:
        """N주 전의 월~일 범위 반환"""
        today = date.today()
        # 이번 주 월요일
        monday = today - timedelta(days=today.weekday())
        # N주 전
        target_monday = monday - timedelta(weeks=weeks_ago)
        target_sunday = target_monday + timedelta(days=6)
        return target_monday, target_sunday

    def generate_stats(self, weeks_ago: int = 0) -> WeeklyStats:
        """주간 통계 계산"""
        week_start, week_end = self.get_week_range(weeks_ago)
        log = self._logger.get_date_range(week_start, week_end)
        return self._compute_stats(log, week_start, week_end)

    def generate_cumulative_stats(self, weeks: int = 4) -> list[WeeklyStats]:
        """최근 N주간 누적 통계"""
        return [self.generate_stats(weeks_ago=i) for i in range(weeks)]

    def _compute_stats(self, log: TradeLog, week_start: date, week_end: date) -> WeeklyStats:
        """TradeLog에서 통계 계산"""
        stats = WeeklyStats(week_start=week_start, week_end=week_end)
        trades = log.trades
        signals = log.signals

        stats.total_trades = len(trades)
        stats.signal_count = len(signals)

        # 매수/매도 분류
        buys = [t for t in trades if t.get("action") == "buy"]
        sells = [t for t in trades if t.get("action") == "sell"]
        stats.buy_count = len(buys)
        stats.sell_count = len(sells)
        stats.total_buy_amount = sum(t.get("notional", 0) for t in buys)
        stats.total_sell_amount = sum(t.get("notional", 0) for t in sells)
        stats.realized_pnl = stats.total_sell_amount - stats.total_buy_amount

        # 종목별 손익
        by_stock: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"buy_amount": 0, "sell_amount": 0, "pnl": 0, "stock_name": ""}
        )
        for t in trades:
            code = t.get("stock_code", "")
            name = t.get("stock_name", code)
            notional = t.get("notional", 0)
            by_stock[code]["stock_name"] = name
            if t.get("action") == "buy":
                by_stock[code]["buy_amount"] += notional
            else:
                by_stock[code]["sell_amount"] += notional

        for code, data in by_stock.items():
            data["pnl"] = data["sell_amount"] - data["buy_amount"]
            if data["pnl"] > 0:
                stats.win_count += 1
            elif data["pnl"] < 0:
                stats.loss_count += 1

        stats.by_stock = dict(by_stock)
        total_decided = stats.win_count + stats.loss_count
        stats.win_rate = (stats.win_count / total_decided * 100) if total_decided > 0 else 0.0

        # 수익률 (매수 총액 대비)
        if stats.total_buy_amount > 0:
            stats.weekly_return_pct = stats.realized_pnl / stats.total_buy_amount * 100

        # 최고/최악 거래
        if sells:
            # 매도 기준 가장 큰 금액/작은 금액
            best = max(sells, key=lambda t: t.get("notional", 0))
            worst = min(sells, key=lambda t: t.get("notional", 0))
            stats.best_trade = best
            stats.worst_trade = worst

        # 시그널 정확도 (매수 시그널 중 실제 거래로 이어진 비율)
        buy_signals = [s for s in signals if s.get("signal_type") in ("buy", "strong_buy")]
        stats.buy_signal_count = len(buy_signals)
        if buy_signals:
            traded_codes = {t.get("stock_code") for t in buys}
            accurate = sum(1 for s in buy_signals if s.get("stock_code") in traded_codes)
            stats.signal_accuracy = accurate / len(buy_signals) * 100

        # 개선 제안 생성
        stats.suggestions = self._generate_suggestions(stats)

        return stats

    def _generate_suggestions(self, stats: WeeklyStats) -> list[str]:
        """통계 기반 개선 제안"""
        suggestions: list[str] = []

        if stats.win_rate < 40 and (stats.win_count + stats.loss_count) > 0:
            suggestions.append("⚠️ 승률이 낮습니다. 매수 시그널 최소 점수 상향을 검토하세요.")

        if stats.weekly_return_pct < -3:
            suggestions.append("🔴 주간 손실이 큽니다. 손절 기준 강화 또는 포지션 축소를 고려하세요.")

        if stats.signal_accuracy < 30 and stats.buy_signal_count > 3:
            suggestions.append("📉 시그널 정확도가 낮습니다. 시그널 필터 조건을 재검토하세요.")

        if stats.total_trades == 0:
            suggestions.append("📊 이번 주 거래가 없습니다. 시그널 기준이 너무 엄격할 수 있습니다.")

        if stats.buy_count > 0 and stats.sell_count == 0:
            suggestions.append("💡 매수만 있고 매도가 없습니다. 익절/손절 기준을 확인하세요.")

        return suggestions

    def format_markdown(self, stats: WeeklyStats) -> str:
        """마크다운 포맷 리포트 생성 (Discord 전송용)"""
        lines: list[str] = []
        lines.append("# 📊 주간 투자 리포트")
        lines.append(f"**{stats.week_start} ~ {stats.week_end}**")
        lines.append("")

        # 요약
        lines.append("## 📈 성과 요약")
        lines.append(f"- 주간 수익률: **{stats.weekly_return_pct:+.2f}%**")
        lines.append(f"- 실현 손익: **{stats.realized_pnl:+,}원**")
        lines.append(f"- 총 거래: {stats.total_trades}건 (매수 {stats.buy_count} / 매도 {stats.sell_count})")
        lines.append(f"- 승률: {stats.win_rate:.1f}% ({stats.win_count}승 {stats.loss_count}패)")
        lines.append("")

        # 시그널
        lines.append("## 🎯 시그널 분석")
        lines.append(f"- 총 시그널: {stats.signal_count}건")
        lines.append(f"- 매수 시그널: {stats.buy_signal_count}건")
        lines.append(f"- 시그널 정확도: {stats.signal_accuracy:.1f}%")
        lines.append("")

        # 종목별
        if stats.by_stock:
            lines.append("## 📋 종목별 현황")
            for code, data in stats.by_stock.items():
                name = data.get("stock_name", code)
                pnl = data.get("pnl", 0)
                emoji = "🟢" if pnl >= 0 else "🔴"
                lines.append(f"- {emoji} {name}({code}): {pnl:+,}원")
            lines.append("")

        # 최고/최악
        if stats.best_trade:
            lines.append("## 🏆 주요 거래")
            best_name = stats.best_trade.get("stock_name", "")
            best_amt = stats.best_trade.get("notional", 0)
            lines.append(f"- 최대 매도: {best_name} {best_amt:,}원")
            if stats.worst_trade:
                worst_name = stats.worst_trade.get("stock_name", "")
                worst_amt = stats.worst_trade.get("notional", 0)
                lines.append(f"- 최소 매도: {worst_name} {worst_amt:,}원")
            lines.append("")

        # 제안
        if stats.suggestions:
            lines.append("## 💡 개선 제안")
            for s in stats.suggestions:
                lines.append(f"- {s}")
            lines.append("")

        return "\n".join(lines)

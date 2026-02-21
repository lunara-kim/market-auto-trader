"""백테스트 결과 리포트 유틸리티."""

from __future__ import annotations

from typing import Any

from src.backtest.engine import BacktestConfig, BacktestResult


def format_backtest_report(result: BacktestResult, config: BacktestConfig | None = None) -> str:
    """간단한 텍스트 리포트 생성."""

    lines: list[str] = []
    lines.append("=== Backtest Summary ===")

    # 센티멘트/PER 반영 여부 표시
    if config is not None:
        sentiment_label = "ON (Historical F&G)" if config.use_sentiment else "OFF"
        per_label = "ON (Historical PER)" if config.use_per else "OFF"
        lines.append(f"Sentiment    : {sentiment_label}")
        lines.append(f"PER Quality  : {per_label}")
    lines.append(f"Total Return : {result.total_return:.2f}%")
    lines.append(f"Win Rate     : {result.win_rate:.2f}%")
    lines.append(f"Avg Return   : {result.avg_return:.2f}%")
    lines.append(f"Max Drawdown : {result.max_drawdown:.2f}%")
    lines.append(f"Sharpe Ratio : {result.sharpe_ratio:.2f}")
    lines.append("")

    # 종목별 브레이크다운
    if result.per_symbol:
        lines.append("=== Per Symbol Breakdown ===")
        for symbol, summary in result.per_symbol.items():
            lines.append(_format_symbol_summary(symbol, summary))
        lines.append("")

    # 월별 브레이크다운은 현재 단순 구현 (날짜 문자열의 YYYY-MM을 기준으로 집계)
    monthly: dict[str, list[float]] = {}
    for trade in result.trades:
        month = trade.date[:7]
        if trade.pnl_pct is None:
            continue
        monthly.setdefault(month, []).append(trade.pnl_pct)

    if monthly:
        lines.append("=== Monthly PnL Breakdown ===")
        for month, pnls in sorted(monthly.items()):
            avg = sum(pnls) / len(pnls)
            lines.append(f"{month}: {avg:+.2f}% ({len(pnls)} trades)")

    return "\n".join(lines)


def _format_symbol_summary(symbol: str, summary: dict[str, Any]) -> str:
    ret = summary.get("total_return", 0.0)
    trades = summary.get("trades", 0)
    return f"{symbol}: {ret:+.2f}% ({trades} trades)"

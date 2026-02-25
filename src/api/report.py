"""
주간 리포트 API 엔드포인트
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel

from src.report.trade_logger import TradeLogger
from src.report.weekly_report import WeeklyReportGenerator

router = APIRouter(
    prefix="/api/v1/report",
    tags=["Report"],
)

_trade_logger = TradeLogger()
_report_generator = WeeklyReportGenerator(_trade_logger)


class WeeklyReportResponse(BaseModel):
    week_start: str
    week_end: str
    markdown: str
    stats: dict[str, Any]


class CumulativeReportResponse(BaseModel):
    weeks: list[dict[str, Any]]
    total_pnl: int
    total_trades: int
    overall_win_rate: float


@router.get(
    "/weekly",
    response_model=WeeklyReportResponse,
    summary="주간 리포트",
)
def weekly_report(
    weeks_ago: int = Query(default=0, ge=0, le=52),
) -> WeeklyReportResponse:
    stats = _report_generator.generate_stats(weeks_ago=weeks_ago)
    markdown = _report_generator.format_markdown(stats)
    return WeeklyReportResponse(
        week_start=stats.week_start.isoformat(),
        week_end=stats.week_end.isoformat(),
        markdown=markdown,
        stats={
            "total_trades": stats.total_trades,
            "buy_count": stats.buy_count,
            "sell_count": stats.sell_count,
            "realized_pnl": stats.realized_pnl,
            "weekly_return_pct": stats.weekly_return_pct,
            "win_rate": stats.win_rate,
            "signal_accuracy": stats.signal_accuracy,
            "suggestions": stats.suggestions,
        },
    )


@router.get(
    "/cumulative",
    response_model=CumulativeReportResponse,
    summary="누적 성과",
)
def cumulative_report(
    weeks: int = Query(default=4, ge=1, le=52),
) -> CumulativeReportResponse:
    all_stats = _report_generator.generate_cumulative_stats(weeks=weeks)
    total_pnl = sum(s.realized_pnl for s in all_stats)
    total_trades = sum(s.total_trades for s in all_stats)
    total_wins = sum(s.win_count for s in all_stats)
    total_losses = sum(s.loss_count for s in all_stats)
    decided = total_wins + total_losses
    overall_win_rate = (total_wins / decided * 100) if decided > 0 else 0.0

    return CumulativeReportResponse(
        weeks=[
            {
                "week_start": s.week_start.isoformat(),
                "week_end": s.week_end.isoformat(),
                "realized_pnl": s.realized_pnl,
                "weekly_return_pct": s.weekly_return_pct,
                "win_rate": s.win_rate,
                "total_trades": s.total_trades,
            }
            for s in all_stats
        ],
        total_pnl=total_pnl,
        total_trades=total_trades,
        overall_win_rate=overall_win_rate,
    )

"""파라미터 최적화 — Grid Search 기반 백테스트 파라미터 튜닝.

AutoTrader의 핵심 파라미터를 그리드 서치로 탐색하여
샤프비율 기준 최적 조합을 찾습니다.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from src.backtest.engine import BacktestConfig, BacktestEngine
from src.backtest.historical_per import HistoricalPERCalculator
from src.backtest.historical_sentiment import HistoricalFearGreedLoader
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class ParamGrid:
    """탐색할 파라미터 범위."""

    buy_threshold: list[float] = field(default_factory=lambda: [5, 10, 15, 20])
    sell_threshold: list[float] = field(default_factory=lambda: [-15, -20, -25, -30])
    stop_loss: list[float] = field(default_factory=lambda: [-0.05, -0.07, -0.10, -0.12])
    take_profit: list[float] = field(default_factory=lambda: [0.08, 0.10, 0.15, 0.20])
    min_trade_interval_days: list[int] = field(default_factory=lambda: [3, 5, 7, 10])
    trailing_stop_pct: list[float] = field(default_factory=lambda: [-0.03, -0.05, -0.07, -0.10])
    max_position_pct: list[float] = field(default_factory=lambda: [0.5, 0.8, 1.0])

    def total_combinations(self) -> int:
        return (
            len(self.buy_threshold)
            * len(self.sell_threshold)
            * len(self.stop_loss)
            * len(self.take_profit)
            * len(self.min_trade_interval_days)
            * len(self.trailing_stop_pct)
            * len(self.max_position_pct)
        )


@dataclass(slots=True)
class OptimizationResult:
    """단일 파라미터 조합의 결과."""

    params: dict[str, Any]
    total_return: float
    win_rate: float
    max_drawdown: float
    sharpe_ratio: float
    avg_return: float
    num_trades: int


class ParameterOptimizer:
    """Grid search 기반 파라미터 최적화."""

    def __init__(
        self,
        symbol_data: dict[str, pd.DataFrame],
        base_config: BacktestConfig | None = None,
        sentiment_loader: HistoricalFearGreedLoader | None = None,
        per_calculator: HistoricalPERCalculator | None = None,
    ) -> None:
        self._symbol_data = symbol_data
        self._base_config = base_config or BacktestConfig()
        self._sentiment_loader = sentiment_loader
        self._per_calculator = per_calculator

    def optimize(
        self,
        grid: ParamGrid | None = None,
        metric: str = "sharpe_ratio",
    ) -> list[OptimizationResult]:
        """그리드 서치 실행.

        Args:
            grid: 파라미터 그리드. None이면 기본 그리드 사용.
            metric: 정렬 기준 메트릭 (sharpe_ratio, total_return, return_mdd_ratio).

        Returns:
            메트릭 내림차순 정렬된 결과 리스트.
        """
        if grid is None:
            grid = ParamGrid()

        total = grid.total_combinations()
        logger.info("파라미터 최적화 시작: %d개 조합", total)

        results: list[OptimizationResult] = []
        count = 0

        for buy_th, sell_th, sl, tp, interval, ts_pct, mp in itertools.product(
            grid.buy_threshold,
            grid.sell_threshold,
            grid.stop_loss,
            grid.take_profit,
            grid.min_trade_interval_days,
            grid.trailing_stop_pct,
            grid.max_position_pct,
        ):
            count += 1
            if count % 500 == 0:
                logger.info("진행: %d / %d", count, total)

            config = BacktestConfig(
                initial_capital=self._base_config.initial_capital,
                take_profit=tp,
                stop_loss=sl,
                max_position_pct=mp,
                sentiment_bias=self._base_config.sentiment_bias,
                use_sentiment=self._base_config.use_sentiment,
                use_per=self._base_config.use_per,
                min_trade_interval_days=interval,
                buy_threshold=buy_th,
                sell_threshold=sell_th,
                use_trend_filter=self._base_config.use_trend_filter,
                use_trailing_stop=True,
                trailing_stop_pct=ts_pct,
            )

            engine = BacktestEngine(
                config=config,
                sentiment_loader=self._sentiment_loader,
                per_calculator=self._per_calculator,
            )
            bt_result = engine.run(self._symbol_data)

            num_trades = len([t for t in bt_result.trades if t.pnl_pct is not None])

            results.append(
                OptimizationResult(
                    params={
                        "buy_threshold": buy_th,
                        "sell_threshold": sell_th,
                        "stop_loss": sl,
                        "take_profit": tp,
                        "min_trade_interval_days": interval,
                        "trailing_stop_pct": ts_pct,
                        "max_position_pct": mp,
                    },
                    total_return=bt_result.total_return,
                    win_rate=bt_result.win_rate,
                    max_drawdown=bt_result.max_drawdown,
                    sharpe_ratio=bt_result.sharpe_ratio,
                    avg_return=bt_result.avg_return,
                    num_trades=num_trades,
                )
            )

        # 정렬
        if metric == "return_mdd_ratio":
            results.sort(
                key=lambda r: (r.total_return / r.max_drawdown) if r.max_drawdown > 0 else r.total_return,
                reverse=True,
            )
        else:
            results.sort(key=lambda r: getattr(r, metric, 0.0), reverse=True)

        logger.info("최적화 완료: 최적 %s = %.4f", metric, getattr(results[0], metric, 0.0) if results else 0.0)
        return results


def format_optimization_report(results: list[OptimizationResult], top_n: int = 10) -> str:
    """최적화 결과를 보기 좋은 텍스트 테이블로 포맷."""
    lines = [
        f"{'Rank':>4} | {'Buy':>4} | {'Sell':>5} | {'SL%':>6} | {'TP%':>5} | {'Intv':>4} | "
        f"{'TS%':>5} | {'Pos%':>4} | "
        f"{'Return%':>8} | {'WinR%':>6} | {'MDD%':>6} | {'Sharpe':>7} | {'Trades':>6}",
        "-" * 110,
    ]
    for i, r in enumerate(results[:top_n], 1):
        p = r.params
        ts_pct = p.get("trailing_stop_pct", 0)
        mp = p.get("max_position_pct", 0.2)
        lines.append(
            f"{i:>4} | {p['buy_threshold']:>4.0f} | {p['sell_threshold']:>5.0f} | "
            f"{p['stop_loss']*100:>5.1f}% | {p['take_profit']*100:>4.0f}% | "
            f"{p['min_trade_interval_days']:>4} | "
            f"{ts_pct*100:>4.0f}% | {mp*100:>3.0f}% | "
            f"{r.total_return:>+7.2f}% | {r.win_rate:>5.1f}% | {r.max_drawdown:>5.2f}% | "
            f"{r.sharpe_ratio:>7.4f} | {r.num_trades:>6}"
        )
    return "\n".join(lines)

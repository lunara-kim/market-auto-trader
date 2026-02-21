"""백테스트 엔진.

AutoTrader의 시그널 스코어링(센티멘트 + PER + RSI + 볼린저밴드)을
과거 시세 데이터에 적용해 성과를 검증합니다.

설계 원칙
---------
* yfinance 호출은 :mod:`src.backtest.data_loader` 에서만 수행합니다.
* 이 모듈은 **순수 파이썬 로직**만 포함하여 테스트에서 쉽게 Mocking 할 수 있도록 합니다.
* 포트폴리오 단위가 아닌, **종목별 독립 시뮬레이션**을 수행하고 결과를 합산합니다.
  - 각 종목은 ``initial_capital / n_symbols`` 를 초기 자본으로 사용합니다.
  - ``max_position_pct`` 은 종목별 자본에 대한 비중으로 적용합니다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

import pandas as pd

from src.analysis.screener import StockScreener
from src.backtest.historical_per import HistoricalPERCalculator
from src.backtest.historical_sentiment import HistoricalFearGreedLoader
from src.broker.kis_client import KISClient
from src.strategy.auto_trader import SignalType as AutoSignalType
from src.strategy.auto_trader import AutoTrader
from src.strategy.rsi import calculate_rsi
from src.strategy.bollinger_bands import calculate_bollinger_bands
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class BacktestTrade:
    """개별 체결 내역."""

    symbol: str
    date: str
    side: str  # "buy" | "sell"
    quantity: int
    price: float
    pnl_pct: float | None = None


@dataclass(slots=True)
class BacktestConfig:
    """백테스트 설정."""

    initial_capital: float = 10_000_000.0
    take_profit: float = 0.15  # +15%
    stop_loss: float = -0.07  # -7%
    max_position_pct: float = 0.2  # 20%
    sentiment_bias: float = 0.0  # 백테스트용 고정 센티멘트 점수 (기본 중립)
    use_sentiment: bool = False  # 히스토리컬 Fear & Greed 사용 여부
    use_per: bool = False  # 히스토리컬 PER quality 사용 여부


@dataclass(slots=True)
class BacktestResult:
    """백테스트 결과 요약."""

    total_return: float
    win_rate: float
    avg_return: float
    max_drawdown: float
    sharpe_ratio: float
    trades: List[BacktestTrade] = field(default_factory=list)
    equity_curve: List[dict[str, float]] = field(default_factory=list)
    per_symbol: Dict[str, dict[str, Any]] = field(default_factory=dict)


class BacktestEngine:
    """RSI + 볼린저밴드 + PER 품질을 이용한 간단 백테스트 엔진."""

    def __init__(
        self,
        kis_client: KISClient | None = None,
        config: BacktestConfig | None = None,
        sentiment_loader: HistoricalFearGreedLoader | None = None,
        per_calculator: HistoricalPERCalculator | None = None,
    ) -> None:
        # KISClient는 PER 스크리닝에만 사용되며, 백테스트 자체는 가격 데이터만으로 수행된다.
        # 백테스트는 PER 없이도 동작할 수 있어야 하므로, kis_client가 없으면
        # 스크리너 단계는 건너뛴다.
        self._client = kis_client
        self._screener = StockScreener(self._client) if self._client is not None else None
        self._config = config or BacktestConfig()
        self._sentiment_loader = sentiment_loader
        self._per_calculator = per_calculator

    @property
    def config(self) -> BacktestConfig:
        return self._config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, symbol_data: dict[str, pd.DataFrame]) -> BacktestResult:
        """여러 종목에 대해 백테스트를 수행합니다.

        Args:
            symbol_data: ``{"AAPL": df, ...}`` 형태의 딕셔너리.

        Returns:
            통합 :class:`BacktestResult`.
        """

        if not symbol_data:
            return BacktestResult(
                total_return=0.0,
                win_rate=0.0,
                avg_return=0.0,
                max_drawdown=0.0,
                sharpe_ratio=0.0,
            )

        n_symbols = len(symbol_data)
        per_symbol_capital = self._config.initial_capital / n_symbols

        all_trades: list[BacktestTrade] = []
        all_equity_curves: dict[str, list[dict[str, float]]] = {}
        per_symbol_result: dict[str, dict[str, Any]] = {}

        for symbol, df in symbol_data.items():
            result = self._run_single_symbol(symbol, df, per_symbol_capital)
            per_symbol_result[symbol] = result["summary"]
            all_trades.extend(result["trades"])
            all_equity_curves[symbol] = result["equity_curve"]

        # 포트폴리오 단위 지표 집계
        total_final_capital = sum(r["final_capital"] for r in per_symbol_result.values())
        total_return = (total_final_capital - self._config.initial_capital) / self._config.initial_capital * 100

        closed_trades = [t for t in all_trades if t.pnl_pct is not None]
        if closed_trades:
            wins = [t for t in closed_trades if t.pnl_pct and t.pnl_pct > 0]
            avg_return = sum(t.pnl_pct or 0.0 for t in closed_trades) / len(closed_trades)
            win_rate = len(wins) / len(closed_trades) * 100
        else:
            avg_return = 0.0
            win_rate = 0.0

        # 포트폴리오 equity curve는 날짜 기준으로 심플하게 합산
        portfolio_curve: dict[str, float] = {}
        for curve in all_equity_curves.values():
            for point in curve:
                portfolio_curve.setdefault(point["date"], 0.0)
                portfolio_curve[point["date"]] += point["equity"]

        # 날짜 순으로 정렬
        dates_sorted = sorted(portfolio_curve.keys())
        equity_curve = [{"date": d, "equity": round(portfolio_curve[d], 2)} for d in dates_sorted]

        max_dd = self._compute_max_drawdown(equity_curve, self._config.initial_capital)
        sharpe = self._compute_sharpe_ratio(equity_curve)

        return BacktestResult(
            total_return=round(total_return, 2),
            win_rate=round(win_rate, 2),
            avg_return=round(avg_return, 2),
            max_drawdown=round(max_dd, 2),
            sharpe_ratio=round(sharpe, 4),
            trades=all_trades,
            equity_curve=equity_curve,
            per_symbol=per_symbol_result,
        )

    # ------------------------------------------------------------------
    # 내부 구현
    # ------------------------------------------------------------------

    def _run_single_symbol(self, symbol: str, df: pd.DataFrame, initial_capital: float) -> dict[str, Any]:
        """단일 심볼 백테스트.

        ``df`` 는 DatetimeIndex 또는 date-like index 를 가지는 시계열로 가정합니다.
        최소 ``Close`` 컬럼은 필수입니다.
        """

        if df.empty or "Close" not in df.columns:
            logger.warning("백테스트: %s — 데이터 없음", symbol)
            return {
                "summary": {
                    "initial_capital": initial_capital,
                    "final_capital": initial_capital,
                    "total_return": 0.0,
                    "trades": 0,
                },
                "trades": [],
                "equity_curve": [],
            }

        closes = df["Close"].astype(float).tolist()
        dates = [str(d.date()) for d in df.index]

        # RSI & Bollinger 계산 (오래된 순)
        rsi_values = calculate_rsi(closes, period=14)
        bands = calculate_bollinger_bands(closes, period=20, num_std=2.0)

        # PER 품질 스코어 결정
        if self._config.use_per and self._per_calculator is not None:
            per_result = self._per_calculator.get_quality(symbol)
            quality_score = per_result.quality_score
        elif self._screener is not None:
            fundamentals = self._screener.get_fundamentals(symbol)
            screening = self._screener.evaluate_quality(fundamentals)
            quality_score = 25.0 if screening.eligible else 0.0
        else:
            quality_score = 0.0

        capital = initial_capital
        shares = 0
        entry_price = 0.0

        trades: list[BacktestTrade] = []
        equity_curve: list[dict[str, float]] = []

        # 최소 필요한 인덱스 (RSI, 볼린저 모두 유효한 이후부터)
        start_idx = max(14 + 1, 20)  # RSI는 period+1, 볼린저는 period 이후부터 의미 있음
        if len(closes) <= start_idx:
            logger.warning("백테스트: %s — 유효한 캔들이 부족합니다 (%d개)", symbol, len(closes))

        for i in range(start_idx, len(closes)):
            price = closes[i]
            date = dates[i]

            current_rsi = rsi_values[i] if i < len(rsi_values) else 50.0
            # 볼린저 밴드 정보
            current_upper = bands["upper"][i] if i < len(bands["upper"]) else price
            current_lower = bands["lower"][i] if i < len(bands["lower"]) else price

            band_width = current_upper - current_lower
            if band_width > 0:
                percent_b = (price - current_lower) / band_width
            else:
                percent_b = 0.5

            # --- 시그널 스코어 계산 (AutoTrader 로직을 근사) ---
            # 센티멘트: 히스토리컬 F&G 또는 고정 바이어스
            if self._config.use_sentiment and self._sentiment_loader is not None:
                # normalized: -100~+100, 부호 반전(공포→매수기회) 후 ±30 범위
                normalized = self._sentiment_loader.get_normalized_score(date)
                sentiment_score = -normalized / 100.0 * 30.0
            else:
                sentiment_score = self._config.sentiment_bias

            # RSI: 과매도(30 이하) → 매수(+), 과매수(70 이상) → 매도(-)
            rsi_score = (50.0 - current_rsi) * 0.8  # 약 -40~+40 범위
            rsi_score = max(-20.0, min(20.0, rsi_score))

            # 볼린저: 하단(0) 근처 → 매수(+), 상단(1) 근처 → 매도(-)
            bollinger_score = (0.5 - percent_b) * 30.0
            bollinger_score = max(-15.0, min(15.0, bollinger_score))

            technical_score = rsi_score + bollinger_score
            total_score = sentiment_score + quality_score + technical_score
            total_score = max(-100.0, min(100.0, total_score))

            # AutoTrader의 스코어 → 시그널 타입 변환 로직 재사용
            signal_type = AutoTrader._score_to_signal_type(total_score)  # type: ignore[attr-defined]

            # 현재 자산 가치 및 equity curve
            equity = capital + shares * price
            equity_curve.append({"date": date, "equity": round(equity, 2)})

            # 포지션 진입 조건
            if shares == 0 and signal_type in (AutoSignalType.BUY, AutoSignalType.STRONG_BUY):
                target_value = equity * self._config.max_position_pct
                qty = int(target_value // price)
                if qty <= 0:
                    continue
                cost = qty * price
                capital -= cost
                shares = qty
                entry_price = price
                trades.append(
                    BacktestTrade(
                        symbol=symbol,
                        date=date,
                        side="buy",
                        quantity=qty,
                        price=price,
                    )
                )
                continue

            # 포지션 청산 조건
            if shares > 0:
                pnl_pct = (price - entry_price) / entry_price
                should_take_profit = pnl_pct >= self._config.take_profit
                should_stop_loss = pnl_pct <= self._config.stop_loss
                should_sell_signal = signal_type in (AutoSignalType.SELL, AutoSignalType.STRONG_SELL)

                if should_take_profit or should_stop_loss or should_sell_signal:
                    proceeds = shares * price
                    capital += proceeds
                    trades.append(
                        BacktestTrade(
                            symbol=symbol,
                            date=date,
                            side="sell",
                            quantity=shares,
                            price=price,
                            pnl_pct=round(pnl_pct * 100, 2),
                        )
                    )
                    shares = 0
                    entry_price = 0.0

        # 마지막 날 평가 (미청산 포지션이 남아 있으면 그대로 시장가 정산한 것으로 가정)
        if shares > 0:
            final_price = closes[-1]
            final_date = dates[-1]
            pnl_pct = (final_price - entry_price) / entry_price
            capital += shares * final_price
            trades.append(
                BacktestTrade(
                    symbol=symbol,
                    date=final_date,
                    side="sell",
                    quantity=shares,
                    price=final_price,
                    pnl_pct=round(pnl_pct * 100, 2),
                )
            )
            shares = 0

        final_capital = capital
        total_return = (final_capital - initial_capital) / initial_capital * 100

        summary = {
            "initial_capital": round(initial_capital, 2),
            "final_capital": round(final_capital, 2),
            "total_return": round(total_return, 2),
            "trades": len(trades),
        }

        return {"summary": summary, "trades": trades, "equity_curve": equity_curve}

    @staticmethod
    def _compute_max_drawdown(equity_curve: list[dict[str, float]], initial_capital: float) -> float:
        if not equity_curve:
            return 0.0
        max_dd = 0.0
        peak = initial_capital
        for point in equity_curve:
            eq = point["equity"]
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak * 100 if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd
        return max_dd

    @staticmethod
    def _compute_sharpe_ratio(equity_curve: list[dict[str, float]], risk_free_rate: float = 0.02) -> float:
        """단순 샤프 비율 근사 (연환산).

        백테스트 설정의 거래일수 등을 재사용하지 않고, 여기서는
        252 거래일을 기준으로 한다.
        """

        if len(equity_curve) < 2:
            return 0.0

        daily_returns: list[float] = []
        for i in range(1, len(equity_curve)):
            prev = equity_curve[i - 1]["equity"]
            cur = equity_curve[i]["equity"]
            if prev <= 0:
                continue
            daily_returns.append((cur - prev) / prev)

        if not daily_returns:
            return 0.0

        avg_ret = sum(daily_returns) / len(daily_returns)
        variance = sum((r - avg_ret) ** 2 for r in daily_returns) / len(daily_returns)
        std = variance ** 0.5
        if std == 0:
            return 0.0

        trading_days = 252
        annualized_ret = avg_ret * trading_days
        annualized_std = std * (trading_days**0.5)
        return (annualized_ret - risk_free_rate) / annualized_std


def _parse_symbols(arg: str | list[str]) -> list[str]:
    if isinstance(arg, list):
        return arg
    return [s for s in arg.split(" ") if s]


def main(argv: list[str] | None = None) -> None:
    """CLI 엔트리포인트.

    Example::

        python -m src.backtest.engine --symbols 005930.KS AAPL --period 6mo
    """

    import argparse

    from src.backtest.data_loader import load_history

    parser = argparse.ArgumentParser(description="AutoTrader 백테스트 실행")
    parser.add_argument("--symbols", nargs="+", required=True, help="백테스트 대상 심볼들")
    parser.add_argument("--period", default="6mo", help="yfinance period 문자열 (기본 6mo)")
    parser.add_argument("--interval", default="1d", help="캔들 간격 (기본 1d)")
    parser.add_argument("--initial-capital", type=float, default=10_000_000.0)
    parser.add_argument("--sentiment-bias", type=float, default=0.0)

    args = parser.parse_args(argv)

    symbols = _parse_symbols(args.symbols)
    config = BacktestConfig(
        initial_capital=args.initial_capital,
        sentiment_bias=args.sentiment_bias,
    )
    engine = BacktestEngine(config=config)

    symbol_data: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        logger.info("히스토리컬 데이터 로딩: %s (period=%s, interval=%s)", symbol, args.period, args.interval)
        df = load_history(symbol, period=args.period, interval=args.interval)
        symbol_data[symbol] = df

    result = engine.run(symbol_data)

    from src.backtest.reporter import format_backtest_report

    report = format_backtest_report(result)
    print(report)


if __name__ == "__main__":  # pragma: no cover - CLI 진입점
    main()

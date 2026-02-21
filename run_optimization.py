"""파라미터 최적화 실행 스크립트."""
import sys
sys.path.insert(0, ".")

from src.backtest.data_loader import load_history
from src.backtest.engine import BacktestConfig, BacktestEngine
from src.backtest.historical_sentiment import HistoricalFearGreedLoader
from src.backtest.historical_per import HistoricalPERCalculator
from src.backtest.optimizer import ParamGrid, ParameterOptimizer, format_optimization_report
from src.backtest.reporter import format_backtest_report

SYMBOLS = ["AAPL", "MSFT", "NVDA", "QQQ"]
PERIOD = "6mo"
INITIAL_CAPITAL = 10_000_000.0


def main():
    # Load data once
    print("데이터 로딩...")
    symbol_data = {}
    for s in SYMBOLS:
        print(f"  {s}...")
        df = load_history(s, period=PERIOD, interval="1d")
        symbol_data[s] = df
        print(f"  {s}: {len(df)} candles")

    # Load sentiment
    print("센티멘트 데이터 로딩...")
    sentiment_loader = HistoricalFearGreedLoader()
    sentiment_loader.load()
    per_calculator = HistoricalPERCalculator()

    # ── Before: 기존 파라미터 ──
    print("\n" + "=" * 60)
    print("  BEFORE — 기존 파라미터")
    print("=" * 60)
    before_config = BacktestConfig(
        initial_capital=INITIAL_CAPITAL,
        use_sentiment=True,
        use_per=True,
        buy_threshold=40.0,
        sell_threshold=-30.0,
        stop_loss=-0.07,
        take_profit=0.15,
        min_trade_interval_days=0,
    )
    before_engine = BacktestEngine(
        config=before_config,
        sentiment_loader=sentiment_loader,
        per_calculator=per_calculator,
    )
    before_result = before_engine.run(symbol_data)
    print(format_backtest_report(before_result, before_config))

    # Per-symbol
    for sym, s in before_result.per_symbol.items():
        sym_trades = [t for t in before_result.trades if t.symbol == sym and t.pnl_pct is not None]
        wins = len([t for t in sym_trades if t.pnl_pct > 0])
        wr = (wins / len(sym_trades) * 100) if sym_trades else 0
        print(f"  {sym}: 수익률={s['total_return']:+.2f}%, 승률={wr:.0f}%, 거래={s['trades']}건")

    # ── 최적화 ──
    print("\n" + "=" * 60)
    print("  파라미터 최적화 (Grid Search)")
    print("=" * 60)

    base_config = BacktestConfig(
        initial_capital=INITIAL_CAPITAL,
        use_sentiment=True,
        use_per=True,
    )
    optimizer = ParameterOptimizer(
        symbol_data=symbol_data,
        base_config=base_config,
        sentiment_loader=sentiment_loader,
        per_calculator=per_calculator,
    )
    results = optimizer.optimize(metric="sharpe_ratio")

    print("\n  Top 10 (Sharpe 기준):")
    print(format_optimization_report(results, top_n=10))

    # ── After: 최적 파라미터 ──
    best = results[0]
    print(f"\n최적 파라미터: {best.params}")

    print("\n" + "=" * 60)
    print("  AFTER — 최적 파라미터")
    print("=" * 60)
    after_config = BacktestConfig(
        initial_capital=INITIAL_CAPITAL,
        use_sentiment=True,
        use_per=True,
        buy_threshold=best.params["buy_threshold"],
        sell_threshold=best.params["sell_threshold"],
        stop_loss=best.params["stop_loss"],
        take_profit=best.params["take_profit"],
        min_trade_interval_days=best.params["min_trade_interval_days"],
    )
    after_engine = BacktestEngine(
        config=after_config,
        sentiment_loader=sentiment_loader,
        per_calculator=per_calculator,
    )
    after_result = after_engine.run(symbol_data)
    print(format_backtest_report(after_result, after_config))

    for sym, s in after_result.per_symbol.items():
        sym_trades = [t for t in after_result.trades if t.symbol == sym and t.pnl_pct is not None]
        wins = len([t for t in sym_trades if t.pnl_pct > 0])
        wr = (wins / len(sym_trades) * 100) if sym_trades else 0
        print(f"  {sym}: 수익률={s['total_return']:+.2f}%, 승률={wr:.0f}%, 거래={s['trades']}건")

    # ── 비교표 ──
    print("\n" + "=" * 60)
    print("  Before vs After 비교")
    print("=" * 60)
    print(f"  {'':20} {'Before':>12} {'After':>12} {'Change':>12}")
    print(f"  {'-'*56}")
    print(f"  {'총수익률':20} {before_result.total_return:>+11.2f}% {after_result.total_return:>+11.2f}% {after_result.total_return - before_result.total_return:>+11.2f}%p")
    print(f"  {'승률':20} {before_result.win_rate:>11.1f}% {after_result.win_rate:>11.1f}% {after_result.win_rate - before_result.win_rate:>+11.1f}%p")
    print(f"  {'MDD':20} {before_result.max_drawdown:>11.2f}% {after_result.max_drawdown:>11.2f}% {after_result.max_drawdown - before_result.max_drawdown:>+11.2f}%p")
    print(f"  {'샤프비율':20} {before_result.sharpe_ratio:>12.4f} {after_result.sharpe_ratio:>12.4f} {after_result.sharpe_ratio - before_result.sharpe_ratio:>+12.4f}")
    before_trades = len([t for t in before_result.trades if t.pnl_pct is not None])
    after_trades = len([t for t in after_result.trades if t.pnl_pct is not None])
    print(f"  {'거래횟수':20} {before_trades:>12} {after_trades:>12} {after_trades - before_trades:>+12}")

    print(f"\n  최적 파라미터:")
    for k, v in best.params.items():
        print(f"    {k}: {v}")


if __name__ == "__main__":
    main()

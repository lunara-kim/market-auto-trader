"""미국 종목 백테스트 실행 스크립트."""
import sys
sys.path.insert(0, ".")

from src.backtest.data_loader import load_history
from src.backtest.engine import BacktestConfig, BacktestEngine
from src.backtest.historical_sentiment import HistoricalFearGreedLoader
from src.backtest.historical_per import HistoricalPERCalculator
from src.backtest.reporter import format_backtest_report

SYMBOLS = ["AAPL", "MSFT", "NVDA", "QQQ"]
PERIOD = "6mo"
INITIAL_CAPITAL = 10_000_000.0

def run(use_sentiment: bool, use_per: bool, label: str):
    config = BacktestConfig(
        initial_capital=INITIAL_CAPITAL,
        use_sentiment=use_sentiment,
        use_per=use_per,
    )

    sentiment_loader = None
    per_calculator = None

    if use_sentiment:
        sentiment_loader = HistoricalFearGreedLoader()
        sentiment_loader.load()

    if use_per:
        per_calculator = HistoricalPERCalculator()

    engine = BacktestEngine(config=config, sentiment_loader=sentiment_loader, per_calculator=per_calculator)

    symbol_data = {}
    for s in SYMBOLS:
        print(f"Loading {s}...")
        df = load_history(s, period=PERIOD, interval="1d")
        symbol_data[s] = df

    result = engine.run(symbol_data)
    report = format_backtest_report(result, config)
    print(f"\n{'='*50}")
    print(f"  {label}")
    print(f"{'='*50}")
    print(report)

    # Per-symbol details
    print("\n--- 종목별 상세 ---")
    for sym, summary in result.per_symbol.items():
        init = summary['initial_capital']
        final = summary['final_capital']
        ret = summary['total_return']
        trades = summary['trades']
        # Calculate per-symbol win rate and MDD
        sym_trades = [t for t in result.trades if t.symbol == sym and t.pnl_pct is not None]
        wins = [t for t in sym_trades if t.pnl_pct > 0]
        win_rate = (len(wins)/len(sym_trades)*100) if sym_trades else 0
        avg_ret = (sum(t.pnl_pct for t in sym_trades)/len(sym_trades)) if sym_trades else 0

        # MDD from equity curve
        sym_curve = [p for p in result.equity_curve]  # portfolio level
        print(f"  {sym}: 수익률={ret:+.2f}%, 승률={win_rate:.1f}%, 평균수익={avg_ret:+.2f}%, 거래={trades}건, 최종자본={final:,.0f}원")

    print(f"\n  포트폴리오 MDD: {result.max_drawdown:.2f}%")
    print(f"  포트폴리오 샤프: {result.sharpe_ratio:.4f}")
    return result

if __name__ == "__main__":
    print("=" * 60)
    print("  미국 종목 AutoTrader 시그널 백테스트 (최근 6개월)")
    print("=" * 60)

    # Run with sentiment + PER
    r1 = run(use_sentiment=True, use_per=True, label="WITH Sentiment + PER")

    # Run without for comparison
    r2 = run(use_sentiment=False, use_per=False, label="WITHOUT Sentiment/PER (baseline)")

    print("\n" + "=" * 60)
    print("  센티멘트/PER 반영 효과 비교")
    print("=" * 60)
    print(f"  WITH    : 총수익률 {r1.total_return:+.2f}%, 승률 {r1.win_rate:.1f}%, MDD {r1.max_drawdown:.2f}%")
    print(f"  WITHOUT : 총수익률 {r2.total_return:+.2f}%, 승률 {r2.win_rate:.1f}%, MDD {r2.max_drawdown:.2f}%")
    diff = r1.total_return - r2.total_return
    print(f"  차이    : {diff:+.2f}%p")

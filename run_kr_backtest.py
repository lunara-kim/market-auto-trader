"""한국 주식 KOSPI TOP10 6개월 백테스트."""
import sys
sys.path.insert(0, ".")

from src.backtest.data_loader import load_history
from src.backtest.engine import BacktestEngine, BacktestConfig
from src.backtest.historical_sentiment import HistoricalFearGreedLoader
from src.backtest.historical_per import HistoricalPERCalculator

SYMBOLS = {
    "005930.KS": "삼성전자",
    "000660.KS": "SK하이닉스",
    "005380.KS": "현대차",
    "373220.KS": "LG에너지솔루션",
    "207940.KS": "삼성바이오로직스",
    "035420.KS": "NAVER",
    "035720.KS": "카카오",
    "005490.KS": "POSCO홀딩스",
    "000270.KS": "기아",
    "259960.KS": "크래프톤",
}

INITIAL_CAPITAL = 10_000_000

# Load price data
print("=" * 60)
print("📊 한국 주식 6개월 백테스트")
print("=" * 60)

print("\n[1/4] 가격 데이터 로딩...")
symbol_data = {}
for sym, name in SYMBOLS.items():
    df = load_history(sym, period="6mo", interval="1d")
    print(f"  {name}({sym}): {len(df)}일치")
    symbol_data[sym] = df

# Load sentiment
print("\n[2/4] Fear & Greed 센티멘트 로딩...")
sentiment_loader = HistoricalFearGreedLoader()
sentiment_loader.load()

# PER calculator
print("\n[3/4] PER 데이터 로딩...")
per_calculator = HistoricalPERCalculator()

# ===== Run 1: WITHOUT sentiment/PER (baseline) =====
print("\n[4/4] 백테스트 실행 중...")
print("\n" + "=" * 60)
print("📈 [A] 기본 전략 (센티멘트/PER 미반영)")
print("=" * 60)

config_base = BacktestConfig(
    initial_capital=INITIAL_CAPITAL,
    use_sentiment=False,
    use_per=False,
    use_trailing_stop=True,
)
engine_base = BacktestEngine(config=config_base)
result_base = engine_base.run(symbol_data)

print(f"\n💰 포트폴리오 전체 성과:")
print(f"  총 수익률: {result_base.total_return:+.2f}%")
print(f"  승률: {result_base.win_rate:.1f}%")
print(f"  평균 수익률: {result_base.avg_return:+.2f}%")
print(f"  최대 낙폭: {result_base.max_drawdown:.2f}%")
print(f"  샤프 비율: {result_base.sharpe_ratio:.4f}")

print(f"\n📋 종목별 성과:")
print(f"  {'종목':20s} {'수익률':>10s} {'거래수':>8s} {'최종자본':>14s}")
print(f"  {'-'*20} {'-'*10} {'-'*8} {'-'*14}")
for sym, info in result_base.per_symbol.items():
    name = SYMBOLS.get(sym, sym)
    ret = info['total_return']
    trades = info['trades']
    final = info['final_capital']
    print(f"  {name:20s} {ret:+9.2f}% {trades:>8d} {final:>13,.0f}원")

# ===== Run 2: WITH sentiment + PER =====
print("\n" + "=" * 60)
print("📈 [B] 강화 전략 (센티멘트+PER+트레일링스톱)")
print("=" * 60)

config_enhanced = BacktestConfig(
    initial_capital=INITIAL_CAPITAL,
    use_sentiment=True,
    use_per=True,
    use_trailing_stop=True,
)
engine_enhanced = BacktestEngine(
    config=config_enhanced,
    sentiment_loader=sentiment_loader,
    per_calculator=per_calculator,
)
result_enhanced = engine_enhanced.run(symbol_data)

print(f"\n💰 포트폴리오 전체 성과:")
print(f"  총 수익률: {result_enhanced.total_return:+.2f}%")
print(f"  승률: {result_enhanced.win_rate:.1f}%")
print(f"  평균 수익률: {result_enhanced.avg_return:+.2f}%")
print(f"  최대 낙폭: {result_enhanced.max_drawdown:.2f}%")
print(f"  샤프 비율: {result_enhanced.sharpe_ratio:.4f}")

print(f"\n📋 종목별 성과:")
print(f"  {'종목':20s} {'수익률':>10s} {'거래수':>8s} {'최종자본':>14s}")
print(f"  {'-'*20} {'-'*10} {'-'*8} {'-'*14}")
for sym, info in result_enhanced.per_symbol.items():
    name = SYMBOLS.get(sym, sym)
    ret = info['total_return']
    trades = info['trades']
    final = info['final_capital']
    print(f"  {name:20s} {ret:+9.2f}% {trades:>8d} {final:>13,.0f}원")

# Trade details for enhanced
closed = [t for t in result_enhanced.trades if t.pnl_pct is not None]
wins = [t for t in closed if t.pnl_pct and t.pnl_pct > 0]
losses = [t for t in closed if t.pnl_pct is not None and t.pnl_pct <= 0]

print(f"\n📊 거래 상세:")
print(f"  총 매매 횟수: {len(result_enhanced.trades)}건 (매수+매도)")
print(f"  청산 거래: {len(closed)}건")
print(f"  수익 거래: {len(wins)}건")
print(f"  손실 거래: {len(losses)}건")
if wins:
    print(f"  최대 수익: +{max(t.pnl_pct for t in wins):.2f}%")
if losses:
    print(f"  최대 손실: {min(t.pnl_pct for t in losses):.2f}%")

# ===== Comparison =====
print("\n" + "=" * 60)
print("🔄 전략 비교 (Before vs After)")
print("=" * 60)
print(f"  {'지표':20s} {'기본':>12s} {'강화(센티+PER)':>14s} {'차이':>10s}")
print(f"  {'-'*20} {'-'*12} {'-'*14} {'-'*10}")

def cmp(label, a, b, fmt=".2f", suffix="%"):
    diff = b - a
    print(f"  {label:20s} {a:>11{fmt}}{suffix} {b:>13{fmt}}{suffix} {diff:>+9{fmt}}{suffix}")

cmp("총 수익률", result_base.total_return, result_enhanced.total_return)
cmp("승률", result_base.win_rate, result_enhanced.win_rate)
cmp("평균 수익률", result_base.avg_return, result_enhanced.avg_return)
cmp("최대 낙폭", result_base.max_drawdown, result_enhanced.max_drawdown)
cmp("샤프 비율", result_base.sharpe_ratio, result_enhanced.sharpe_ratio, ".4f", "")

print("\n✅ 백테스트 완료!")

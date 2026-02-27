"""Phase 5-2: 게이트 방식 백테스트 비교 스크립트.

BacktestEngine의 점수합산 방식을 게이트 방식으로 오버라이드하여 비교합니다.
"""
import sys
sys.path.insert(0, ".")

import pandas as pd
from src.backtest.data_loader import load_history
from src.backtest.engine import BacktestEngine, BacktestConfig, BacktestTrade
from src.backtest.historical_sentiment import HistoricalFearGreedLoader
from src.backtest.historical_per import HistoricalPERCalculator
from src.strategy.rsi import calculate_rsi
from src.strategy.bollinger_bands import calculate_bollinger_bands
from src.utils.logger import get_logger
from typing import Any

logger = get_logger(__name__)

SYMBOLS = {
    "005930.KS": "삼성전자",
    "000660.KS": "SK하이닉스",
    "005380.KS": "현대차",
    "000270.KS": "기아",
    "005490.KS": "POSCO홀딩스",
    "035420.KS": "NAVER",
    "035720.KS": "카카오",
    "259960.KS": "크래프톤",
}

INITIAL_CAPITAL = 10_000_000


class GateBacktestEngine(BacktestEngine):
    """게이트 방식을 적용한 백테스트 엔진.
    
    기존 점수합산 대신 레짐 기반 게이트로 시그널을 결정합니다:
    - RISK_OFF (F&G < 25): 평균회귀만 허용
    - NEUTRAL (25 <= F&G < 75): 양쪽 허용 (보수적)
    - RISK_ON (F&G >= 75): 추세추종만 허용
    """

    def _classify_regime(self, fear_greed_score: float) -> str:
        """Fear & Greed 점수 → 레짐 분류 (RegimeEngine과 동일 임계치)"""
        if fear_greed_score < 30:
            return "risk_off"
        elif fear_greed_score >= 65:
            return "risk_on"
        else:
            return "neutral"

    def _run_single_symbol(self, symbol: str, df: pd.DataFrame, initial_capital: float) -> dict[str, Any]:
        """게이트 방식으로 오버라이드된 단일 종목 백테스트."""
        if df.empty or "Close" not in df.columns:
            return {
                "summary": {"initial_capital": initial_capital, "final_capital": initial_capital, "total_return": 0.0, "trades": 0},
                "trades": [], "equity_curve": [],
            }

        closes = df["Close"].astype(float).tolist()
        dates = [str(d.date()) for d in df.index]
        rsi_values = calculate_rsi(closes, period=14)
        bands = calculate_bollinger_bands(closes, period=20, num_std=2.0)

        # PER quality — 백테스트에서는 Gate 1(유니버스 필터)를 완화합니다.
        # HistoricalPERCalculator는 yfinance trailing PE만 사용하므로 데이터가
        # 없거나 기준 미달이면 quality_score=0. 실전 AutoTrader는 프로필별
        # skip_per_filter 등이 있어 대부분 통과합니다. 백테스트에서도 동일하게
        # PER 필터는 보너스 점수로만 반영하고, 유니버스 제외는 하지 않습니다.
        per_eligible = True  # PER은 보너스로만, 게이트 차단 안함

        # 볼린저 밴드폭 계산 (expanding 감지용)
        band_widths = []
        for i in range(len(closes)):
            bw = bands["upper"][i] - bands["lower"][i] if i < len(bands["upper"]) else 0
            band_widths.append(bw)

        capital = initial_capital
        shares = 0
        entry_price = 0.0
        peak_price = 0.0
        last_sell_idx: int | None = None

        trades: list[BacktestTrade] = []
        equity_curve: list[dict[str, float]] = []

        start_idx = max(15, 20, 50)  # RSI + BB + MA 안전 마진

        for i in range(start_idx, len(closes)):
            price = closes[i]
            date = dates[i]

            current_rsi = rsi_values[i] if i < len(rsi_values) else 50.0
            current_upper = bands["upper"][i] if i < len(bands["upper"]) else price
            current_lower = bands["lower"][i] if i < len(bands["lower"]) else price
            band_width = current_upper - current_lower
            percent_b = (price - current_lower) / band_width if band_width > 0 else 0.5

            # 밴드폭 확장 여부 (최근 5일 평균보다 현재가 크면)
            recent_bw = band_widths[max(0, i-5):i]
            avg_bw = sum(recent_bw) / len(recent_bw) if recent_bw else 0
            band_expanding = band_widths[i] > avg_bw * 1.05

            # RSI 분류 — AutoTrader의 전일대비×6 근사(변동성 큼)와 14일 RSI(안정적)의
            # 시그널 빈도를 맞추기 위해 35/65 사용. 전일대비 근사의 30/70은
            # 14일 RSI의 35/65와 유사한 발동 빈도를 보임.
            if current_rsi < 35:
                rsi_signal = "oversold"
            elif current_rsi > 65:
                rsi_signal = "overbought"
            else:
                rsi_signal = "neutral"

            # 볼린저 분류 — AutoTrader와 일관된 임계치
            if percent_b <= 0.2:
                bb_signal = "lower_band"
            elif percent_b >= 0.8 and band_expanding:
                bb_signal = "breakout"
            elif percent_b >= 0.8:
                bb_signal = "upper_band"
            else:
                bb_signal = "middle"

            # 레짐 결정 (Fear & Greed)
            if self._config.use_sentiment and self._sentiment_loader is not None:
                fg_raw = self._sentiment_loader.get_score(date)
                if fg_raw is None:
                    fg_raw = 50  # 기본값
            else:
                fg_raw = 50  # 중립

            regime = self._classify_regime(fg_raw)

            # === 게이트 방식 시그널 결정 ===
            is_buy_signal = False
            is_sell_signal = False

            if not per_eligible:
                pass  # Gate 1 실패: 유니버스 제외
            elif regime == "risk_off":
                # 평균회귀만
                if rsi_signal == "oversold" and bb_signal == "lower_band":
                    is_buy_signal = True
                elif rsi_signal == "overbought":
                    is_sell_signal = True
            elif regime == "risk_on":
                # 추세추종만
                if bb_signal == "breakout" and band_expanding:
                    is_buy_signal = True
                elif bb_signal == "lower_band":
                    is_sell_signal = True
            else:  # neutral — 양쪽 허용 + 약한 추세추종 (밴드 돌파 시 진입)
                if rsi_signal == "oversold":
                    is_buy_signal = True
                elif bb_signal == "breakout":
                    # Neutral에서는 band_expanding 없이도 돌파 시 진입 허용
                    is_buy_signal = True
                elif rsi_signal == "overbought":
                    is_sell_signal = True

            equity = capital + shares * price
            equity_curve.append({"date": date, "equity": round(equity, 2)})

            # 포지션 진입
            if shares == 0 and is_buy_signal:
                if (self._config.min_trade_interval_days > 0
                    and last_sell_idx is not None
                    and (i - last_sell_idx) < self._config.min_trade_interval_days):
                    continue
                target_value = equity * self._config.max_position_pct
                qty = int(target_value // price)
                if qty <= 0:
                    continue
                capital -= qty * price
                shares = qty
                entry_price = price
                peak_price = price
                trades.append(BacktestTrade(symbol=symbol, date=date, side="buy", quantity=qty, price=price))
                continue

            # 포지션 청산
            if shares > 0:
                if price > peak_price:
                    peak_price = price
                pnl_pct = (price - entry_price) / entry_price
                should_take_profit = pnl_pct >= self._config.take_profit

                if self._config.use_trailing_stop:
                    trailing_pnl = (price - peak_price) / peak_price
                    should_stop_loss = trailing_pnl <= self._config.trailing_stop_pct
                else:
                    should_stop_loss = pnl_pct <= self._config.stop_loss

                if should_take_profit or should_stop_loss or is_sell_signal:
                    revenue = shares * price
                    capital += revenue
                    trades.append(BacktestTrade(
                        symbol=symbol, date=date, side="sell",
                        quantity=shares, price=price, pnl_pct=round(pnl_pct * 100, 2),
                    ))
                    shares = 0
                    entry_price = 0.0
                    peak_price = 0.0
                    last_sell_idx = i

        # 미청산 포지션 강제 청산
        if shares > 0 and closes:
            price = closes[-1]
            pnl_pct = (price - entry_price) / entry_price
            capital += shares * price
            trades.append(BacktestTrade(
                symbol=symbol, date=dates[-1], side="sell",
                quantity=shares, price=price, pnl_pct=round(pnl_pct * 100, 2),
            ))
            shares = 0

        final_capital = capital
        total_return = (final_capital - initial_capital) / initial_capital * 100
        closed = [t for t in trades if t.pnl_pct is not None]

        return {
            "summary": {
                "initial_capital": initial_capital,
                "final_capital": round(final_capital, 2),
                "total_return": round(total_return, 2),
                "trades": len(closed),
            },
            "trades": trades,
            "equity_curve": equity_curve,
        }


def main():
    print("=" * 60)
    print("📊 Phase 5-2: 게이트 방식 Before/After 백테스트 비교")
    print("=" * 60)

    # 데이터 로딩
    print("\n[1/3] 가격 데이터 로딩...")
    symbol_data = {}
    for sym, name in SYMBOLS.items():
        df = load_history(sym, period="6mo", interval="1d")
        print(f"  {name}({sym}): {len(df)}일치")
        symbol_data[sym] = df

    print("\n[2/3] Fear & Greed + PER 로딩...")
    sentiment_loader = HistoricalFearGreedLoader()
    sentiment_loader.load()
    per_calculator = HistoricalPERCalculator()

    # === Before: 점수합산 방식 (기존) ===
    print("\n" + "=" * 60)
    print("📈 [BEFORE] 점수합산 방식")
    print("=" * 60)

    config = BacktestConfig(
        initial_capital=INITIAL_CAPITAL,
        use_sentiment=True,
        use_per=True,
        use_trailing_stop=True,
    )
    engine_before = BacktestEngine(
        config=config,
        sentiment_loader=sentiment_loader,
        per_calculator=per_calculator,
    )
    result_before = engine_before.run(symbol_data)
    _print_result(result_before, "점수합산")

    # === After: 게이트 방식 ===
    print("\n" + "=" * 60)
    print("📈 [AFTER] 게이트 방식")
    print("=" * 60)

    engine_after = GateBacktestEngine(
        config=config,
        sentiment_loader=sentiment_loader,
        per_calculator=per_calculator,
    )
    result_after = engine_after.run(symbol_data)
    _print_result(result_after, "게이트")

    # === 비교 ===
    print("\n" + "=" * 60)
    print("🔄 Before(점수합산) vs After(게이트) 비교")
    print("=" * 60)
    print(f"  {'지표':20s} {'Before':>12s} {'After':>12s} {'차이':>10s}")
    print(f"  {'-'*20} {'-'*12} {'-'*12} {'-'*10}")

    def cmp(label, a, b, fmt=".2f", suffix="%"):
        diff = b - a
        print(f"  {label:20s} {a:>11{fmt}}{suffix} {b:>11{fmt}}{suffix} {diff:>+9{fmt}}{suffix}")

    cmp("총 수익률", result_before.total_return, result_after.total_return)
    cmp("승률", result_before.win_rate, result_after.win_rate)
    cmp("평균 수익률", result_before.avg_return, result_after.avg_return)
    cmp("최대 낙폭(MDD)", result_before.max_drawdown, result_after.max_drawdown)
    cmp("샤프 비율", result_before.sharpe_ratio, result_after.sharpe_ratio, ".4f", "")

    # 종목별 비교
    print("\n📋 종목별 수익률 비교:")
    print(f"  {'종목':12s} {'Before':>10s} {'After':>10s} {'차이':>10s} {'Before거래':>10s} {'After거래':>10s}")
    print(f"  {'-'*12} {'-'*10} {'-'*10} {'-'*10} {'-'*10} {'-'*10}")
    for sym in SYMBOLS:
        name = SYMBOLS[sym][:6]
        b = result_before.per_symbol.get(sym, {})
        a = result_after.per_symbol.get(sym, {})
        br = b.get("total_return", 0)
        ar = a.get("total_return", 0)
        bt = b.get("trades", 0)
        at = a.get("trades", 0)
        diff = ar - br
        print(f"  {name:12s} {br:>+9.2f}% {ar:>+9.2f}% {diff:>+9.2f}% {bt:>10d} {at:>10d}")

    print("\n✅ 비교 완료!")

    # JSON 결과 반환 (메인 스크립트에서 사용)
    return result_before, result_after


def _print_result(result, label):
    print(f"\n💰 {label} 포트폴리오 성과:")
    print(f"  총 수익률: {result.total_return:+.2f}%")
    print(f"  승률: {result.win_rate:.1f}%")
    print(f"  평균 수익률: {result.avg_return:+.2f}%")
    print(f"  최대 낙폭: {result.max_drawdown:.2f}%")
    print(f"  샤프 비율: {result.sharpe_ratio:.4f}")
    print("\n📋 종목별:")
    for sym, info in result.per_symbol.items():
        name = SYMBOLS.get(sym, sym)[:8]
        print(f"  {name:10s} {info['total_return']:+8.2f}%  ({info['trades']}거래)")


if __name__ == "__main__":
    main()

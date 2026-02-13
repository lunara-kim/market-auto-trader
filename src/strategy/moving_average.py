"""
이동평균 교차 전략 (Moving Average Crossover Strategy)

골든크로스(단기 MA > 장기 MA)와 데드크로스(단기 MA < 장기 MA)를
기반으로 매매 신호를 생성하는 기본 전략입니다.

지원하는 이동평균 종류:
- SMA (Simple Moving Average, 단순이동평균)
- EMA (Exponential Moving Average, 지수이동평균)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from config.backtest import backtest_settings
from config.trading import trading_settings
from src.strategy.base import BaseStrategy
from src.utils.logger import get_logger

logger = get_logger(__name__)


class MAType(str, Enum):
    """이동평균 종류"""

    SMA = "sma"
    EMA = "ema"


class SignalType(str, Enum):
    """매매 신호 종류"""

    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class MAConfig:
    """이동평균 교차 전략 설정"""

    short_window: int = 5      # 단기 이동평균 기간
    long_window: int = 20      # 장기 이동평균 기간
    ma_type: MAType = MAType.SMA
    signal_threshold: float = 0.0  # 교차 시 최소 차이 비율 (노이즈 필터)

    def __post_init__(self) -> None:
        if self.short_window >= self.long_window:
            msg = (
                f"단기 기간({self.short_window})은 "
                f"장기 기간({self.long_window})보다 작아야 합니다"
            )
            raise ValueError(msg)
        if self.short_window < 2:
            msg = "단기 기간은 최소 2 이상이어야 합니다"
            raise ValueError(msg)


@dataclass
class AnalysisResult:
    """분석 결과 데이터 클래스"""

    short_ma: list[float] = field(default_factory=list)
    long_ma: list[float] = field(default_factory=list)
    prices: list[float] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)
    current_short_ma: float = 0.0
    current_long_ma: float = 0.0
    prev_short_ma: float = 0.0
    prev_long_ma: float = 0.0
    current_price: float = 0.0
    ma_spread: float = 0.0         # (단기MA - 장기MA) / 장기MA * 100
    price_vs_short: float = 0.0    # (현재가 - 단기MA) / 단기MA * 100
    trend: str = "neutral"          # uptrend / downtrend / neutral

    def to_dict(self) -> dict[str, Any]:
        return {
            "short_ma": self.short_ma,
            "long_ma": self.long_ma,
            "prices": self.prices,
            "dates": self.dates,
            "current_short_ma": self.current_short_ma,
            "current_long_ma": self.current_long_ma,
            "prev_short_ma": self.prev_short_ma,
            "prev_long_ma": self.prev_long_ma,
            "current_price": self.current_price,
            "ma_spread": round(self.ma_spread, 4),
            "price_vs_short": round(self.price_vs_short, 4),
            "trend": self.trend,
        }


def calculate_sma(prices: list[float], window: int) -> list[float]:
    """
    단순이동평균(SMA) 계산

    Args:
        prices: 종가 리스트 (오래된 순)
        window: 이동평균 기간

    Returns:
        SMA 값 리스트 (window-1개는 0.0)
    """
    if len(prices) < window:
        return []

    result: list[float] = [0.0] * (window - 1)

    # 첫 번째 SMA는 직접 계산
    window_sum = sum(prices[:window])
    result.append(window_sum / window)

    # 이후는 슬라이딩 윈도우로 효율적으로 계산
    for i in range(window, len(prices)):
        window_sum += prices[i] - prices[i - window]
        result.append(window_sum / window)

    return result


def calculate_ema(prices: list[float], window: int) -> list[float]:
    """
    지수이동평균(EMA) 계산

    최근 데이터에 더 큰 가중치를 부여합니다.
    multiplier = 2 / (window + 1)

    Args:
        prices: 종가 리스트 (오래된 순)
        window: 이동평균 기간

    Returns:
        EMA 값 리스트 (window-1개는 0.0)
    """
    if len(prices) < window:
        return []

    result: list[float] = [0.0] * (window - 1)
    multiplier = 2.0 / (window + 1)

    # 첫 EMA = 첫 window개의 SMA
    first_sma = sum(prices[:window]) / window
    result.append(first_sma)

    # 이후 EMA = (현재가 - 이전 EMA) * multiplier + 이전 EMA
    for i in range(window, len(prices)):
        ema = (prices[i] - result[-1]) * multiplier + result[-1]
        result.append(ema)

    return result


class MovingAverageCrossover(BaseStrategy):
    """
    이동평균 교차 전략

    골든크로스 (단기 MA가 장기 MA를 상향 돌파) → 매수 신호
    데드크로스 (단기 MA가 장기 MA를 하향 돌파) → 매도 신호

    Usage::

        config = MAConfig(short_window=5, long_window=20, ma_type=MAType.SMA)
        strategy = MovingAverageCrossover(config)

        # 분석
        analysis = strategy.analyze({"prices": [...], "dates": [...]})

        # 신호 생성
        signal = strategy.generate_signal(analysis)

        # 백테스팅
        result = strategy.backtest(historical_data, initial_capital=10_000_000)
    """

    def __init__(self, config: MAConfig | None = None) -> None:
        self.config = config or MAConfig()
        name = (
            f"MA_Crossover_{self.config.ma_type.value.upper()}"
            f"({self.config.short_window},{self.config.long_window})"
        )
        super().__init__(name=name)
        logger.info(
            "이동평균 교차 전략 설정: %s기간=%d/%d, 임계값=%.4f",
            self.config.ma_type.value.upper(),
            self.config.short_window,
            self.config.long_window,
            self.config.signal_threshold,
        )

    def _calculate_ma(self, prices: list[float], window: int) -> list[float]:
        """설정된 MA 종류에 따라 이동평균 계산"""
        if self.config.ma_type == MAType.EMA:
            return calculate_ema(prices, window)
        return calculate_sma(prices, window)

    def analyze(self, market_data: dict[str, Any]) -> dict[str, Any]:
        """
        시장 데이터 분석 — 이동평균 계산 + 트렌드 판단

        Args:
            market_data: {
                "prices": list[float],     # 종가 리스트 (오래된 순, 필수)
                "dates": list[str],        # 날짜 리스트 (선택)
                "stock_code": str,         # 종목 코드 (선택)
            }

        Returns:
            AnalysisResult.to_dict()
        """
        prices: list[float] = market_data.get("prices", [])
        dates: list[str] = market_data.get("dates", [])
        stock_code: str = market_data.get("stock_code", "unknown")

        min_required = self.config.long_window + 1  # 교차 판단에 최소 +1 필요
        if len(prices) < min_required:
            logger.warning(
                "[%s] 데이터 부족: %d개 (최소 %d개 필요)",
                stock_code, len(prices), min_required,
            )
            return AnalysisResult(
                prices=prices,
                dates=dates,
                current_price=prices[-1] if prices else 0.0,
            ).to_dict()

        short_ma = self._calculate_ma(prices, self.config.short_window)
        long_ma = self._calculate_ma(prices, self.config.long_window)

        current_price = prices[-1]
        current_short = short_ma[-1]
        current_long = long_ma[-1]
        prev_short = short_ma[-2]
        prev_long = long_ma[-2]

        # MA 스프레드: 양수면 단기 > 장기 (상승 추세)
        ma_spread = (
            (current_short - current_long) / current_long * 100
            if current_long != 0 else 0.0
        )

        # 현재가 vs 단기 MA
        price_vs_short = (
            (current_price - current_short) / current_short * 100
            if current_short != 0 else 0.0
        )

        # 트렌드 판단
        if ma_spread > 0.5:
            trend = "uptrend"
        elif ma_spread < -0.5:
            trend = "downtrend"
        else:
            trend = "neutral"

        result = AnalysisResult(
            short_ma=short_ma,
            long_ma=long_ma,
            prices=prices,
            dates=dates,
            current_short_ma=current_short,
            current_long_ma=current_long,
            prev_short_ma=prev_short,
            prev_long_ma=prev_long,
            current_price=current_price,
            ma_spread=ma_spread,
            price_vs_short=price_vs_short,
            trend=trend,
        )

        logger.info(
            "[%s] 분석 완료: 현재가=%.0f, 단기MA=%.0f, 장기MA=%.0f, "
            "스프레드=%.2f%%, 트렌드=%s",
            stock_code, current_price, current_short, current_long,
            ma_spread, trend,
        )

        return result.to_dict()

    def generate_signal(self, analysis_result: dict[str, Any]) -> dict[str, Any]:
        """
        이동평균 교차 기반 매매 신호 생성

        골든크로스: 이전에 short < long 이었다가 short > long 되면 → BUY
        데드크로스: 이전에 short > long 이었다가 short < long 되면 → SELL
        그 외: HOLD

        Args:
            analysis_result: analyze()의 결과

        Returns:
            {
                "signal": "buy" | "sell" | "hold",
                "strength": float (0.0 ~ 1.0),
                "reason": str,
                "strategy_name": str,
                "timestamp": str,
                "metrics": {...}
            }
        """
        current_short = analysis_result.get("current_short_ma", 0.0)
        current_long = analysis_result.get("current_long_ma", 0.0)
        prev_short = analysis_result.get("prev_short_ma", 0.0)
        prev_long = analysis_result.get("prev_long_ma", 0.0)
        current_price = analysis_result.get("current_price", 0.0)
        ma_spread = analysis_result.get("ma_spread", 0.0)
        trend = analysis_result.get("trend", "neutral")

        # 데이터 부족 시 HOLD
        if current_short == 0 or current_long == 0:
            return self._build_signal(
                SignalType.HOLD, 0.0,
                "데이터 부족으로 신호 생성 불가",
                analysis_result,
            )

        # 교차 판단
        prev_diff = prev_short - prev_long
        curr_diff = current_short - current_long

        # 노이즈 필터: 교차 폭이 threshold 미만이면 무시
        spread_ratio = abs(ma_spread)

        if prev_diff <= 0 < curr_diff:
            # 골든크로스! 🟢
            strength = min(spread_ratio / 3.0, 1.0)  # 스프레드 3% → 강도 1.0
            if self.config.signal_threshold > 0 and spread_ratio < self.config.signal_threshold:
                return self._build_signal(
                    SignalType.HOLD, 0.1,
                    f"골든크로스 감지되었으나 스프레드({spread_ratio:.2f}%)가 "
                    f"임계값({self.config.signal_threshold:.2f}%) 미만",
                    analysis_result,
                )
            return self._build_signal(
                SignalType.BUY, max(strength, 0.3),
                f"골든크로스 발생: 단기MA({current_short:.0f}) > "
                f"장기MA({current_long:.0f}), 스프레드 {ma_spread:.2f}%",
                analysis_result,
            )

        if prev_diff >= 0 > curr_diff:
            # 데드크로스! 🔴
            strength = min(spread_ratio / 3.0, 1.0)
            if self.config.signal_threshold > 0 and spread_ratio < self.config.signal_threshold:
                return self._build_signal(
                    SignalType.HOLD, 0.1,
                    f"데드크로스 감지되었으나 스프레드({spread_ratio:.2f}%)가 "
                    f"임계값({self.config.signal_threshold:.2f}%) 미만",
                    analysis_result,
                )
            return self._build_signal(
                SignalType.SELL, max(strength, 0.3),
                f"데드크로스 발생: 단기MA({current_short:.0f}) < "
                f"장기MA({current_long:.0f}), 스프레드 {ma_spread:.2f}%",
                analysis_result,
            )

        # 교차 없음 → 추세 유지
        reason = f"교차 없음. 현재 추세: {trend}, 스프레드: {ma_spread:.2f}%"
        return self._build_signal(SignalType.HOLD, 0.0, reason, analysis_result)

    def _build_signal(
        self,
        signal_type: SignalType,
        strength: float,
        reason: str,
        analysis_result: dict[str, Any],
    ) -> dict[str, Any]:
        """매매 신호 딕셔너리 구성"""
        signal = {
            "signal": signal_type.value,
            "strength": round(strength, 4),
            "reason": reason,
            "strategy_name": self.name,
            "timestamp": datetime.now(UTC).isoformat(),
            "metrics": {
                "current_short_ma": analysis_result.get("current_short_ma", 0.0),
                "current_long_ma": analysis_result.get("current_long_ma", 0.0),
                "ma_spread": analysis_result.get("ma_spread", 0.0),
                "trend": analysis_result.get("trend", "neutral"),
                "current_price": analysis_result.get("current_price", 0.0),
            },
        }
        logger.info(
            "신호 생성: %s (강도=%.2f) — %s",
            signal_type.value.upper(), strength, reason,
        )
        return signal

    def backtest(
        self,
        historical_data: list[dict[str, Any]],
        initial_capital: float,
    ) -> dict[str, Any]:
        """
        과거 데이터로 이동평균 교차 전략 백테스팅

        Args:
            historical_data: [{"date": str, "close": float, ...}, ...]
                             오래된 순서
            initial_capital: 초기 자본금 (원)

        Returns:
            {
                "strategy_name": str,
                "initial_capital": float,
                "final_capital": float,
                "total_return": float,        # 총 수익률 (%)
                "total_trades": int,
                "winning_trades": int,
                "losing_trades": int,
                "win_rate": float,            # 승률 (%)
                "max_drawdown": float,        # 최대 낙폭 (%)
                "sharpe_ratio": float,        # 샤프 비율 (근사)
                "trades": list,
                "equity_curve": list,
            }
        """
        if len(historical_data) < self.config.long_window + 1:
            logger.warning("백테스팅 데이터 부족: %d개", len(historical_data))
            return {
                "strategy_name": self.name,
                "initial_capital": initial_capital,
                "final_capital": initial_capital,
                "total_return": 0.0,
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": 0.0,
                "max_drawdown": 0.0,
                "sharpe_ratio": 0.0,
                "trades": [],
                "equity_curve": [],
                "error": "데이터 부족",
            }

        # 백테스트 설정에서 수수료/세금 로드 (미설정 시 trading_settings 기본값)
        buy_commission = backtest_settings.get_commission_rate(
            fallback=trading_settings.buy_commission_rate,
        )
        sell_commission = backtest_settings.get_commission_rate(
            fallback=trading_settings.sell_commission_rate,
        )
        sell_tax = backtest_settings.get_sell_tax_rate(
            fallback=trading_settings.total_sell_tax_rate,
        )

        prices = [d["close"] for d in historical_data]
        dates = [d.get("date", str(i)) for i, d in enumerate(historical_data)]

        short_ma = self._calculate_ma(prices, self.config.short_window)
        long_ma = self._calculate_ma(prices, self.config.long_window)

        # 시뮬레이션 상태
        capital = initial_capital
        shares = 0
        position_price = 0.0
        trades: list[dict[str, Any]] = []
        equity_curve: list[dict[str, Any]] = []
        daily_returns: list[float] = []
        peak_equity = initial_capital

        # long_window부터 시뮬레이션 시작 (이전에는 MA 값 없음)
        for i in range(self.config.long_window, len(prices)):
            price = prices[i]
            date = dates[i]

            # 현재 자산 가치
            equity = capital + shares * price
            equity_curve.append({"date": date, "equity": round(equity, 2)})

            # 일간 수익률 (첫 날 제외)
            if len(equity_curve) > 1:
                prev_equity = equity_curve[-2]["equity"]
                daily_ret = (equity - prev_equity) / prev_equity if prev_equity > 0 else 0.0
                daily_returns.append(daily_ret)

            # 교차 감지
            curr_short = short_ma[i]
            curr_long = long_ma[i]
            prev_short_val = short_ma[i - 1]
            prev_long_val = long_ma[i - 1]

            prev_diff = prev_short_val - prev_long_val
            curr_diff = curr_short - curr_long

            # 골든크로스 → 매수 (보유 주식 없을 때만)
            if prev_diff <= 0 < curr_diff and shares == 0:
                available = capital * (1 - buy_commission)
                shares = int(available // price)
                if shares > 0:
                    cost = shares * price
                    commission = cost * buy_commission
                    capital -= cost + commission
                    position_price = price
                    trades.append({
                        "date": date,
                        "type": "buy",
                        "price": price,
                        "shares": shares,
                        "commission": round(commission, 2),
                        "capital_after": round(capital, 2),
                    })
                    logger.debug(
                        "백테스트 매수: %s, 가격=%.0f, 수량=%d",
                        date, price, shares,
                    )

            # 데드크로스 → 매도 (보유 주식 있을 때만)
            elif prev_diff >= 0 > curr_diff and shares > 0:
                revenue = shares * price
                commission = revenue * sell_commission
                tax = revenue * sell_tax
                capital += revenue - commission - tax
                pnl = (price - position_price) / position_price * 100
                trades.append({
                    "date": date,
                    "type": "sell",
                    "price": price,
                    "shares": shares,
                    "commission": round(commission, 2),
                    "tax": round(tax, 2),
                    "pnl_pct": round(pnl, 2),
                    "capital_after": round(capital, 2),
                })
                logger.debug(
                    "백테스트 매도: %s, 가격=%.0f, 수량=%d, 수익률=%.2f%%",
                    date, price, shares, pnl,
                )
                shares = 0
                position_price = 0.0

            # 최대 낙폭 갱신
            if equity > peak_equity:
                peak_equity = equity

        # 최종 정산 (미체결 포지션 있으면 마지막 가격으로 정리)
        final_price = prices[-1]
        if shares > 0:
            revenue = shares * final_price
            commission = revenue * sell_commission
            tax = revenue * sell_tax
            capital += revenue - commission - tax
            pnl = (final_price - position_price) / position_price * 100
            trades.append({
                "date": dates[-1],
                "type": "sell (정산)",
                "price": final_price,
                "shares": shares,
                "commission": round(commission, 2),
                "tax": round(tax, 2),
                "pnl_pct": round(pnl, 2),
                "capital_after": round(capital, 2),
            })
            shares = 0

        final_capital = capital
        total_return = (final_capital - initial_capital) / initial_capital * 100

        # 승률 계산
        sell_trades = [t for t in trades if t["type"].startswith("sell")]
        winning = sum(1 for t in sell_trades if t.get("pnl_pct", 0) > 0)
        losing = sum(1 for t in sell_trades if t.get("pnl_pct", 0) <= 0)
        win_rate = (winning / len(sell_trades) * 100) if sell_trades else 0.0

        # 최대 낙폭(MDD)
        max_dd = 0.0
        running_peak = initial_capital
        for point in equity_curve:
            eq = point["equity"]
            if eq > running_peak:
                running_peak = eq
            dd = (running_peak - eq) / running_peak * 100
            if dd > max_dd:
                max_dd = dd

        # 샤프 비율 근사 (연환산)
        trading_days = backtest_settings.trading_days_per_year
        risk_free = backtest_settings.risk_free_rate
        if daily_returns:
            avg_return = sum(daily_returns) / len(daily_returns)
            variance = sum((r - avg_return) ** 2 for r in daily_returns) / len(daily_returns)
            std_return = variance ** 0.5
            annualized_return = avg_return * trading_days
            annualized_std = std_return * (trading_days ** 0.5)
            sharpe = (
                (annualized_return - risk_free) / annualized_std
                if annualized_std > 0 else 0.0
            )
        else:
            sharpe = 0.0

        result = {
            "strategy_name": self.name,
            "initial_capital": initial_capital,
            "final_capital": round(final_capital, 2),
            "total_return": round(total_return, 2),
            "total_trades": len(trades),
            "winning_trades": winning,
            "losing_trades": losing,
            "win_rate": round(win_rate, 2),
            "max_drawdown": round(max_dd, 2),
            "sharpe_ratio": round(sharpe, 4),
            "trades": trades,
            "equity_curve": equity_curve,
        }

        logger.info(
            "백테스팅 완료: 수익률=%.2f%%, 승률=%.1f%%, MDD=%.2f%%, "
            "샤프=%.2f, 거래=%d건",
            total_return, win_rate, max_dd, sharpe, len(trades),
        )

        return result

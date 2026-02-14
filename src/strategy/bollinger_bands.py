"""
볼린저 밴드 전략 (Bollinger Bands Strategy)

SMA 기반 중심선과 표준편차 기반 상/하단 밴드를 이용해
가격의 이탈 및 복귀를 포착하여 매매 신호를 생성합니다.

- 하단 밴드 이탈 후 복귀 → 매수
- 상단 밴드 돌파 후 복귀 → 매도
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from config.backtest import backtest_settings
from config.trading import trading_settings
from src.strategy.base import BaseStrategy
from src.utils.logger import get_logger

logger = get_logger(__name__)


class SignalType(str, Enum):
    """매매 신호 종류"""

    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class BollingerConfig:
    """볼린저 밴드 전략 설정

    Attributes:
        period: 이동평균 기간 (기본 20)
        num_std: 표준편차 배수 (기본 2.0)
        signal_threshold: 신호 강도 최소 임계값 (기본 0.0)
    """

    period: int = 20
    num_std: float = 2.0
    signal_threshold: float = 0.0

    def __post_init__(self) -> None:
        if self.period < 2:
            msg = "볼린저 밴드 기간은 최소 2 이상이어야 합니다"
            raise ValueError(msg)
        if self.num_std <= 0:
            msg = f"표준편차 배수({self.num_std})는 0보다 커야 합니다"
            raise ValueError(msg)


def calculate_bollinger_bands(
    prices: list[float],
    period: int = 20,
    num_std: float = 2.0,
) -> dict[str, list[float]]:
    """
    볼린저 밴드 계산 — SMA + 표준편차 기반 상/하단 밴드

    Args:
        prices: 종가 리스트 (오래된 순)
        period: 이동평균 기간 (기본 20)
        num_std: 표준편차 배수 (기본 2.0)

    Returns:
        {
            "middle": list[float],   # 중심선 (SMA)
            "upper": list[float],    # 상단 밴드 (SMA + num_std * std)
            "lower": list[float],    # 하단 밴드 (SMA - num_std * std)
        }
        period-1개는 0.0 패딩
    """
    if len(prices) < period:
        return {"middle": [], "upper": [], "lower": []}

    middle: list[float] = [0.0] * (period - 1)
    upper: list[float] = [0.0] * (period - 1)
    lower: list[float] = [0.0] * (period - 1)

    for i in range(period - 1, len(prices)):
        window = prices[i - period + 1 : i + 1]
        sma = sum(window) / period
        variance = sum((p - sma) ** 2 for p in window) / period
        std = variance ** 0.5

        middle.append(sma)
        upper.append(sma + num_std * std)
        lower.append(sma - num_std * std)

    return {"middle": middle, "upper": upper, "lower": lower}


class BollingerBandStrategy(BaseStrategy):
    """
    볼린저 밴드 기반 매매 전략

    하단 밴드 이탈 후 복귀(가격이 하단 밴드 아래였다가 위로 올라옴) → 매수
    상단 밴드 돌파 후 복귀(가격이 상단 밴드 위였다가 아래로 내려옴) → 매도

    Usage::

        config = BollingerConfig(period=20, num_std=2.0)
        strategy = BollingerBandStrategy(config)

        analysis = strategy.analyze({"prices": [...], "dates": [...]})
        signal = strategy.generate_signal(analysis)
        result = strategy.backtest(historical_data, initial_capital=10_000_000)
    """

    def __init__(self, config: BollingerConfig | None = None) -> None:
        self.config = config or BollingerConfig()
        name = f"Bollinger({self.config.period},{self.config.num_std})"
        super().__init__(name=name)
        logger.info(
            "볼린저 밴드 전략 설정: 기간=%d, 표준편차배수=%.1f, 임계값=%.4f",
            self.config.period,
            self.config.num_std,
            self.config.signal_threshold,
        )

    def analyze(self, market_data: dict[str, Any]) -> dict[str, Any]:
        """
        시장 데이터 분석 — 볼린저 밴드 계산 + %B, 밴드폭 계산

        Args:
            market_data: {
                "prices": list[float],     # 종가 리스트 (오래된 순, 필수)
                "dates": list[str],        # 날짜 리스트 (선택)
                "stock_code": str,         # 종목 코드 (선택)
            }

        Returns:
            {
                "middle": list[float],
                "upper": list[float],
                "lower": list[float],
                "prices": list[float],
                "dates": list[str],
                "current_price": float,
                "prev_price": float,
                "current_upper": float,
                "current_lower": float,
                "current_middle": float,
                "prev_upper": float,
                "prev_lower": float,
                "percent_b": float,        # %B = (가격 - 하단) / (상단 - 하단)
                "bandwidth": float,        # 밴드폭 = (상단 - 하단) / 중심 * 100
                "zone": "above_upper" | "below_lower" | "neutral",
            }
        """
        prices: list[float] = market_data.get("prices", [])
        dates: list[str] = market_data.get("dates", [])
        stock_code: str = market_data.get("stock_code", "unknown")

        min_required = self.config.period + 1  # 이전 밴드와 비교 필요
        if len(prices) < min_required:
            logger.warning(
                "[%s] 데이터 부족: %d개 (최소 %d개 필요)",
                stock_code, len(prices), min_required,
            )
            return {
                "middle": [],
                "upper": [],
                "lower": [],
                "prices": prices,
                "dates": dates,
                "current_price": prices[-1] if prices else 0.0,
                "prev_price": prices[-2] if len(prices) >= 2 else 0.0,
                "current_upper": 0.0,
                "current_lower": 0.0,
                "current_middle": 0.0,
                "prev_upper": 0.0,
                "prev_lower": 0.0,
                "percent_b": 0.0,
                "bandwidth": 0.0,
                "zone": "neutral",
            }

        bands = calculate_bollinger_bands(
            prices, self.config.period, self.config.num_std,
        )

        current_price = prices[-1]
        prev_price = prices[-2]
        current_upper = bands["upper"][-1]
        current_lower = bands["lower"][-1]
        current_middle = bands["middle"][-1]
        prev_upper = bands["upper"][-2]
        prev_lower = bands["lower"][-2]

        # %B 계산: (가격 - 하단) / (상단 - 하단)
        band_width_abs = current_upper - current_lower
        if band_width_abs > 0:
            percent_b = (current_price - current_lower) / band_width_abs
        else:
            percent_b = 0.5  # 밴드폭이 0이면 중간

        # 밴드폭: (상단 - 하단) / 중심 * 100
        bandwidth = (
            band_width_abs / current_middle * 100
            if current_middle > 0 else 0.0
        )

        # 구간 판단
        if current_price > current_upper:
            zone = "above_upper"
        elif current_price < current_lower:
            zone = "below_lower"
        else:
            zone = "neutral"

        logger.info(
            "[%s] 볼린저 분석 완료: 현재가=%.0f, 상단=%.0f, 중심=%.0f, "
            "하단=%.0f, %%B=%.2f, 밴드폭=%.2f%%, 구간=%s",
            stock_code, current_price, current_upper, current_middle,
            current_lower, percent_b, bandwidth, zone,
        )

        return {
            "middle": bands["middle"],
            "upper": bands["upper"],
            "lower": bands["lower"],
            "prices": prices,
            "dates": dates,
            "current_price": current_price,
            "prev_price": prev_price,
            "current_upper": current_upper,
            "current_lower": current_lower,
            "current_middle": current_middle,
            "prev_upper": prev_upper,
            "prev_lower": prev_lower,
            "percent_b": round(percent_b, 4),
            "bandwidth": round(bandwidth, 4),
            "zone": zone,
        }

    def generate_signal(self, analysis_result: dict[str, Any]) -> dict[str, Any]:
        """
        볼린저 밴드 기반 매매 신호 생성

        - 하단 이탈 후 복귀: 이전 가격 < 이전 하단 밴드, 현재 가격 ≥ 현재 하단 밴드 → 매수
        - 상단 돌파 후 복귀: 이전 가격 > 이전 상단 밴드, 현재 가격 ≤ 현재 상단 밴드 → 매도
        - 그 외: 관망

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
        current_price = analysis_result.get("current_price", 0.0)
        prev_price = analysis_result.get("prev_price", 0.0)
        current_upper = analysis_result.get("current_upper", 0.0)
        current_lower = analysis_result.get("current_lower", 0.0)
        prev_upper = analysis_result.get("prev_upper", 0.0)
        prev_lower = analysis_result.get("prev_lower", 0.0)
        percent_b = analysis_result.get("percent_b", 0.0)
        bandwidth = analysis_result.get("bandwidth", 0.0)
        zone = analysis_result.get("zone", "neutral")

        # 데이터 부족 시 HOLD
        if not analysis_result.get("middle"):
            return self._build_signal(
                SignalType.HOLD, 0.0,
                "데이터 부족으로 신호 생성 불가",
                analysis_result,
            )

        # 하단 이탈 후 복귀 → 매수
        if prev_price < prev_lower and current_price >= current_lower:
            # 강도: 하단에서 얼마나 복귀했는가
            strength = min(abs(percent_b), 1.0) if percent_b > 0 else 0.3
            if self.config.signal_threshold > 0 and strength < self.config.signal_threshold:
                return self._build_signal(
                    SignalType.HOLD, strength,
                    f"하단 이탈 후 복귀 감지되었으나 강도({strength:.2f})가 "
                    f"임계값({self.config.signal_threshold:.2f}) 미만",
                    analysis_result,
                )
            return self._build_signal(
                SignalType.BUY, max(strength, 0.3),
                f"하단 이탈 후 복귀: 가격 {prev_price:.0f} → {current_price:.0f} "
                f"(하단 {current_lower:.0f}), %B={percent_b:.2f}",
                analysis_result,
            )

        # 상단 돌파 후 복귀 → 매도
        if prev_price > prev_upper and current_price <= current_upper:
            # 강도: 상단에서 얼마나 복귀했는가
            strength = min(abs(1 - percent_b), 1.0) if percent_b < 1 else 0.3
            if self.config.signal_threshold > 0 and strength < self.config.signal_threshold:
                return self._build_signal(
                    SignalType.HOLD, strength,
                    f"상단 돌파 후 복귀 감지되었으나 강도({strength:.2f})가 "
                    f"임계값({self.config.signal_threshold:.2f}) 미만",
                    analysis_result,
                )
            return self._build_signal(
                SignalType.SELL, max(strength, 0.3),
                f"상단 돌파 후 복귀: 가격 {prev_price:.0f} → {current_price:.0f} "
                f"(상단 {current_upper:.0f}), %B={percent_b:.2f}",
                analysis_result,
            )

        # 그 외: 관망
        reason = (
            f"가격 {current_price:.0f} — {zone} 구간, "
            f"%B={percent_b:.2f}, 밴드폭={bandwidth:.2f}%, 신호 없음"
        )
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
                "current_price": analysis_result.get("current_price", 0.0),
                "current_upper": analysis_result.get("current_upper", 0.0),
                "current_lower": analysis_result.get("current_lower", 0.0),
                "current_middle": analysis_result.get("current_middle", 0.0),
                "percent_b": analysis_result.get("percent_b", 0.0),
                "bandwidth": analysis_result.get("bandwidth", 0.0),
                "zone": analysis_result.get("zone", "neutral"),
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
        과거 데이터로 볼린저 밴드 전략 백테스팅

        Args:
            historical_data: [{"date": str, "close": float, ...}, ...]
                             오래된 순서
            initial_capital: 초기 자본금 (원)

        Returns:
            {
                "strategy_name": str,
                "initial_capital": float,
                "final_capital": float,
                "total_return": float,
                "total_trades": int,
                "winning_trades": int,
                "losing_trades": int,
                "win_rate": float,
                "max_drawdown": float,
                "sharpe_ratio": float,
                "trades": list,
                "equity_curve": list,
            }
        """
        min_required = self.config.period + 1
        if len(historical_data) < min_required:
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

        # 백테스트 설정에서 수수료/세금 로드
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

        bands = calculate_bollinger_bands(
            prices, self.config.period, self.config.num_std,
        )

        # 시뮬레이션 상태
        capital = initial_capital
        shares = 0
        position_price = 0.0
        trades: list[dict[str, Any]] = []
        equity_curve: list[dict[str, Any]] = []
        daily_returns: list[float] = []
        peak_equity = initial_capital

        # period부터 시뮬레이션 시작 (이전 가격 vs 이전 밴드 비교 필요)
        start_idx = self.config.period
        for i in range(start_idx, len(prices)):
            price = prices[i]
            prev_price = prices[i - 1]
            date = dates[i]

            current_upper = bands["upper"][i]
            current_lower = bands["lower"][i]
            prev_upper = bands["upper"][i - 1]
            prev_lower = bands["lower"][i - 1]

            # 현재 자산 가치
            equity = capital + shares * price
            equity_curve.append({"date": date, "equity": round(equity, 2)})

            # 일간 수익률
            if len(equity_curve) > 1:
                prev_equity = equity_curve[-2]["equity"]
                daily_ret = (equity - prev_equity) / prev_equity if prev_equity > 0 else 0.0
                daily_returns.append(daily_ret)

            # 하단 이탈 후 복귀 → 매수
            if (prev_price < prev_lower
                    and price >= current_lower
                    and shares == 0):
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

            # 상단 돌파 후 복귀 → 매도
            elif (prev_price > prev_upper
                    and price <= current_upper
                    and shares > 0):
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

        # 최종 정산
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
            "볼린저 백테스팅 완료: 수익률=%.2f%%, 승률=%.1f%%, MDD=%.2f%%, "
            "샤프=%.2f, 거래=%d건",
            total_return, win_rate, max_dd, sharpe, len(trades),
        )

        return result

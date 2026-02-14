"""
RSI (Relative Strength Index) 전략

RSI 값이 과매도 구간(기본 30 이하)에서 탈출하면 매수,
과매수 구간(기본 70 이상)에 진입하면 매도 신호를 생성합니다.

RSI = 100 - 100 / (1 + RS)
RS  = 평균 상승폭 / 평균 하락폭  (Wilder 방식, 지수 이동평균)
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
class RSIConfig:
    """RSI 전략 설정

    Attributes:
        period: RSI 계산 기간 (기본 14)
        overbought: 과매수 기준선 (기본 70)
        oversold: 과매도 기준선 (기본 30)
        signal_threshold: 신호 강도 최소 임계값 (기본 0.0)
    """

    period: int = 14
    overbought: float = 70.0
    oversold: float = 30.0
    signal_threshold: float = 0.0

    def __post_init__(self) -> None:
        if self.period < 2:
            msg = "RSI 기간은 최소 2 이상이어야 합니다"
            raise ValueError(msg)
        if not (0 < self.oversold < self.overbought < 100):
            msg = (
                f"과매도({self.oversold})와 과매수({self.overbought}) 기준이 "
                f"올바르지 않습니다 (0 < oversold < overbought < 100)"
            )
            raise ValueError(msg)


def calculate_rsi(prices: list[float], period: int = 14) -> list[float]:
    """
    RSI (Relative Strength Index) 계산 — Wilder 방식

    첫 period개의 평균 상승/하락폭은 단순 평균으로 계산하고,
    이후는 지수 이동평균(Wilder smoothing)으로 갱신합니다.

    Args:
        prices: 종가 리스트 (오래된 순)
        period: RSI 계산 기간 (기본 14)

    Returns:
        RSI 값 리스트 (period개는 0.0 패딩)
    """
    if len(prices) < period + 1:
        return []

    result: list[float] = [0.0] * period

    # 첫 period 구간의 상승/하락 변동 계산
    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, period + 1):
        change = prices[i] - prices[i - 1]
        if change > 0:
            gains.append(change)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(change))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    # 첫 RSI 값
    if avg_loss == 0:
        result.append(100.0)
    else:
        rs = avg_gain / avg_loss
        result.append(100.0 - 100.0 / (1.0 + rs))

    # Wilder smoothing으로 이후 RSI 계산
    for i in range(period + 1, len(prices)):
        change = prices[i] - prices[i - 1]
        gain = change if change > 0 else 0.0
        loss = abs(change) if change < 0 else 0.0

        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

        if avg_loss == 0:
            result.append(100.0)
        else:
            rs = avg_gain / avg_loss
            result.append(100.0 - 100.0 / (1.0 + rs))

    return result


class RSIStrategy(BaseStrategy):
    """
    RSI 기반 매매 전략

    과매도(RSI ≤ oversold) 구간에서 탈출(RSI > oversold)하면 매수,
    과매수(RSI ≥ overbought) 구간에 진입(RSI ≥ overbought)하면 매도.

    Usage::

        config = RSIConfig(period=14, overbought=70, oversold=30)
        strategy = RSIStrategy(config)

        analysis = strategy.analyze({"prices": [...], "dates": [...]})
        signal = strategy.generate_signal(analysis)
        result = strategy.backtest(historical_data, initial_capital=10_000_000)
    """

    def __init__(self, config: RSIConfig | None = None) -> None:
        self.config = config or RSIConfig()
        name = f"RSI({self.config.period})"
        super().__init__(name=name)
        logger.info(
            "RSI 전략 설정: 기간=%d, 과매수=%.1f, 과매도=%.1f, 임계값=%.4f",
            self.config.period,
            self.config.overbought,
            self.config.oversold,
            self.config.signal_threshold,
        )

    def analyze(self, market_data: dict[str, Any]) -> dict[str, Any]:
        """
        시장 데이터 분석 — RSI 계산 + 과매수/과매도 판단

        Args:
            market_data: {
                "prices": list[float],     # 종가 리스트 (오래된 순, 필수)
                "dates": list[str],        # 날짜 리스트 (선택)
                "stock_code": str,         # 종목 코드 (선택)
            }

        Returns:
            {
                "rsi_values": list[float],
                "prices": list[float],
                "dates": list[str],
                "current_rsi": float,
                "prev_rsi": float,
                "current_price": float,
                "zone": "overbought" | "oversold" | "neutral",
            }
        """
        prices: list[float] = market_data.get("prices", [])
        dates: list[str] = market_data.get("dates", [])
        stock_code: str = market_data.get("stock_code", "unknown")

        min_required = self.config.period + 2  # 교차 판단에 최소 +2 필요
        if len(prices) < min_required:
            logger.warning(
                "[%s] 데이터 부족: %d개 (최소 %d개 필요)",
                stock_code, len(prices), min_required,
            )
            return {
                "rsi_values": [],
                "prices": prices,
                "dates": dates,
                "current_rsi": 0.0,
                "prev_rsi": 0.0,
                "current_price": prices[-1] if prices else 0.0,
                "zone": "neutral",
            }

        rsi_values = calculate_rsi(prices, self.config.period)

        current_rsi = rsi_values[-1]
        prev_rsi = rsi_values[-2]
        current_price = prices[-1]

        # 구간 판단
        if current_rsi >= self.config.overbought:
            zone = "overbought"
        elif current_rsi <= self.config.oversold:
            zone = "oversold"
        else:
            zone = "neutral"

        logger.info(
            "[%s] RSI 분석 완료: 현재가=%.0f, RSI=%.2f, 이전RSI=%.2f, 구간=%s",
            stock_code, current_price, current_rsi, prev_rsi, zone,
        )

        return {
            "rsi_values": rsi_values,
            "prices": prices,
            "dates": dates,
            "current_rsi": current_rsi,
            "prev_rsi": prev_rsi,
            "current_price": current_price,
            "zone": zone,
        }

    def generate_signal(self, analysis_result: dict[str, Any]) -> dict[str, Any]:
        """
        RSI 기반 매매 신호 생성

        - 과매도 탈출: 이전 RSI ≤ oversold, 현재 RSI > oversold → 매수
        - 과매수 진입: 현재 RSI ≥ overbought → 매도
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
        current_rsi = analysis_result.get("current_rsi", 0.0)
        prev_rsi = analysis_result.get("prev_rsi", 0.0)
        zone = analysis_result.get("zone", "neutral")

        # 데이터 부족 시 HOLD
        if not analysis_result.get("rsi_values"):
            return self._build_signal(
                SignalType.HOLD, 0.0,
                "데이터 부족으로 신호 생성 불가",
                analysis_result,
            )

        # 과매도 탈출 → 매수
        if prev_rsi <= self.config.oversold < current_rsi:
            # 강도: oversold에서 얼마나 올라왔는가 (0~1 스케일)
            strength = min(
                (current_rsi - self.config.oversold) / (50 - self.config.oversold),
                1.0,
            )
            if self.config.signal_threshold > 0 and strength < self.config.signal_threshold:
                return self._build_signal(
                    SignalType.HOLD, strength,
                    f"과매도 탈출 감지되었으나 강도({strength:.2f})가 "
                    f"임계값({self.config.signal_threshold:.2f}) 미만",
                    analysis_result,
                )
            return self._build_signal(
                SignalType.BUY, max(strength, 0.3),
                f"과매도 탈출: RSI {prev_rsi:.1f} → {current_rsi:.1f} "
                f"(기준선 {self.config.oversold})",
                analysis_result,
            )

        # 과매수 진입 → 매도
        if current_rsi >= self.config.overbought:
            # 강도: overbought를 얼마나 초과했는가
            strength = min(
                (current_rsi - self.config.overbought) / (100 - self.config.overbought),
                1.0,
            )
            if self.config.signal_threshold > 0 and strength < self.config.signal_threshold:
                return self._build_signal(
                    SignalType.HOLD, strength,
                    f"과매수 감지되었으나 강도({strength:.2f})가 "
                    f"임계값({self.config.signal_threshold:.2f}) 미만",
                    analysis_result,
                )
            return self._build_signal(
                SignalType.SELL, max(strength, 0.3),
                f"과매수 진입: RSI {current_rsi:.1f} "
                f"(기준선 {self.config.overbought})",
                analysis_result,
            )

        # 그 외: 관망
        reason = f"RSI {current_rsi:.1f} — {zone} 구간, 신호 없음"
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
                "current_rsi": analysis_result.get("current_rsi", 0.0),
                "prev_rsi": analysis_result.get("prev_rsi", 0.0),
                "zone": analysis_result.get("zone", "neutral"),
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
        과거 데이터로 RSI 전략 백테스팅

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
        min_required = self.config.period + 2
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

        rsi_values = calculate_rsi(prices, self.config.period)

        # 시뮬레이션 상태
        capital = initial_capital
        shares = 0
        position_price = 0.0
        trades: list[dict[str, Any]] = []
        equity_curve: list[dict[str, Any]] = []
        daily_returns: list[float] = []
        peak_equity = initial_capital

        # period+1 부터 시뮬레이션 시작 (이전 RSI와 현재 RSI 비교 필요)
        start_idx = self.config.period + 1
        for i in range(start_idx, len(prices)):
            price = prices[i]
            date = dates[i]

            # 현재 자산 가치
            equity = capital + shares * price
            equity_curve.append({"date": date, "equity": round(equity, 2)})

            # 일간 수익률
            if len(equity_curve) > 1:
                prev_equity = equity_curve[-2]["equity"]
                daily_ret = (equity - prev_equity) / prev_equity if prev_equity > 0 else 0.0
                daily_returns.append(daily_ret)

            current_rsi = rsi_values[i]
            prev_rsi = rsi_values[i - 1]

            # 과매도 탈출 → 매수 (보유 주식 없을 때만)
            if prev_rsi <= self.config.oversold < current_rsi and shares == 0:
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
                        "백테스트 매수: %s, 가격=%.0f, 수량=%d, RSI=%.1f",
                        date, price, shares, current_rsi,
                    )

            # 과매수 진입 → 매도 (보유 주식 있을 때만)
            elif current_rsi >= self.config.overbought and shares > 0:
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
                    "백테스트 매도: %s, 가격=%.0f, 수량=%d, RSI=%.1f, 수익률=%.2f%%",
                    date, price, shares, current_rsi, pnl,
                )
                shares = 0
                position_price = 0.0

            # 최대 낙폭 갱신
            if equity > peak_equity:
                peak_equity = equity

        # 최종 정산 (미체결 포지션)
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
            "RSI 백테스팅 완료: 수익률=%.2f%%, 승률=%.1f%%, MDD=%.2f%%, "
            "샤프=%.2f, 거래=%d건",
            total_return, win_rate, max_dd, sharpe, len(trades),
        )

        return result

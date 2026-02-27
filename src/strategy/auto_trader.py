"""
자동매매 엔진 — 레짐 기반 게이트 방식 시그널 생성 + 주문 실행

게이트 방식:
1. PER/PEG → 유니버스 필터 (eligible 아니면 HOLD)
2. Fear&Greed → 레짐 결정 (RegimeEngine)
3. 레짐별 허용 전략만 실행 (평균회귀 / 추세추종)
4. 뉴스 센티멘트 → 포지션 사이즈 배수
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from src.analysis.market_profile import (
    SectorType,
    StockProfile,
    classify_by_profile,
    get_stock_profile,
)
from src.analysis.screener import StockScreener
from src.analysis.sentiment import (
    HybridSentimentAnalyzer,
    HybridSentimentResult,
    MarketSentiment,
    MarketSentimentResult,
)
from src.analysis.universe import UniverseManager
from src.broker.kis_client import KISClient
from src.strategy.oneshot import OneShotOrderConfig, OneShotOrderService
from src.strategy.oneshot import OneShotSellConfig, OneShotSellService
from src.strategy.regime import MarketRegime, RegimeEngine
from src.strategy.safety import SafetyCheck
from src.utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------


class SignalType(Enum):
    """매매 시그널 유형"""

    STRONG_BUY = "strong_buy"
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"
    STRONG_SELL = "strong_sell"


@dataclass
class TechnicalSignals:
    """기술적 분석 신호 (RSI + 볼린저 분리)"""

    rsi_value: float  # RSI 근사값 (0~100)
    rsi_signal: str  # "oversold", "neutral", "overbought"
    bollinger_position: float  # %B 값 (0~1)
    bollinger_signal: str  # "lower_band", "middle", "upper_band", "breakout"
    band_width_expanding: bool  # 밴드폭 확장 여부


@dataclass
class TradeSignal:
    """매매 시그널"""

    stock_code: str
    stock_name: str
    signal_type: SignalType
    regime: MarketRegime = MarketRegime.NEUTRAL  # 적용된 레짐
    strategy_used: str = "none"  # "mean_reversion", "trend_following", "none"
    size_multiplier: float = 1.0  # 뉴스 기반 포지션 배수
    score: float = 0.0  # 후순위 정렬용
    sentiment_score: float = 0.0  # 하위호환용 (뉴스 기반 배수로 대체)
    quality_score: float = 0.0  # PER 품질 기여분
    technical_score: float = 0.0  # 기술적 분석 기여분
    reason: str = ""
    recommended_action: str = "hold"
    warnings: list[str] = field(default_factory=list)


@dataclass
class RiskLimits:
    """리스크 한도 설정"""

    max_daily_trades: int = 10
    max_position_pct: float = 0.2
    max_total_position_pct: float = 0.8
    max_daily_loss_pct: float = 0.03
    min_signal_score_buy: float = 35.0
    max_signal_score_sell: float = -20.0


@dataclass
class AutoTraderConfig:
    """자동매매 설정"""

    universe_name: str = "kospi_top30"
    risk_limits: RiskLimits = field(default_factory=RiskLimits)
    dry_run: bool = True
    max_notional_krw: int = 5_000_000
    min_trade_interval_days: int = 5


# ---------------------------------------------------------------------------
# AutoTrader
# ---------------------------------------------------------------------------


class AutoTrader:
    """자동매매 엔진 — 레짐 기반 게이트 방식"""

    def __init__(
        self,
        kis_client: KISClient,
        config: AutoTraderConfig | None = None,
        safety_check: SafetyCheck | None = None,
    ) -> None:
        self._client = kis_client
        self._config = config or AutoTraderConfig()
        self._sentiment = MarketSentiment()
        self._hybrid_sentiment = HybridSentimentAnalyzer()
        self._screener = StockScreener(kis_client)
        self._universe = UniverseManager()
        self._regime_engine = RegimeEngine()
        self._daily_trade_count = 0
        self._safety_check = safety_check

    @property
    def config(self) -> AutoTraderConfig:
        return self._config

    # ───────────────── 유니버스 스캔 ─────────────────

    def scan_universe(self) -> list[TradeSignal]:
        """유니버스 전체 스캔 → 시그널 생성"""
        hybrid_result = self._hybrid_sentiment.analyze()
        sentiment_result = self._sentiment.analyze()
        universe = self._universe.get_universe(self._config.universe_name)
        if universe is None:
            logger.warning("유니버스 '%s' 없음", self._config.universe_name)
            return []

        # critical urgency → 거래 스킵
        if hybrid_result.news_urgency == "critical":
            logger.warning("뉴스 urgency=critical, 거래 스킵 (리스크 관리)")
            return []

        signals: list[TradeSignal] = []
        for stock_code in universe.stock_codes:
            try:
                profile = get_stock_profile(stock_code)
                signal = self.calculate_signal(
                    stock_code, sentiment_result, hybrid_result, profile
                )
                signals.append(signal)
            except Exception:
                logger.exception("시그널 계산 실패: %s", stock_code)

        # 점수 내림차순 정렬
        signals.sort(key=lambda s: s.score, reverse=True)
        logger.info(
            "유니버스 스캔 완료: %d종목 중 %d개 시그널",
            len(universe.stock_codes),
            len(signals),
        )
        return signals

    # ───────────────── 기술적 분석 ─────────────────

    def classify_technical(self, stock_code: str) -> TechnicalSignals:
        """현재가 기반 기술적 신호 분류 (RSI + 볼린저 분리)"""
        try:
            price_data = self._client.get_price(stock_code)
            prdy_ctrt = float(price_data.get("prdy_ctrt", 0) or 0)

            # RSI 근사: 전일 대비율 기반
            # -5% 이하 → RSI ~20 (과매도), +5% 이상 → RSI ~80 (과매수)
            # 하락(음수)일수록 RSI가 낮아지도록 설정
            rsi_value = 50.0 + prdy_ctrt * 6.0
            rsi_value = max(0.0, min(100.0, rsi_value))

            if rsi_value < 30:
                rsi_signal = "oversold"
            elif rsi_value > 70:
                rsi_signal = "overbought"
            else:
                rsi_signal = "neutral"

            # 볼린저 근사: 일중 고/저 대비 현재가 위치
            high = float(price_data.get("stck_hgpr", 0) or 0)
            low = float(price_data.get("stck_lwpr", 0) or 0)
            current = float(price_data.get("stck_prpr", 0) or 0)

            if high > low > 0:
                pct_b = (current - low) / (high - low)
                band_range = (high - low) / low * 100  # 밴드폭 %

                if pct_b <= 0.1:
                    bollinger_signal = "lower_band"
                elif pct_b >= 0.95:
                    bollinger_signal = "breakout"
                elif pct_b >= 0.8:
                    bollinger_signal = "upper_band"
                else:
                    bollinger_signal = "middle"

                # 밴드폭 2% 이상이면 확장 중으로 판단
                band_width_expanding = band_range >= 2.0
            else:
                pct_b = 0.5
                bollinger_signal = "middle"
                band_width_expanding = False

            return TechnicalSignals(
                rsi_value=rsi_value,
                rsi_signal=rsi_signal,
                bollinger_position=pct_b,
                bollinger_signal=bollinger_signal,
                band_width_expanding=band_width_expanding,
            )
        except Exception:
            logger.exception("기술적 분석 실패: %s", stock_code)
            return TechnicalSignals(
                rsi_value=50.0,
                rsi_signal="neutral",
                bollinger_position=0.5,
                bollinger_signal="middle",
                band_width_expanding=False,
            )

    def _calculate_technical_score(self, stock_code: str) -> float:
        """기술적 점수 계산 (하위호환용, 정렬 점수에 사용)"""
        tech = self.classify_technical(stock_code)
        # RSI 점수: oversold→+20, overbought→-20
        rsi_score = (50.0 - tech.rsi_value) * 0.4
        rsi_score = max(-20.0, min(20.0, rsi_score))
        # 볼린저 점수: lower_band→+15, upper_band→-15
        bollinger_score = (0.5 - tech.bollinger_position) * 30.0
        bollinger_score = max(-15.0, min(15.0, bollinger_score))
        return rsi_score + bollinger_score

    # ───────────────── 뉴스 → 사이즈 배수 ─────────────────

    @staticmethod
    def _news_to_size_multiplier(
        hybrid_result: HybridSentimentResult | None,
    ) -> float:
        """뉴스 센티멘트 → 포지션 사이즈 배수 (0 ~ 1.5x)

        - 극단적 부정 (news_score <= -80): 0 (진입 차단)
        - 부정 (-80 < score <= -50): 0.5 ~ 0.8x
        - 약한 부정 (-50 < score < 0): 0.8 ~ 1.0x
        - 중립 (0): 1.0x
        - 약한 긍정 (0 < score < 50): 1.0 ~ 1.2x
        - 긍정 (score >= 50): 1.2 ~ 1.5x
        """
        if hybrid_result is None or not hybrid_result.news_available:
            return 1.0

        news_score = hybrid_result.news_score
        if news_score is None:
            return 1.0

        # 극단적 부정 → 진입 차단
        if news_score <= -80:
            return 0.0

        # news_score: -100 ~ +100
        if news_score >= 50:
            return 1.2 + (news_score - 50) / 100.0 * 0.6  # 1.2 ~ 1.5
        elif news_score <= -50:
            # -80 ~ -50 → 0.5 ~ 0.8
            return 0.5 + (news_score + 80) / 30.0 * 0.3
        elif news_score < 0:
            # -50 ~ 0 → 0.8 ~ 1.0
            return 0.8 + (news_score + 50) / 50.0 * 0.2
        elif news_score > 0:
            # 0 ~ 50 → 1.0 ~ 1.2
            return 1.0 + news_score / 50.0 * 0.2
        else:
            return 1.0

    # ───────────────── 시그널 계산 (게이트 방식) ─────────────────

    def calculate_signal(
        self,
        stock_code: str,
        sentiment_result: MarketSentimentResult,
        hybrid_result: HybridSentimentResult | None = None,
        profile: StockProfile | None = None,
    ) -> TradeSignal:
        """단일 종목 시그널 계산 — 게이트 방식

        1. PER/PEG → 유니버스 필터
        2. Fear&Greed → 레짐 결정
        3. 레짐별 게이트 → 시그널 타입 결정
        4. 뉴스 → 포지션 사이즈 배수
        """
        if profile is None:
            profile = get_stock_profile(stock_code)

        # Gate 1: PER/PEG 유니버스 필터
        fundamentals = self._screener.get_fundamentals(stock_code)

        earnings_growth = None
        revenue_growth = None
        if profile.use_peg_ratio:
            try:
                import yfinance as yf

                ticker = yf.Ticker(stock_code)
                info = ticker.info or {}
                earnings_growth = info.get("earningsGrowth")
                revenue_growth = info.get("revenueGrowth")
            except Exception:
                logger.debug("yfinance 성장률 조회 실패: %s", stock_code)

        screening = self._screener.evaluate_quality_with_profile(
            fundamentals,
            profile=profile,
            earnings_growth=earnings_growth,
            revenue_growth=revenue_growth,
        )

        if not screening.eligible:
            return TradeSignal(
                stock_code=stock_code,
                stock_name=fundamentals.stock_name,
                signal_type=SignalType.HOLD,
                reason=f"제외: {screening.reason}",
            )

        # Gate 2: 레짐 결정
        fg_score = sentiment_result.fear_greed.score
        regime = self._regime_engine.classify(fg_score)

        # Gate 3: 기술적 분석
        tech = self.classify_technical(stock_code)

        # Gate 4: 레짐별 시그널 결정
        signal_type = SignalType.HOLD
        strategy_used = "none"

        if regime == MarketRegime.RISK_OFF:
            # 평균회귀만 허용
            if tech.rsi_signal == "oversold" and tech.bollinger_signal == "lower_band":
                signal_type = SignalType.BUY
                strategy_used = "mean_reversion"
            elif tech.rsi_signal == "overbought":
                signal_type = SignalType.SELL
                strategy_used = "mean_reversion"
        elif regime == MarketRegime.RISK_ON:
            # 추세추종만 허용
            if (
                tech.bollinger_signal == "breakout"
                and tech.band_width_expanding
            ):
                signal_type = SignalType.BUY
                strategy_used = "trend_following"
            elif tech.bollinger_signal == "lower_band":
                signal_type = SignalType.SELL
                strategy_used = "trend_following"
        else:
            # NEUTRAL: 양쪽 허용, 보수적
            if tech.rsi_signal == "oversold":
                signal_type = SignalType.BUY
                strategy_used = "mean_reversion"
            elif tech.bollinger_signal == "breakout":
                # Neutral에서는 band_expanding 없이도 돌파 시 약한 추세추종 허용
                signal_type = SignalType.BUY
                strategy_used = "trend_following"
            elif tech.rsi_signal == "overbought":
                signal_type = SignalType.SELL
                strategy_used = "mean_reversion"

        # 뉴스 센티멘트 → 사이즈 배수 (점수에는 기여하지 않음)
        size_multiplier = self._news_to_size_multiplier(hybrid_result)

        # 품질 점수 (정렬용)
        if profile.skip_per_filter:
            quality_score = 0.0
        elif profile.use_peg_ratio:
            _quality, score_adj, _reason = classify_by_profile(
                profile=profile,
                per=fundamentals.per,
                sector_avg_per=fundamentals.sector_avg_per,
                earnings_growth=earnings_growth,
                revenue_growth=revenue_growth,
            )
            quality_score = score_adj
        else:
            quality_score = 25.0

        # 기술적 점수 (정렬용)
        technical_score = self._calculate_technical_score(stock_code)
        if profile.sector == SectorType.GROWTH:
            technical_score *= 1.3
            technical_score = max(-35.0, min(35.0, technical_score))

        # 센티멘트 점수 (하위호환용 기록만, 총점에는 합산하지 않음)
        if hybrid_result is not None:
            sentiment_score = -hybrid_result.hybrid_score / 100.0 * 30.0
        else:
            sentiment_score = (50 - fg_score) * 0.6

        # 총점: 품질 + 기술적 점수만 (센티멘트는 size_multiplier로 분리)
        total_score = quality_score + technical_score
        total_score = max(-100.0, min(100.0, total_score))

        # STRONG 변환: 점수 기반으로 강도 조절
        if signal_type == SignalType.BUY and total_score > 70:
            signal_type = SignalType.STRONG_BUY
        elif signal_type == SignalType.SELL and total_score < -60:
            signal_type = SignalType.STRONG_SELL

        # 현재가 조회
        price_data = self._client.get_price(stock_code)
        current_price = int(price_data.get("stck_prpr", 0) or 0)

        # 추천 액션
        if signal_type in (SignalType.STRONG_BUY, SignalType.BUY):
            qty = (
                max(1, self._config.max_notional_krw // current_price)
                if current_price > 0
                else 1
            )
            action = f"buy {qty}주 @ {current_price:,}원"
        elif signal_type in (SignalType.SELL, SignalType.STRONG_SELL):
            action = f"sell @ {current_price:,}원"
        else:
            action = "hold"

        reasons = []
        reasons.append(f"레짐={regime.value}")
        reasons.append(f"전략={strategy_used}")
        reasons.append(f"RSI={tech.rsi_signal}")
        reasons.append(f"BB={tech.bollinger_signal}")
        reasons.append(f"사이즈배수={size_multiplier:.2f}")
        reason = f"{signal_type.value} ({', '.join(reasons)})"

        return TradeSignal(
            stock_code=stock_code,
            stock_name=fundamentals.stock_name,
            signal_type=signal_type,
            regime=regime,
            strategy_used=strategy_used,
            size_multiplier=size_multiplier,
            score=total_score,
            sentiment_score=sentiment_score,
            quality_score=quality_score,
            technical_score=technical_score,
            reason=reason,
            recommended_action=action,
        )

    @staticmethod
    def _score_to_signal_type(score: float) -> SignalType:
        """점수 → 시그널 타입 (하위호환용)"""
        if score > 70:
            return SignalType.STRONG_BUY
        if score > 35:
            return SignalType.BUY
        if score < -60:
            return SignalType.STRONG_SELL
        if score < -20:
            return SignalType.SELL
        return SignalType.HOLD

    # ───────────────── 주문 실행 ─────────────────

    def execute_signals(self, signals: list[TradeSignal]) -> list[dict[str, Any]]:
        """시그널 기반 주문 실행"""
        buy_signals = [
            s
            for s in signals
            if s.signal_type in (SignalType.STRONG_BUY, SignalType.BUY)
            and s.score >= self._config.risk_limits.min_signal_score_buy
        ]

        results: list[dict[str, Any]] = []
        balance = self._client.get_balance()
        total_asset = float(
            balance.get("summary", [{}])[0].get("tot_evlu_amt", 0)
            if isinstance(balance.get("summary"), list) and balance.get("summary")
            else 0
        )

        holdings = balance.get("holdings", [])
        current_position_value = sum(
            float(h.get("evlu_amt", 0) or 0) for h in holdings
        )
        current_position_pct = (
            current_position_value / total_asset if total_asset > 0 else 0.0
        )

        for signal in buy_signals:
            if self._daily_trade_count >= self._config.risk_limits.max_daily_trades:
                logger.warning("일일 거래 한도 도달: %d", self._daily_trade_count)
                break

            if current_position_pct >= self._config.risk_limits.max_total_position_pct:
                logger.warning(
                    "총 포지션 한도 도달: %.1f%%",
                    current_position_pct * 100,
                )
                break

            result = self._execute_buy(signal, total_asset)
            if result:
                results.append(result)
                self._daily_trade_count += 1

        return results

    def _execute_buy(
        self, signal: TradeSignal, total_asset: float
    ) -> dict[str, Any] | None:
        """단일 매수 주문 실행"""
        try:
            price_data = self._client.get_price(signal.stock_code)
            current_price = int(price_data.get("stck_prpr", 0) or 0)
            if current_price <= 0:
                return None

            if self._safety_check is not None:
                check_result = self._safety_check.check(
                    order_amount=current_price,
                    available_cash=total_asset,
                )
                if not check_result.safe:
                    logger.warning(
                        "안전장치 차단: %s — %s",
                        signal.stock_code,
                        ", ".join(check_result.reasons),
                    )
                    return None

            # 사이즈 배수 적용 (뉴스 기반)
            base_qty = max(1, self._config.max_notional_krw // current_price)
            qty = max(1, int(base_qty * signal.size_multiplier))

            notional = current_price * qty
            if total_asset > 0:
                position_pct = notional / total_asset
                if position_pct > self._config.risk_limits.max_position_pct:
                    qty = max(
                        1,
                        int(
                            total_asset
                            * self._config.risk_limits.max_position_pct
                            / current_price
                        ),
                    )
                    notional = current_price * qty

            if self._config.dry_run:
                logger.info(
                    "[DRY RUN] 매수: %s %s %d주 @ %d원 (총 %d원, 배수 %.2f)",
                    signal.stock_code,
                    signal.stock_name,
                    qty,
                    current_price,
                    notional,
                    signal.size_multiplier,
                )
                return {
                    "stock_code": signal.stock_code,
                    "stock_name": signal.stock_name,
                    "action": "buy",
                    "quantity": qty,
                    "price": current_price,
                    "notional": notional,
                    "dry_run": True,
                    "signal_score": signal.score,
                    "regime": signal.regime.value,
                    "strategy": signal.strategy_used,
                    "size_multiplier": signal.size_multiplier,
                }

            order_svc = OneShotOrderService(self._client)
            config = OneShotOrderConfig(
                stock_code=signal.stock_code,
                quantity=qty,
                max_notional_krw=self._config.max_notional_krw,
                explicit_price=current_price,
            )
            result = order_svc.execute_order(config)
            return {
                "stock_code": signal.stock_code,
                "stock_name": signal.stock_name,
                "action": "buy",
                "quantity": qty,
                "price": current_price,
                "notional": notional,
                "dry_run": False,
                "signal_score": signal.score,
                "regime": signal.regime.value,
                "strategy": signal.strategy_used,
                "size_multiplier": signal.size_multiplier,
                "order_result": result,
            }
        except Exception:
            logger.exception("매수 실행 실패: %s", signal.stock_code)
            return None

    # ───────────────── 매도 체크 ─────────────────

    def check_holdings_for_sell(self) -> list[TradeSignal]:
        """보유 종목 매도 시그널 체크 (강한 부정 뉴스 → 청산 가속)"""
        balance = self._client.get_balance()
        holdings = balance.get("holdings", [])
        sentiment_result = self._sentiment.analyze()

        # 뉴스 센티멘트 기반 청산 가속 판단
        try:
            hybrid_result = self._hybrid_sentiment.analyze()
        except Exception:
            hybrid_result = None

        sell_signals: list[TradeSignal] = []

        for holding in holdings:
            stock_code = holding.get("pdno", "")
            stock_name = holding.get("prdt_name", stock_code)
            qty = int(holding.get("hldg_qty", 0) or 0)
            if qty <= 0 or not stock_code:
                continue

            pnl_rate = float(holding.get("evlu_pfls_rt", 0) or 0)
            current_price = int(holding.get("prpr", 0) or 0)

            # 익절: +10% 이상
            if pnl_rate >= 10.0:
                sell_signals.append(
                    TradeSignal(
                        stock_code=stock_code,
                        stock_name=stock_name,
                        signal_type=SignalType.SELL,
                        score=-40.0,
                        reason=f"익절: 수익률 {pnl_rate:+.1f}% ≥ 10%",
                        recommended_action=f"sell {qty}주 @ {current_price:,}원",
                    )
                )
                continue

            # 손절: -5% 이하
            if pnl_rate <= -5.0:
                sell_signals.append(
                    TradeSignal(
                        stock_code=stock_code,
                        stock_name=stock_name,
                        signal_type=SignalType.STRONG_SELL,
                        score=-80.0,
                        reason=f"손절: 수익률 {pnl_rate:+.1f}% ≤ -5%",
                        recommended_action=f"sell {qty}주 @ {current_price:,}원",
                    )
                )
                continue

            # 청산 가속: 강한 부정 뉴스 (news_score <= -60) → 청산 우선순위 상향
            if (
                hybrid_result is not None
                and hybrid_result.news_available
                and hybrid_result.news_score is not None
                and hybrid_result.news_score <= -60
            ):
                sell_signals.append(
                    TradeSignal(
                        stock_code=stock_code,
                        stock_name=stock_name,
                        signal_type=SignalType.SELL,
                        score=-60.0,
                        reason=f"청산가속: 강한 부정 뉴스 (news={hybrid_result.news_score:.0f}), 수익률 {pnl_rate:+.1f}%",
                        recommended_action=f"sell {qty}주 @ {current_price:,}원",
                    )
                )
                continue

            # 일반 시그널 재계산
            try:
                signal = self.calculate_signal(stock_code, sentiment_result)
                if signal.signal_type in (SignalType.SELL, SignalType.STRONG_SELL):
                    signal = TradeSignal(
                        stock_code=stock_code,
                        stock_name=stock_name,
                        signal_type=signal.signal_type,
                        regime=signal.regime,
                        strategy_used=signal.strategy_used,
                        size_multiplier=signal.size_multiplier,
                        score=signal.score,
                        sentiment_score=signal.sentiment_score,
                        quality_score=signal.quality_score,
                        technical_score=signal.technical_score,
                        reason=signal.reason,
                        recommended_action=f"sell {qty}주 @ {current_price:,}원",
                    )
                    sell_signals.append(signal)
            except Exception:
                logger.exception("매도 시그널 계산 실패: %s", stock_code)

        return sell_signals

    # ───────────────── 사이클 실행 ─────────────────

    def run_cycle(self) -> dict[str, Any]:
        """한 사이클 실행"""
        timestamp = datetime.now(tz=timezone.utc).isoformat()
        sentiment_result = self._sentiment.analyze()

        buy_signals = self.scan_universe()
        executed_buys = self.execute_signals(buy_signals)

        sell_signals = self.check_holdings_for_sell()
        executed_sells: list[dict[str, Any]] = []
        for signal in sell_signals:
            if self._config.dry_run:
                executed_sells.append(
                    {
                        "stock_code": signal.stock_code,
                        "stock_name": signal.stock_name,
                        "action": "sell",
                        "signal_type": signal.signal_type.value,
                        "score": signal.score,
                        "reason": signal.reason,
                        "regime": signal.regime.value,
                        "dry_run": True,
                    }
                )
            else:
                try:
                    balance = self._client.get_balance()
                    holdings = balance.get("holdings", [])
                    qty = 0
                    for h in holdings:
                        if h.get("pdno") == signal.stock_code:
                            qty = int(h.get("hldg_qty", 0) or 0)
                            break

                    if qty > 0:
                        sell_svc = OneShotSellService(self._client)
                        price_data = self._client.get_price(signal.stock_code)
                        current_price = int(
                            price_data.get("stck_prpr", 0) or 0
                        )
                        sell_config = OneShotSellConfig(
                            stock_code=signal.stock_code,
                            quantity=qty,
                            max_notional_krw=self._config.max_notional_krw,
                            explicit_price=current_price,
                        )
                        result = sell_svc.execute_sell(sell_config)
                        executed_sells.append(
                            {
                                "stock_code": signal.stock_code,
                                "stock_name": signal.stock_name,
                                "action": "sell",
                                "quantity": qty,
                                "price": current_price,
                                "dry_run": False,
                                "order_result": result,
                            }
                        )
                except Exception:
                    logger.exception("매도 실행 실패: %s", signal.stock_code)

        # 레짐 정보 추가
        fg_score = sentiment_result.fear_greed.score
        regime = self._regime_engine.classify(fg_score)

        return {
            "timestamp": timestamp,
            "sentiment": {
                "score": fg_score,
                "classification": sentiment_result.fear_greed.classification,
                "buy_multiplier": sentiment_result.buy_multiplier,
                "recommendation": sentiment_result.recommendation,
            },
            "regime": regime.value,
            "allowed_strategies": self._regime_engine.get_allowed_strategies(regime),
            "scanned": len(buy_signals),
            "buy_signals": [
                {
                    "stock_code": s.stock_code,
                    "stock_name": s.stock_name,
                    "signal_type": s.signal_type.value,
                    "score": s.score,
                    "reason": s.reason,
                    "regime": s.regime.value,
                    "strategy": s.strategy_used,
                }
                for s in buy_signals
                if s.signal_type in (SignalType.BUY, SignalType.STRONG_BUY)
            ],
            "sell_signals": [
                {
                    "stock_code": s.stock_code,
                    "stock_name": s.stock_name,
                    "signal_type": s.signal_type.value,
                    "score": s.score,
                    "reason": s.reason,
                }
                for s in sell_signals
            ],
            "executed_buys": executed_buys,
            "executed_sells": executed_sells,
            "dry_run": self._config.dry_run,
        }

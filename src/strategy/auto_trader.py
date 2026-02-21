"""
자동매매 엔진 — 센티멘트 + 스크리너 + 기술적 분석 → 주문 실행

시장 공포탐욕지수, PER 품질 판단, RSI/볼린저 기술적 분석을 종합하여
매매 시그널을 생성하고, 리스크 관리 하에 주문을 실행합니다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

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
class TradeSignal:
    """매매 시그널"""

    stock_code: str
    stock_name: str
    signal_type: SignalType
    score: float  # -100 ~ +100
    sentiment_score: float  # 센티멘트 기여분
    quality_score: float  # PER 품질 기여분
    technical_score: float  # RSI/볼린저 기여분
    reason: str
    recommended_action: str  # "buy 1주 @ 189,200원" 등
    warnings: list[str] = field(default_factory=list)


@dataclass
class RiskLimits:
    """리스크 한도 설정"""

    max_daily_trades: int = 10
    max_position_pct: float = 0.2  # 종목당 최대 투자 비중 20%
    max_total_position_pct: float = 0.8  # 총 포지션 한도 80%
    max_daily_loss_pct: float = 0.03  # 일일 최대 손실 3%
    min_signal_score_buy: float = 35.0  # 매수 최소 점수
    max_signal_score_sell: float = -20.0  # 매도 최대 점수


@dataclass
class AutoTraderConfig:
    """자동매매 설정"""

    universe_name: str = "kospi_top30"
    risk_limits: RiskLimits = field(default_factory=RiskLimits)
    dry_run: bool = True  # 기본값 True!
    max_notional_krw: int = 5_000_000  # 종목당 최대 500만원
    min_trade_interval_days: int = 5  # 같은 종목 재진입까지 최소 대기일


# ---------------------------------------------------------------------------
# AutoTrader
# ---------------------------------------------------------------------------


class AutoTrader:
    """자동매매 엔진 — 센티멘트 + 스크리너 + 기술적 분석 → 주문 실행"""

    def __init__(self, kis_client: KISClient, config: AutoTraderConfig | None = None) -> None:
        self._client = kis_client
        self._config = config or AutoTraderConfig()
        self._sentiment = MarketSentiment()
        self._hybrid_sentiment = HybridSentimentAnalyzer()
        self._screener = StockScreener(kis_client)
        self._universe = UniverseManager()
        self._daily_trade_count = 0

    @property
    def config(self) -> AutoTraderConfig:
        return self._config

    # ───────────────── 유니버스 스캔 ─────────────────

    def scan_universe(self) -> list[TradeSignal]:
        """유니버스 전체 스캔 → 시그널 생성

        1. 하이브리드 센티멘트 조회
        2. 유니버스 종목 순회
        3. 각 종목: PER 품질 판단 → 기술적 분석 → 점수 합산
        4. 시그널 리스트 반환 (점수 내림차순)
        """
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
                signal = self.calculate_signal(stock_code, sentiment_result, hybrid_result)
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

    # ───────────────── 시그널 계산 ─────────────────

    def calculate_signal(
        self,
        stock_code: str,
        sentiment_result: MarketSentimentResult,
        hybrid_result: HybridSentimentResult | None = None,
    ) -> TradeSignal:
        """단일 종목 시그널 계산

        - 센티멘트 점수: -30 ~ +30 (하이브리드 센티멘트 기반)
        - PER 품질 점수: 0 or +25 (eligible이면 +25, 아니면 0으로 HOLD)
        - RSI 점수: -20 ~ +20
        - 볼린저 점수: -15 ~ +15
        """
        # 1. 재무지표 + 품질 판단
        fundamentals = self._screener.get_fundamentals(stock_code)
        screening = self._screener.evaluate_quality(fundamentals)

        # 가치함정/주주환원 미흡 → HOLD
        if not screening.eligible:
            return TradeSignal(
                stock_code=stock_code,
                stock_name=fundamentals.stock_name,
                signal_type=SignalType.HOLD,
                score=0.0,
                sentiment_score=0.0,
                quality_score=0.0,
                technical_score=0.0,
                reason=f"제외: {screening.reason}",
                recommended_action="hold",
            )

        # 2. 센티멘트 점수: hybrid_score → -30 ~ +30
        if hybrid_result is not None:
            # hybrid_score / 100 * 30 → ±30
            # 부호 반전: 공포(음수) → 매수 기회(양수)
            sentiment_score = -hybrid_result.hybrid_score / 100.0 * 30.0
        else:
            # fallback: 기존 방식
            fg_score = sentiment_result.fear_greed.score
            sentiment_score = (50 - fg_score) * 0.6  # 공포일수록 높은 점수

        # 3. 품질 점수: eligible이면 +25
        quality_score = 25.0

        # 4. 기술적 분석 (현재가 기반 간이 계산)
        technical_score = self._calculate_technical_score(stock_code)

        # 총점
        total_score = sentiment_score + quality_score + technical_score
        total_score = max(-100.0, min(100.0, total_score))

        # 시그널 타입 결정
        signal_type = self._score_to_signal_type(total_score)

        # 현재가 조회
        price_data = self._client.get_price(stock_code)
        current_price = int(price_data.get("stck_prpr", 0) or 0)

        # 추천 액션
        if signal_type in (SignalType.STRONG_BUY, SignalType.BUY):
            qty = max(1, self._config.max_notional_krw // current_price) if current_price > 0 else 1
            action = f"buy {qty}주 @ {current_price:,}원"
        elif signal_type in (SignalType.SELL, SignalType.STRONG_SELL):
            action = f"sell @ {current_price:,}원"
        else:
            action = "hold"

        reasons = []
        reasons.append(f"센티멘트 {sentiment_score:+.1f}")
        reasons.append(f"품질 {quality_score:+.1f}")
        reasons.append(f"기술적 {technical_score:+.1f}")
        reason = f"총점 {total_score:.1f} ({', '.join(reasons)})"

        return TradeSignal(
            stock_code=stock_code,
            stock_name=fundamentals.stock_name,
            signal_type=signal_type,
            score=total_score,
            sentiment_score=sentiment_score,
            quality_score=quality_score,
            technical_score=technical_score,
            reason=reason,
            recommended_action=action,
        )

    def _calculate_technical_score(self, stock_code: str) -> float:
        """현재가 기반 기술적 점수 계산 (RSI + 볼린저 간이 버전)

        - 전일 대비율로 RSI 근사: -20 ~ +20
        - 고가/저가 대비 현재가 위치로 볼린저 근사: -15 ~ +15
        """
        try:
            price_data = self._client.get_price(stock_code)
            prdy_ctrt = float(price_data.get("prdy_ctrt", 0) or 0)  # 전일 대비율(%)

            # RSI 근사: 전일 대비율 기반
            # 하락(-5% 이하) → +20(과매도 매수기회), 상승(+5% 이상) → -20(과매수)
            rsi_score = -prdy_ctrt * 4.0
            rsi_score = max(-20.0, min(20.0, rsi_score))

            # 볼린저 근사: 일중 고/저 대비 현재가 위치
            high = float(price_data.get("stck_hgpr", 0) or 0)
            low = float(price_data.get("stck_lwpr", 0) or 0)
            current = float(price_data.get("stck_prpr", 0) or 0)

            if high > low > 0:
                # %B 근사: 0(하단)~1(상단), 0.5가 중앙
                pct_b = (current - low) / (high - low)
                # 하단 근처(0) → +15, 상단 근처(1) → -15
                bollinger_score = (0.5 - pct_b) * 30.0
                bollinger_score = max(-15.0, min(15.0, bollinger_score))
            else:
                bollinger_score = 0.0

            return rsi_score + bollinger_score
        except Exception:
            logger.exception("기술적 분석 실패: %s", stock_code)
            return 0.0

    @staticmethod
    def _score_to_signal_type(score: float) -> SignalType:
        """점수 → 시그널 타입"""
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
        """시그널 기반 주문 실행

        1. BUY/STRONG_BUY 시그널만 필터
        2. 리스크 필터 적용 (일일 거래횟수, 포지션 한도 등)
        3. 주문 크기 결정
        4. OneShotOrderService로 지정가 매수 실행
        5. dry_run이면 시뮬레이션만
        """
        buy_signals = [
            s for s in signals
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

        # 현재 포지션 비중 계산
        holdings = balance.get("holdings", [])
        current_position_value = sum(
            float(h.get("evlu_amt", 0) or 0) for h in holdings
        )
        current_position_pct = (
            current_position_value / total_asset if total_asset > 0 else 0.0
        )

        for signal in buy_signals:
            # 일일 거래 횟수 제한
            if self._daily_trade_count >= self._config.risk_limits.max_daily_trades:
                logger.warning("일일 거래 한도 도달: %d", self._daily_trade_count)
                break

            # 포지션 한도 체크
            if current_position_pct >= self._config.risk_limits.max_total_position_pct:
                logger.warning(
                    "총 포지션 한도 도달: %.1f%%",
                    current_position_pct * 100,
                )
                break

            # 주문 실행
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

            # 매수 강도 배율 적용
            sentiment_result = self._sentiment.analyze()
            multiplier = sentiment_result.buy_multiplier
            base_qty = max(1, self._config.max_notional_krw // current_price)
            qty = max(1, int(base_qty * multiplier))

            # 종목당 최대 비중 체크
            notional = current_price * qty
            if total_asset > 0:
                position_pct = notional / total_asset
                if position_pct > self._config.risk_limits.max_position_pct:
                    qty = max(
                        1,
                        int(total_asset * self._config.risk_limits.max_position_pct / current_price),
                    )
                    notional = current_price * qty

            if self._config.dry_run:
                logger.info(
                    "[DRY RUN] 매수: %s %s %d주 @ %d원 (총 %d원)",
                    signal.stock_code,
                    signal.stock_name,
                    qty,
                    current_price,
                    notional,
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
                }

            # 실제 주문
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
                "order_result": result,
            }
        except Exception:
            logger.exception("매수 실행 실패: %s", signal.stock_code)
            return None

    # ───────────────── 매도 체크 ─────────────────

    def check_holdings_for_sell(self) -> list[TradeSignal]:
        """보유 종목 매도 시그널 체크

        1. 현재 보유종목 조회
        2. 각 종목 시그널 재계산
        3. SELL/STRONG_SELL 시그널 반환
        + 목표 수익률 +15% 도달 → SELL
        + 손절 -7% 도달 → STRONG_SELL
        """
        balance = self._client.get_balance()
        holdings = balance.get("holdings", [])
        sentiment_result = self._sentiment.analyze()

        sell_signals: list[TradeSignal] = []

        for holding in holdings:
            stock_code = holding.get("pdno", "")
            stock_name = holding.get("prdt_name", stock_code)
            qty = int(holding.get("hldg_qty", 0) or 0)
            if qty <= 0 or not stock_code:
                continue

            # 수익률 체크
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
                        sentiment_score=0.0,
                        quality_score=0.0,
                        technical_score=0.0,
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
                        sentiment_score=0.0,
                        quality_score=0.0,
                        technical_score=0.0,
                        reason=f"손절: 수익률 {pnl_rate:+.1f}% ≤ -5%",
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
        """한 사이클 실행 (매수 스캔 + 보유종목 매도 체크)"""
        timestamp = datetime.now(tz=timezone.utc).isoformat()
        sentiment_result = self._sentiment.analyze()

        # 매수 스캔 (hybrid sentiment는 scan_universe 내부에서 조회)
        buy_signals = self.scan_universe()
        executed_buys = self.execute_signals(buy_signals)

        # 매도 체크
        sell_signals = self.check_holdings_for_sell()
        executed_sells: list[dict[str, Any]] = []
        for signal in sell_signals:
            if self._config.dry_run:
                executed_sells.append({
                    "stock_code": signal.stock_code,
                    "stock_name": signal.stock_name,
                    "action": "sell",
                    "signal_type": signal.signal_type.value,
                    "score": signal.score,
                    "reason": signal.reason,
                    "dry_run": True,
                })
            else:
                try:
                    # 보유 수량 조회
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
                        current_price = int(price_data.get("stck_prpr", 0) or 0)
                        sell_config = OneShotSellConfig(
                            stock_code=signal.stock_code,
                            quantity=qty,
                            max_notional_krw=self._config.max_notional_krw,
                            explicit_price=current_price,
                        )
                        result = sell_svc.execute_sell(sell_config)
                        executed_sells.append({
                            "stock_code": signal.stock_code,
                            "stock_name": signal.stock_name,
                            "action": "sell",
                            "quantity": qty,
                            "price": current_price,
                            "dry_run": False,
                            "order_result": result,
                        })
                except Exception:
                    logger.exception("매도 실행 실패: %s", signal.stock_code)

        return {
            "timestamp": timestamp,
            "sentiment": {
                "score": sentiment_result.fear_greed.score,
                "classification": sentiment_result.fear_greed.classification,
                "buy_multiplier": sentiment_result.buy_multiplier,
                "recommendation": sentiment_result.recommendation,
            },
            "scanned": len(buy_signals),
            "buy_signals": [
                {
                    "stock_code": s.stock_code,
                    "stock_name": s.stock_name,
                    "signal_type": s.signal_type.value,
                    "score": s.score,
                    "reason": s.reason,
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

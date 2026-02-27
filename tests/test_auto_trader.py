"""
AutoTrader 자동매매 엔진 테스트 — 레짐 기반 게이트 방식
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.analysis.screener import ScreeningResult, StockFundamentals
from src.analysis.sentiment import (
    FearGreedIndex,
    HybridSentimentResult,
    MarketSentimentResult,
    SentimentResult,
)
from src.broker.kis_client import KISClient
from src.strategy.auto_trader import (
    AutoTrader,
    AutoTraderConfig,
    SignalType,
    TechnicalSignals,
    TradeSignal,
)
from src.strategy.regime import MarketRegime


# ───────────────── Fixtures ─────────────────


def _make_sentiment(score: int = 30) -> MarketSentimentResult:
    return MarketSentimentResult(
        fear_greed=SentimentResult(
            score=score,
            classification="Fear",
            timestamp=datetime.now(tz=timezone.utc),
            source="test",
        ),
        buy_multiplier=FearGreedIndex.get_buy_multiplier(score),
        market_condition="neutral",
        recommendation="buy",
    )


def _make_hybrid(
    news_score: float | None = None,
    news_urgency: str | None = None,
    fg_score: int = 30,
) -> HybridSentimentResult:
    fg = SentimentResult(
        score=fg_score,
        classification="Fear",
        timestamp=datetime.now(tz=timezone.utc),
        source="test",
    )
    return HybridSentimentResult(
        hybrid_score=(fg_score - 50) * 2.0,
        numeric_score=(fg_score - 50) * 2.0,
        news_score=news_score,
        weights={"numeric": 1.0, "news": 0.0} if news_score is None else {"numeric": 0.5, "news": 0.5},
        news_available=news_score is not None,
        news_urgency=news_urgency,
        fear_greed_raw=fg,
    )


def _make_fundamentals(
    stock_code: str = "005930",
    stock_name: str = "삼성전자",
    per: float = 8.0,
    roe: float = 15.0,
    operating_margin: float = 15.0,
    revenue_growth_yoy: float = 10.0,
    dividend_yield: float = 2.0,
) -> StockFundamentals:
    return StockFundamentals(
        stock_code=stock_code,
        stock_name=stock_name,
        per=per,
        pbr=1.5,
        roe=roe,
        dividend_yield=dividend_yield,
        operating_margin=operating_margin,
        revenue_growth_yoy=revenue_growth_yoy,
        sector="기타",
        sector_avg_per=12.0,
        sector_avg_operating_margin=10.0,
        has_buyback=False,
    )


def _make_screening(
    fundamentals: StockFundamentals,
    quality: str = "undervalued",
    eligible: bool = True,
) -> ScreeningResult:
    return ScreeningResult(
        stock_code=fundamentals.stock_code,
        stock_name=fundamentals.stock_name,
        fundamentals=fundamentals,
        quality=quality,
        quality_score=70.0,
        reason=f"테스트: {quality}",
        eligible=eligible,
    )


@pytest.fixture
def mock_kis() -> MagicMock:
    client = MagicMock(spec=KISClient)
    client.get_price.return_value = {
        "stck_prpr": "70000",
        "prdy_ctrt": "-2.0",
        "stck_hgpr": "72000",
        "stck_lwpr": "68000",
        "per": "10.0",
        "pbr": "1.5",
        "hts_kor_isnm": "삼성전자",
    }
    client.get_balance.return_value = {
        "holdings": [],
        "summary": [{"tot_evlu_amt": "100000000", "dnca_tot_amt": "50000000"}],
    }
    return client


@pytest.fixture
def trader(mock_kis: MagicMock) -> AutoTrader:
    config = AutoTraderConfig(dry_run=True)
    return AutoTrader(mock_kis, config)


# ───────────────── 레짐 게이트 시그널 테스트 ─────────────────


class TestGateBasedSignal:
    """게이트 방식 시그널 생성 테스트"""

    def test_risk_off_mean_reversion_buy(self, trader: AutoTrader, mock_kis: MagicMock) -> None:
        """Risk-Off + 과매도 + 볼밴 하단 → 평균회귀 BUY"""
        sentiment = _make_sentiment(score=10)  # F&G=10 → RISK_OFF
        fundamentals = _make_fundamentals()
        screening = _make_screening(fundamentals, eligible=True)

        with (
            patch.object(trader._screener, "get_fundamentals", return_value=fundamentals),
            patch.object(trader._screener, "evaluate_quality_with_profile", return_value=screening),
            patch.object(
                trader,
                "classify_technical",
                return_value=TechnicalSignals(
                    rsi_value=20.0,
                    rsi_signal="oversold",
                    bollinger_position=0.05,
                    bollinger_signal="lower_band",
                    band_width_expanding=False,
                ),
            ),
        ):
            signal = trader.calculate_signal("005930", sentiment)

        assert signal.signal_type in (SignalType.BUY, SignalType.STRONG_BUY)
        assert signal.regime == MarketRegime.RISK_OFF
        assert signal.strategy_used == "mean_reversion"

    def test_risk_off_blocks_trend_following(self, trader: AutoTrader, mock_kis: MagicMock) -> None:
        """Risk-Off에서 추세추종 시그널 차단 (breakout이어도 HOLD)"""
        sentiment = _make_sentiment(score=10)
        fundamentals = _make_fundamentals()
        screening = _make_screening(fundamentals, eligible=True)

        with (
            patch.object(trader._screener, "get_fundamentals", return_value=fundamentals),
            patch.object(trader._screener, "evaluate_quality_with_profile", return_value=screening),
            patch.object(
                trader,
                "classify_technical",
                return_value=TechnicalSignals(
                    rsi_value=60.0,
                    rsi_signal="neutral",
                    bollinger_position=0.98,
                    bollinger_signal="breakout",
                    band_width_expanding=True,
                ),
            ),
        ):
            signal = trader.calculate_signal("005930", sentiment)

        assert signal.signal_type == SignalType.HOLD
        assert signal.regime == MarketRegime.RISK_OFF

    def test_risk_on_trend_following_buy(self, trader: AutoTrader, mock_kis: MagicMock) -> None:
        """Risk-On + breakout + 밴드 확장 → 추세추종 BUY"""
        sentiment = _make_sentiment(score=80)
        fundamentals = _make_fundamentals()
        screening = _make_screening(fundamentals, eligible=True)

        with (
            patch.object(trader._screener, "get_fundamentals", return_value=fundamentals),
            patch.object(trader._screener, "evaluate_quality_with_profile", return_value=screening),
            patch.object(
                trader,
                "classify_technical",
                return_value=TechnicalSignals(
                    rsi_value=60.0,
                    rsi_signal="neutral",
                    bollinger_position=0.98,
                    bollinger_signal="breakout",
                    band_width_expanding=True,
                ),
            ),
        ):
            signal = trader.calculate_signal("005930", sentiment)

        assert signal.signal_type in (SignalType.BUY, SignalType.STRONG_BUY)
        assert signal.regime == MarketRegime.RISK_ON
        assert signal.strategy_used == "trend_following"

    def test_risk_on_blocks_mean_reversion(self, trader: AutoTrader, mock_kis: MagicMock) -> None:
        """Risk-On에서 평균회귀 시그널 차단 (과매도여도 HOLD)"""
        sentiment = _make_sentiment(score=80)
        fundamentals = _make_fundamentals()
        screening = _make_screening(fundamentals, eligible=True)

        with (
            patch.object(trader._screener, "get_fundamentals", return_value=fundamentals),
            patch.object(trader._screener, "evaluate_quality_with_profile", return_value=screening),
            patch.object(
                trader,
                "classify_technical",
                return_value=TechnicalSignals(
                    rsi_value=20.0,
                    rsi_signal="oversold",
                    bollinger_position=0.05,
                    bollinger_signal="lower_band",
                    band_width_expanding=False,
                ),
            ),
        ):
            signal = trader.calculate_signal("005930", sentiment)

        # Risk-On에서 lower_band → SELL (추세 이탈)
        assert signal.signal_type == SignalType.SELL
        assert signal.regime == MarketRegime.RISK_ON

    def test_neutral_allows_mean_reversion(self, trader: AutoTrader, mock_kis: MagicMock) -> None:
        """Neutral에서 과매도 → 평균회귀 BUY 허용"""
        sentiment = _make_sentiment(score=50)
        fundamentals = _make_fundamentals()
        screening = _make_screening(fundamentals, eligible=True)

        with (
            patch.object(trader._screener, "get_fundamentals", return_value=fundamentals),
            patch.object(trader._screener, "evaluate_quality_with_profile", return_value=screening),
            patch.object(
                trader,
                "classify_technical",
                return_value=TechnicalSignals(
                    rsi_value=20.0,
                    rsi_signal="oversold",
                    bollinger_position=0.1,
                    bollinger_signal="lower_band",
                    band_width_expanding=False,
                ),
            ),
        ):
            signal = trader.calculate_signal("005930", sentiment)

        assert signal.signal_type in (SignalType.BUY, SignalType.STRONG_BUY)
        assert signal.strategy_used == "mean_reversion"

    def test_neutral_allows_trend_following(self, trader: AutoTrader, mock_kis: MagicMock) -> None:
        """Neutral에서 breakout → 추세추종 BUY 허용"""
        sentiment = _make_sentiment(score=50)
        fundamentals = _make_fundamentals()
        screening = _make_screening(fundamentals, eligible=True)

        with (
            patch.object(trader._screener, "get_fundamentals", return_value=fundamentals),
            patch.object(trader._screener, "evaluate_quality_with_profile", return_value=screening),
            patch.object(
                trader,
                "classify_technical",
                return_value=TechnicalSignals(
                    rsi_value=55.0,
                    rsi_signal="neutral",
                    bollinger_position=0.98,
                    bollinger_signal="breakout",
                    band_width_expanding=True,
                ),
            ),
        ):
            signal = trader.calculate_signal("005930", sentiment)

        assert signal.signal_type in (SignalType.BUY, SignalType.STRONG_BUY)
        assert signal.strategy_used == "trend_following"

    def test_neutral_hold_when_no_signal(self, trader: AutoTrader, mock_kis: MagicMock) -> None:
        """Neutral + 중립 기술 → HOLD"""
        sentiment = _make_sentiment(score=50)
        fundamentals = _make_fundamentals()
        screening = _make_screening(fundamentals, eligible=True)

        with (
            patch.object(trader._screener, "get_fundamentals", return_value=fundamentals),
            patch.object(trader._screener, "evaluate_quality_with_profile", return_value=screening),
            patch.object(
                trader,
                "classify_technical",
                return_value=TechnicalSignals(
                    rsi_value=50.0,
                    rsi_signal="neutral",
                    bollinger_position=0.5,
                    bollinger_signal="middle",
                    band_width_expanding=False,
                ),
            ),
        ):
            signal = trader.calculate_signal("005930", sentiment)

        assert signal.signal_type == SignalType.HOLD

    def test_value_trap_excluded(self, trader: AutoTrader, mock_kis: MagicMock) -> None:
        """가치함정 종목 → HOLD (제외)"""
        sentiment = _make_sentiment(score=10)
        fundamentals = _make_fundamentals(roe=3.0, revenue_growth_yoy=-5.0)
        screening = _make_screening(fundamentals, quality="value_trap", eligible=False)

        with (
            patch.object(trader._screener, "get_fundamentals", return_value=fundamentals),
            patch.object(trader._screener, "evaluate_quality_with_profile", return_value=screening),
        ):
            signal = trader.calculate_signal("005930", sentiment)

        assert signal.signal_type == SignalType.HOLD
        assert "제외" in signal.reason


# ───────────────── 뉴스 사이즈 배수 테스트 ─────────────────


class TestNewsSizeMultiplier:
    def test_positive_news_increases_size(self) -> None:
        hybrid = _make_hybrid(news_score=70.0)
        m = AutoTrader._news_to_size_multiplier(hybrid)
        assert 1.2 <= m <= 1.5

    def test_negative_news_decreases_size(self) -> None:
        hybrid = _make_hybrid(news_score=-70.0)
        m = AutoTrader._news_to_size_multiplier(hybrid)
        assert 0.5 <= m <= 0.8

    def test_neutral_news_near_one(self) -> None:
        hybrid = _make_hybrid(news_score=0.0)
        m = AutoTrader._news_to_size_multiplier(hybrid)
        assert 0.9 <= m <= 1.1

    def test_no_news_returns_one(self) -> None:
        assert AutoTrader._news_to_size_multiplier(None) == 1.0

    def test_news_unavailable_returns_one(self) -> None:
        hybrid = _make_hybrid(news_score=None)
        assert AutoTrader._news_to_size_multiplier(hybrid) == 1.0


# ───────────────── 기술적 분석 테스트 ─────────────────


class TestClassifyTechnical:
    def test_oversold(self, trader: AutoTrader, mock_kis: MagicMock) -> None:
        mock_kis.get_price.return_value = {
            "stck_prpr": "68000",
            "prdy_ctrt": "-5.0",
            "stck_hgpr": "72000",
            "stck_lwpr": "68000",
        }
        tech = trader.classify_technical("005930")
        assert tech.rsi_signal == "oversold"
        assert tech.bollinger_signal == "lower_band"

    def test_overbought(self, trader: AutoTrader, mock_kis: MagicMock) -> None:
        mock_kis.get_price.return_value = {
            "stck_prpr": "75000",
            "prdy_ctrt": "5.0",
            "stck_hgpr": "75000",
            "stck_lwpr": "70000",
        }
        tech = trader.classify_technical("005930")
        assert tech.rsi_signal == "overbought"

    def test_neutral(self, trader: AutoTrader, mock_kis: MagicMock) -> None:
        mock_kis.get_price.return_value = {
            "stck_prpr": "71000",
            "prdy_ctrt": "0.5",
            "stck_hgpr": "72000",
            "stck_lwpr": "70000",
        }
        tech = trader.classify_technical("005930")
        assert tech.rsi_signal == "neutral"
        assert tech.bollinger_signal == "middle"


# ───────────────── scan_universe 테스트 ─────────────────


class TestScanUniverse:
    def test_scan_universe(self, trader: AutoTrader, mock_kis: MagicMock) -> None:
        sentiment = _make_sentiment(score=30)

        with (
            patch.object(trader._sentiment, "analyze", return_value=sentiment),
            patch.object(
                trader._universe,
                "get_universe",
                return_value=MagicMock(stock_codes=["005930", "000660"]),
            ),
            patch.object(
                trader,
                "calculate_signal",
                side_effect=[
                    TradeSignal(
                        stock_code="005930",
                        stock_name="삼성전자",
                        signal_type=SignalType.BUY,
                        score=50.0,
                        reason="test",
                        recommended_action="buy",
                    ),
                    TradeSignal(
                        stock_code="000660",
                        stock_name="SK하이닉스",
                        signal_type=SignalType.STRONG_BUY,
                        score=80.0,
                        reason="test",
                        recommended_action="buy",
                    ),
                ],
            ),
        ):
            signals = trader.scan_universe()

        assert len(signals) == 2
        assert signals[0].score > signals[1].score
        assert signals[0].stock_code == "000660"


# ───────────────── execute_signals 테스트 ─────────────────


class TestExecuteSignals:
    def test_daily_trade_limit(self, trader: AutoTrader, mock_kis: MagicMock) -> None:
        trader._daily_trade_count = 10

        signals = [
            TradeSignal(
                stock_code="005930",
                stock_name="삼성전자",
                signal_type=SignalType.BUY,
                score=50.0,
                reason="test",
                recommended_action="buy",
            )
        ]

        results = trader.execute_signals(signals)
        assert len(results) == 0

    def test_position_limit(self, trader: AutoTrader, mock_kis: MagicMock) -> None:
        mock_kis.get_balance.return_value = {
            "holdings": [{"evlu_amt": "90000000"}],
            "summary": [{"tot_evlu_amt": "100000000"}],
        }

        signals = [
            TradeSignal(
                stock_code="005930",
                stock_name="삼성전자",
                signal_type=SignalType.BUY,
                score=50.0,
                reason="test",
                recommended_action="buy",
            )
        ]

        results = trader.execute_signals(signals)
        assert len(results) == 0

    def test_dry_run_mode(self, trader: AutoTrader, mock_kis: MagicMock) -> None:
        assert trader.config.dry_run is True

        signals = [
            TradeSignal(
                stock_code="005930",
                stock_name="삼성전자",
                signal_type=SignalType.BUY,
                score=50.0,
                reason="test",
                recommended_action="buy 1주 @ 70,000원",
            )
        ]

        results = trader.execute_signals(signals)
        assert len(results) == 1
        assert results[0]["dry_run"] is True
        assert results[0]["action"] == "buy"
        assert "regime" in results[0]
        mock_kis.place_order.assert_not_called()


# ───────────────── check_holdings_for_sell 테스트 ─────────────────


class TestCheckHoldingsForSell:
    def test_take_profit(self, trader: AutoTrader, mock_kis: MagicMock) -> None:
        mock_kis.get_balance.return_value = {
            "holdings": [
                {
                    "pdno": "005930",
                    "prdt_name": "삼성전자",
                    "hldg_qty": "10",
                    "prpr": "80000",
                    "evlu_pfls_rt": "16.0",
                }
            ],
            "summary": [{"tot_evlu_amt": "100000000"}],
        }

        with patch.object(trader._sentiment, "analyze", return_value=_make_sentiment()):
            signals = trader.check_holdings_for_sell()

        assert len(signals) == 1
        assert signals[0].signal_type == SignalType.SELL
        assert "익절" in signals[0].reason

    def test_stop_loss(self, trader: AutoTrader, mock_kis: MagicMock) -> None:
        mock_kis.get_balance.return_value = {
            "holdings": [
                {
                    "pdno": "005930",
                    "prdt_name": "삼성전자",
                    "hldg_qty": "10",
                    "prpr": "65000",
                    "evlu_pfls_rt": "-8.0",
                }
            ],
            "summary": [{"tot_evlu_amt": "100000000"}],
        }

        with patch.object(trader._sentiment, "analyze", return_value=_make_sentiment()):
            signals = trader.check_holdings_for_sell()

        assert len(signals) == 1
        assert signals[0].signal_type == SignalType.STRONG_SELL
        assert "손절" in signals[0].reason


# ───────────────── run_cycle 테스트 ─────────────────


class TestRunCycle:
    def test_full_cycle(self, trader: AutoTrader, mock_kis: MagicMock) -> None:
        sentiment = _make_sentiment(score=30)

        mock_kis.get_balance.return_value = {
            "holdings": [],
            "summary": [{"tot_evlu_amt": "100000000"}],
        }

        with (
            patch.object(trader._sentiment, "analyze", return_value=sentiment),
            patch.object(
                trader,
                "scan_universe",
                return_value=[
                    TradeSignal(
                        stock_code="005930",
                        stock_name="삼성전자",
                        signal_type=SignalType.BUY,
                        score=50.0,
                        reason="test",
                        recommended_action="buy",
                    ),
                ],
            ),
            patch.object(trader, "check_holdings_for_sell", return_value=[]),
        ):
            result = trader.run_cycle()

        assert "timestamp" in result
        assert result["dry_run"] is True
        assert result["scanned"] == 1
        assert "regime" in result
        assert "allowed_strategies" in result
        assert isinstance(result["buy_signals"], list)
        assert isinstance(result["sell_signals"], list)


# ───────────────── API 엔드포인트 테스트 ─────────────────


class TestAutoTraderAPI:
    @pytest.fixture
    def client(self) -> TestClient:
        from src.main import app

        return TestClient(app)

    def test_get_config(self, client: TestClient) -> None:
        resp = client.get("/api/v1/auto-trader/config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["dry_run"] is True
        assert "risk_limits" in data

    def test_put_config(self, client: TestClient) -> None:
        new_config = {
            "universe_name": "kospi_top30",
            "risk_limits": {
                "max_daily_trades": 5,
                "max_position_pct": 0.1,
                "max_total_position_pct": 0.5,
                "max_daily_loss_pct": 0.02,
                "min_signal_score_buy": 50.0,
                "max_signal_score_sell": -40.0,
            },
            "dry_run": True,
            "max_notional_krw": 3_000_000,
        }
        resp = client.put("/api/v1/auto-trader/config", json=new_config)
        assert resp.status_code == 200
        data = resp.json()
        assert data["max_notional_krw"] == 3_000_000

        # Reset
        default_config = {
            "universe_name": "kospi_top30",
            "risk_limits": {
                "max_daily_trades": 10,
                "max_position_pct": 0.2,
                "max_total_position_pct": 0.8,
                "max_daily_loss_pct": 0.03,
                "min_signal_score_buy": 35.0,
                "max_signal_score_sell": -20.0,
            },
            "dry_run": True,
            "max_notional_krw": 5_000_000,
            "min_trade_interval_days": 5,
        }
        client.put("/api/v1/auto-trader/config", json=default_config)

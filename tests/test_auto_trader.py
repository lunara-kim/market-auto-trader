"""
AutoTrader 자동매매 엔진 테스트
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.analysis.screener import ScreeningResult, StockFundamentals
from src.analysis.sentiment import (
    FearGreedIndex,
    MarketSentimentResult,
    SentimentResult,
)
from src.broker.kis_client import KISClient
from src.strategy.auto_trader import (
    AutoTrader,
    AutoTraderConfig,
    SignalType,
    TradeSignal,
)


# ───────────────── Fixtures ─────────────────


def _make_sentiment(score: int = 30) -> MarketSentimentResult:
    """테스트용 센티멘트 결과 생성"""
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
    t = AutoTrader(mock_kis, config)
    return t


# ───────────────── calculate_signal 테스트 ─────────────────


class TestCalculateSignal:
    """calculate_signal 테스트"""

    def test_strong_buy_signal(self, trader: AutoTrader, mock_kis: MagicMock) -> None:
        """극도의 공포 + 저평가 종목 → STRONG_BUY"""
        sentiment = _make_sentiment(score=10)  # 극단적 공포 → +24 센티멘트
        fundamentals = _make_fundamentals()  # eligible
        screening = _make_screening(fundamentals, eligible=True)

        with (
            patch.object(trader._screener, "get_fundamentals", return_value=fundamentals),
            patch.object(trader._screener, "evaluate_quality", return_value=screening),
        ):
            # 전일대비 -5% → RSI +20, 하단 근처 → 볼린저 +15
            mock_kis.get_price.return_value = {
                "stck_prpr": "68000",
                "prdy_ctrt": "-5.0",
                "stck_hgpr": "72000",
                "stck_lwpr": "68000",
                "per": "8.0",
                "hts_kor_isnm": "삼성전자",
            }
            signal = trader.calculate_signal("005930", sentiment)

        assert signal.signal_type == SignalType.STRONG_BUY
        assert signal.score > 70
        assert signal.sentiment_score > 0
        assert signal.quality_score == 25.0

    def test_buy_signal(self, trader: AutoTrader, mock_kis: MagicMock) -> None:
        """공포 + 저평가 → BUY"""
        sentiment = _make_sentiment(score=35)  # 공포 → +9 센티멘트
        fundamentals = _make_fundamentals()
        screening = _make_screening(fundamentals, eligible=True)

        with (
            patch.object(trader._screener, "get_fundamentals", return_value=fundamentals),
            patch.object(trader._screener, "evaluate_quality", return_value=screening),
        ):
            mock_kis.get_price.return_value = {
                "stck_prpr": "69000",
                "prdy_ctrt": "-2.0",
                "stck_hgpr": "72000",
                "stck_lwpr": "68000",
                "per": "8.0",
                "hts_kor_isnm": "삼성전자",
            }
            signal = trader.calculate_signal("005930", sentiment)

        assert signal.signal_type == SignalType.BUY
        assert signal.score > 40

    def test_hold_signal(self, trader: AutoTrader, mock_kis: MagicMock) -> None:
        """중립 센티멘트 + 보통 기술 → HOLD"""
        sentiment = _make_sentiment(score=50)  # 중립 → 0 센티멘트
        fundamentals = _make_fundamentals()
        screening = _make_screening(fundamentals, eligible=True)

        with (
            patch.object(trader._screener, "get_fundamentals", return_value=fundamentals),
            patch.object(trader._screener, "evaluate_quality", return_value=screening),
        ):
            mock_kis.get_price.return_value = {
                "stck_prpr": "70000",
                "prdy_ctrt": "0.0",
                "stck_hgpr": "70500",
                "stck_lwpr": "69500",
                "per": "10.0",
                "hts_kor_isnm": "삼성전자",
            }
            signal = trader.calculate_signal("005930", sentiment)

        assert signal.signal_type == SignalType.HOLD

    def test_sell_signal(self, trader: AutoTrader, mock_kis: MagicMock) -> None:
        """극단적 탐욕 + 과매수 → SELL"""
        sentiment = _make_sentiment(score=95)  # 극단적 탐욕 → -27 센티멘트
        fundamentals = _make_fundamentals()
        screening = _make_screening(fundamentals, eligible=True)

        with (
            patch.object(trader._screener, "get_fundamentals", return_value=fundamentals),
            patch.object(trader._screener, "evaluate_quality", return_value=screening),
        ):
            mock_kis.get_price.return_value = {
                "stck_prpr": "75000",
                "prdy_ctrt": "5.0",
                "stck_hgpr": "75000",
                "stck_lwpr": "70000",
                "per": "10.0",
                "hts_kor_isnm": "삼성전자",
            }
            signal = trader.calculate_signal("005930", sentiment)

        assert signal.signal_type in (SignalType.SELL, SignalType.STRONG_SELL)
        assert signal.score < -30

    def test_value_trap_excluded(self, trader: AutoTrader, mock_kis: MagicMock) -> None:
        """가치함정 종목 → HOLD (제외)"""
        sentiment = _make_sentiment(score=20)
        fundamentals = _make_fundamentals(roe=3.0, revenue_growth_yoy=-5.0)
        screening = _make_screening(
            fundamentals, quality="value_trap", eligible=False
        )

        with (
            patch.object(trader._screener, "get_fundamentals", return_value=fundamentals),
            patch.object(trader._screener, "evaluate_quality", return_value=screening),
        ):
            signal = trader.calculate_signal("005930", sentiment)

        assert signal.signal_type == SignalType.HOLD
        assert signal.score == 0.0
        assert "제외" in signal.reason

    def test_poor_shareholder_return_excluded(
        self, trader: AutoTrader, mock_kis: MagicMock
    ) -> None:
        """주주환원 미흡 → HOLD (제외)"""
        sentiment = _make_sentiment(score=20)
        fundamentals = _make_fundamentals(dividend_yield=0.3)
        screening = _make_screening(
            fundamentals, quality="poor_shareholder_return", eligible=False
        )

        with (
            patch.object(trader._screener, "get_fundamentals", return_value=fundamentals),
            patch.object(trader._screener, "evaluate_quality", return_value=screening),
        ):
            signal = trader.calculate_signal("005930", sentiment)

        assert signal.signal_type == SignalType.HOLD
        assert signal.score == 0.0
        assert "제외" in signal.reason


# ───────────────── scan_universe 테스트 ─────────────────


class TestScanUniverse:
    def test_scan_universe(self, trader: AutoTrader, mock_kis: MagicMock) -> None:
        """전체 스캔 → 시그널 리스트 반환 (점수 내림차순)"""
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
                        sentiment_score=10.0,
                        quality_score=25.0,
                        technical_score=15.0,
                        reason="test",
                        recommended_action="buy",
                    ),
                    TradeSignal(
                        stock_code="000660",
                        stock_name="SK하이닉스",
                        signal_type=SignalType.STRONG_BUY,
                        score=80.0,
                        sentiment_score=20.0,
                        quality_score=25.0,
                        technical_score=35.0,
                        reason="test",
                        recommended_action="buy",
                    ),
                ],
            ),
        ):
            signals = trader.scan_universe()

        assert len(signals) == 2
        # 점수 내림차순
        assert signals[0].score > signals[1].score
        assert signals[0].stock_code == "000660"


# ───────────────── execute_signals 테스트 ─────────────────


class TestExecuteSignals:
    def test_daily_trade_limit(self, trader: AutoTrader, mock_kis: MagicMock) -> None:
        """일일 거래 한도 초과 시 중단"""
        trader._daily_trade_count = 10  # 이미 한도 도달

        signals = [
            TradeSignal(
                stock_code="005930",
                stock_name="삼성전자",
                signal_type=SignalType.BUY,
                score=50.0,
                sentiment_score=10.0,
                quality_score=25.0,
                technical_score=15.0,
                reason="test",
                recommended_action="buy",
            )
        ]

        with patch.object(trader._sentiment, "analyze", return_value=_make_sentiment()):
            results = trader.execute_signals(signals)

        assert len(results) == 0

    def test_position_limit(self, trader: AutoTrader, mock_kis: MagicMock) -> None:
        """총 포지션 한도 초과 시 중단"""
        mock_kis.get_balance.return_value = {
            "holdings": [{"evlu_amt": "90000000"}],  # 90% 투자 중
            "summary": [{"tot_evlu_amt": "100000000"}],
        }

        signals = [
            TradeSignal(
                stock_code="005930",
                stock_name="삼성전자",
                signal_type=SignalType.BUY,
                score=50.0,
                sentiment_score=10.0,
                quality_score=25.0,
                technical_score=15.0,
                reason="test",
                recommended_action="buy",
            )
        ]

        with patch.object(trader._sentiment, "analyze", return_value=_make_sentiment()):
            results = trader.execute_signals(signals)

        assert len(results) == 0

    def test_dry_run_mode(self, trader: AutoTrader, mock_kis: MagicMock) -> None:
        """dry_run 모드에서 실제 주문 없이 시뮬레이션"""
        assert trader.config.dry_run is True

        signals = [
            TradeSignal(
                stock_code="005930",
                stock_name="삼성전자",
                signal_type=SignalType.BUY,
                score=50.0,
                sentiment_score=10.0,
                quality_score=25.0,
                technical_score=15.0,
                reason="test",
                recommended_action="buy 1주 @ 70,000원",
            )
        ]

        with patch.object(trader._sentiment, "analyze", return_value=_make_sentiment()):
            results = trader.execute_signals(signals)

        assert len(results) == 1
        assert results[0]["dry_run"] is True
        assert results[0]["action"] == "buy"
        mock_kis.place_order.assert_not_called()


# ───────────────── check_holdings_for_sell 테스트 ─────────────────


class TestCheckHoldingsForSell:
    def test_take_profit(self, trader: AutoTrader, mock_kis: MagicMock) -> None:
        """익절: +15% 이상 → SELL"""
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
        """손절: -7% 이하 → STRONG_SELL"""
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
        """전체 사이클 통합 테스트"""
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
                        sentiment_score=10.0,
                        quality_score=25.0,
                        technical_score=15.0,
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
        assert isinstance(result["buy_signals"], list)
        assert isinstance(result["sell_signals"], list)
        assert isinstance(result["executed_buys"], list)
        assert isinstance(result["executed_sells"], list)


# ───────────────── API 엔드포인트 테스트 ─────────────────


class TestAutoTraderAPI:
    @pytest.fixture
    def client(self) -> TestClient:
        from src.main import app

        return TestClient(app)

    def test_get_config(self, client: TestClient) -> None:
        """GET /api/v1/auto-trader/config"""
        resp = client.get("/api/v1/auto-trader/config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["dry_run"] is True
        assert "risk_limits" in data

    def test_put_config(self, client: TestClient) -> None:
        """PUT /api/v1/auto-trader/config"""
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
        assert data["risk_limits"]["max_daily_trades"] == 5

        # Reset config for other tests
        default_config = {
            "universe_name": "kospi_top30",
            "risk_limits": {
                "max_daily_trades": 10,
                "max_position_pct": 0.2,
                "max_total_position_pct": 0.8,
                "max_daily_loss_pct": 0.03,
                "min_signal_score_buy": 40.0,
                "max_signal_score_sell": -30.0,
            },
            "dry_run": True,
            "max_notional_krw": 5_000_000,
        }
        client.put("/api/v1/auto-trader/config", json=default_config)

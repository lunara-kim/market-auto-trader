"""
설정 모듈 테스트

config 패키지의 Settings, TradingSettings, BacktestSettings를
검증합니다. 환경변수 기반 설정이 올바르게 로드되고 기본값이
정확한지 확인합니다.
"""

from __future__ import annotations

import os
from unittest.mock import patch



# ─────────────────────────────────────────────
# TradingSettings 테스트
# ─────────────────────────────────────────────

class TestTradingSettings:
    """매매 설정 테스트"""

    def test_default_values(self) -> None:
        """기본값 확인"""
        from config.trading import TradingSettings

        ts = TradingSettings()
        assert ts.buy_commission_rate == 0.00015
        assert ts.sell_commission_rate == 0.00015
        assert ts.total_sell_tax_rate == 0.0023
        assert ts.ma_short_window == 5
        assert ts.ma_long_window == 20
        assert ts.ma_signal_threshold == 0.0
        assert ts.max_risk_per_trade_pct == 1.0
        assert ts.max_position_size_pct == 20.0
        assert ts.max_daily_loss_pct == 3.0
        assert ts.oneshot_max_notional_krw == 1_000_000

    def test_env_override(self) -> None:
        """환경변수로 값 오버라이드"""
        from config.trading import TradingSettings

        env = {
            "TRADING_BUY_COMMISSION_RATE": "0.0003",
            "TRADING_MA_SHORT_WINDOW": "10",
            "TRADING_MAX_DAILY_LOSS_PCT": "5.0",
        }
        with patch.dict(os.environ, env, clear=False):
            ts = TradingSettings()
            assert ts.buy_commission_rate == 0.0003
            assert ts.ma_short_window == 10
            assert ts.max_daily_loss_pct == 5.0

    def test_tax_rates(self) -> None:
        """세금 항목 구분"""
        from config.trading import TradingSettings

        ts = TradingSettings()
        assert ts.securities_tax_rate == 0.0018
        assert ts.rural_tax_rate == 0.0015
        # 거래세 + 농특세 ≈ total_sell_tax_rate
        assert abs(
            ts.securities_tax_rate + ts.rural_tax_rate - 0.0033
        ) < 0.0001


# ─────────────────────────────────────────────
# BacktestSettings 테스트
# ─────────────────────────────────────────────

class TestBacktestSettings:
    """백테스트 설정 테스트"""

    def test_default_values(self) -> None:
        """기본값 확인"""
        from config.backtest import BacktestSettings

        bs = BacktestSettings()
        assert bs.initial_capital == 10_000_000.0
        assert bs.commission_rate is None
        assert bs.sell_tax_rate is None
        assert bs.risk_free_rate == 0.035
        assert bs.trading_days_per_year == 252
        assert bs.lookback_multiplier == 1.5

    def test_get_commission_rate_fallback(self) -> None:
        """수수료 fallback 로직"""
        from config.backtest import BacktestSettings

        bs = BacktestSettings()
        # 미설정 → fallback 사용
        assert bs.get_commission_rate(fallback=0.0002) == 0.0002

    def test_get_commission_rate_override(self) -> None:
        """수수료 직접 설정"""
        from config.backtest import BacktestSettings

        env = {"BACKTEST_COMMISSION_RATE": "0.0005"}
        with patch.dict(os.environ, env, clear=False):
            bs = BacktestSettings()
            assert bs.get_commission_rate(fallback=0.0002) == 0.0005

    def test_get_sell_tax_rate_fallback(self) -> None:
        """매도 세율 fallback"""
        from config.backtest import BacktestSettings

        bs = BacktestSettings()
        assert bs.get_sell_tax_rate(fallback=0.003) == 0.003

    def test_get_sell_tax_rate_override(self) -> None:
        """매도 세율 직접 설정"""
        from config.backtest import BacktestSettings

        env = {"BACKTEST_SELL_TAX_RATE": "0.001"}
        with patch.dict(os.environ, env, clear=False):
            bs = BacktestSettings()
            assert bs.get_sell_tax_rate(fallback=0.003) == 0.001

    def test_env_override(self) -> None:
        """환경변수로 오버라이드"""
        from config.backtest import BacktestSettings

        env = {
            "BACKTEST_INITIAL_CAPITAL": "50000000",
            "BACKTEST_RISK_FREE_RATE": "0.04",
            "BACKTEST_TRADING_DAYS_PER_YEAR": "250",
        }
        with patch.dict(os.environ, env, clear=False):
            bs = BacktestSettings()
            assert bs.initial_capital == 50_000_000.0
            assert bs.risk_free_rate == 0.04
            assert bs.trading_days_per_year == 250


# ─────────────────────────────────────────────
# config 패키지 통합 테스트
# ─────────────────────────────────────────────

class TestConfigPackage:
    """config 패키지 import 테스트"""

    def test_import_all(self) -> None:
        """패키지에서 모든 설정을 import 가능"""
        from config import backtest_settings, settings, trading_settings

        assert settings is not None
        assert trading_settings is not None
        assert backtest_settings is not None

    def test_settings_basic(self) -> None:
        """기본 앱 설정 확인"""
        from config import settings

        assert hasattr(settings, "app_env")
        assert hasattr(settings, "database_url")
        assert hasattr(settings, "kis_mock")

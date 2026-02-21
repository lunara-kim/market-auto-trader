from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd

from src.analysis.screener import ScreeningResult, StockFundamentals
from src.backtest.engine import BacktestConfig, BacktestEngine


def _fake_screening(symbol: str = "AAPL", eligible: bool = True) -> ScreeningResult:
    fundamentals = StockFundamentals(
        stock_code=symbol,
        stock_name=symbol,
        per=10.0,
        pbr=1.5,
        roe=15.0,
        dividend_yield=2.0,
        operating_margin=15.0,
        revenue_growth_yoy=10.0,
        sector="IT",
        sector_avg_per=20.0,
        sector_avg_operating_margin=10.0,
    )
    return ScreeningResult(
        stock_code=symbol,
        stock_name=symbol,
        fundamentals=fundamentals,
        quality="undervalued" if eligible else "value_trap",
        quality_score=80.0,
        reason="test",
        eligible=eligible,
    )


class TestBacktestEngine:
    def _make_sample_df(self) -> pd.DataFrame:
        # V자 반등 패턴: 하락 후 상승 → RSI가 과매도→반등하여 매수 시그널 발생
        import math

        idx = pd.date_range("2024-01-01", periods=60, freq="D")
        close = []
        for i in range(60):
            # 처음 30일 하락, 이후 30일 상승 (사인파 기반)
            close.append(100 + 20 * math.sin((i - 15) / 60 * 2 * math.pi))
        data = {
            "Open": close,
            "High": [c * 1.02 for c in close],
            "Low": [c * 0.98 for c in close],
            "Close": close,
            "Volume": [1_000] * 60,
        }
        return pd.DataFrame(data, index=idx)

    def test_run_single_symbol_generates_trades(self, monkeypatch) -> None:
        df = self._make_sample_df()

        # KISClient는 사용하지 않도록 더미 객체 주입
        dummy_client = MagicMock()
        engine = BacktestEngine(kis_client=dummy_client, config=BacktestConfig(initial_capital=1_000_000))

        # Screener는 항상 eligible=True 를 반환하도록 패치
        monkeypatch.setattr(engine, "_screener", MagicMock())
        engine._screener.get_fundamentals.return_value = _fake_screening().fundamentals
        engine._screener.evaluate_quality.return_value = _fake_screening(eligible=True)

        result = engine.run({"AAPL": df})

        # 최소 한 번 이상의 트레이드가 발생해야 한다
        assert result.trades
        # 결과 수익률과 MDD 계산이 수행되었는지 확인
        assert isinstance(result.total_return, float)
        assert isinstance(result.max_drawdown, float)

    def test_run_multiple_symbols(self, monkeypatch) -> None:
        df = self._make_sample_df()

        dummy_client = MagicMock()
        engine = BacktestEngine(kis_client=dummy_client, config=BacktestConfig(initial_capital=2_000_000))

        monkeypatch.setattr(engine, "_screener", MagicMock())
        engine._screener.get_fundamentals.return_value = _fake_screening().fundamentals
        engine._screener.evaluate_quality.return_value = _fake_screening(eligible=True)

        result = engine.run({"AAPL": df, "MSFT": df})

        # 심볼별 결과가 존재해야 한다
        assert set(result.per_symbol.keys()) == {"AAPL", "MSFT"}
        assert result.per_symbol["AAPL"]["initial_capital"] > 0

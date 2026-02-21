from __future__ import annotations

from unittest.mock import patch

import pandas as pd

from src.backtest.data_loader import load_history


class TestLoadHistory:
    def test_load_history_basic(self) -> None:
        data = pd.DataFrame(
            {
                "Open": [1, 2],
                "High": [2, 3],
                "Low": [0.5, 1.5],
                "Close": [1.5, 2.5],
                "Volume": [100, 200],
            },
            index=pd.date_range("2024-01-01", periods=2, freq="D"),
        )

        with patch("src.backtest.data_loader.yf.download", return_value=data) as mock_dl:
            df = load_history("AAPL", period="1mo", interval="1d")

        mock_dl.assert_called_once()
        assert not df.empty
        assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]

    def test_load_history_empty(self) -> None:
        empty = pd.DataFrame()
        with patch("src.backtest.data_loader.yf.download", return_value=empty):
            df = load_history("AAPL")

        # 스키마는 유지
        assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
        assert df.empty

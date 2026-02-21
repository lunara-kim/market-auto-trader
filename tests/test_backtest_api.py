from __future__ import annotations

from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

from src.main import app


class TestBacktestAPI:
    def _make_df(self) -> pd.DataFrame:
        idx = pd.date_range("2024-01-01", periods=30, freq="D")
        close = [100 + i for i in range(30)]
        data = {
            "Open": close,
            "High": [c * 1.01 for c in close],
            "Low": [c * 0.99 for c in close],
            "Close": close,
            "Volume": [1_000] * 30,
        }
        return pd.DataFrame(data, index=idx)

    def test_run_and_get_backtest(self) -> None:
        client = TestClient(app)

        df = self._make_df()

        # yfinance 호출을 막기 위해 load_history를 패치
        with patch("src.api.backtest.load_history", side_effect=[df]):
            resp = client.post(
                "/api/v1/backtest/run",
                json={"symbols": ["AAPL"], "period": "6mo", "interval": "1d"},
            )

        assert resp.status_code == 200
        data = resp.json()
        backtest_id = data["backtest_id"]
        assert backtest_id

        # 결과 조회
        resp2 = client.get(f"/api/v1/backtest/results/{backtest_id}")
        assert resp2.status_code == 200
        result = resp2.json()["result"]
        assert "total_return" in result
        assert "trades" in result

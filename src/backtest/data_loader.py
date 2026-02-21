"""히스토리컬 가격 데이터 로더.

Yahoo Finance (yfinance)를 사용해 과거 OHLCV 데이터를 불러옵니다.
테스트에서는 yfinance 호출을 mock 해야 합니다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd
import yfinance as yf


Period = Literal["1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"]
Interval = Literal["1d", "1wk", "1mo"]


@dataclass(slots=True)
class HistoryRequest:
    """히스토리컬 데이터 요청 파라미터."""

    symbol: str
    period: Period = "1y"
    interval: Interval = "1d"


def load_history(symbol: str, period: Period = "1y", interval: Interval = "1d") -> pd.DataFrame:
    """단일 종목의 과거 OHLCV 데이터를 조회합니다.

    Args:
        symbol: 티커 심볼 (예: "005930.KS", "AAPL")
        period: 조회 기간 (yfinance period 문자열)
        interval: 캔들 간격

    Returns:
        인덱스가 DatetimeIndex 이고, ``["Open", "High", "Low", "Close", "Volume"]``
        컬럼을 가진 :class:`pandas.DataFrame`.

    Note:
        - 네트워크 오류나 데이터 없음 등으로 인해 빈 DataFrame이 반환될 수 있습니다.
        - 테스트에서는 :func:`yfinance.download` 를 mock 해야 합니다.
    """

    df = yf.download(symbol, period=period, interval=interval, auto_adjust=False, progress=False)

    if df.empty:
        # 컬럼 스키마는 유지해서 이후 로직이 실패하지 않도록 맞춰준다.
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])

    # yfinance ≥ 0.2.31 returns MultiIndex columns for single ticker; flatten.
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # yfinance는 Adj Close 등을 포함할 수 있으나, 백테스트에는 기본 OHLCV만 사용한다.
    required_cols = ["Open", "High", "Low", "Close", "Volume"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        # 누락된 컬럼은 NaN으로 채워 추가
        for col in missing:
            df[col] = pd.NA

    return df[required_cols].copy()

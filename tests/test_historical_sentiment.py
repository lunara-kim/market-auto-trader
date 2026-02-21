"""히스토리컬 Fear & Greed 로더 테스트."""

from __future__ import annotations

from src.backtest.historical_sentiment import (
    HistoricalFearGreedLoader,
    normalize_fear_greed,
)


def _make_fng_data(entries: list[tuple[str, int]]) -> dict:
    """(date_str, value) 쌍 → alternative.me API 응답 형태."""
    from datetime import datetime, timezone

    data = []
    for date_str, value in entries:
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        data.append({"value": str(value), "timestamp": str(int(dt.timestamp()))})
    return {"data": data}


class TestNormalize:
    def test_extreme_fear(self) -> None:
        assert normalize_fear_greed(0) == -100.0

    def test_neutral(self) -> None:
        assert normalize_fear_greed(50) == 0.0

    def test_extreme_greed(self) -> None:
        assert normalize_fear_greed(100) == 100.0


class TestHistoricalFearGreedLoader:
    def test_load_and_exact_match(self) -> None:
        raw = _make_fng_data([("2024-06-01", 45), ("2024-06-02", 60)])
        loader = HistoricalFearGreedLoader(fetcher=lambda: raw)
        loader.load()
        assert loader.get_score("2024-06-01") == 45
        assert loader.get_score("2024-06-02") == 60

    def test_fallback_to_previous_date(self) -> None:
        raw = _make_fng_data([("2024-06-01", 30), ("2024-06-03", 70)])
        loader = HistoricalFearGreedLoader(fetcher=lambda: raw)
        loader.load()
        # 2024-06-02 없으면 → 2024-06-01 사용
        assert loader.get_score("2024-06-02") == 30

    def test_no_earlier_date_returns_none(self) -> None:
        raw = _make_fng_data([("2024-06-05", 50)])
        loader = HistoricalFearGreedLoader(fetcher=lambda: raw)
        loader.load()
        assert loader.get_score("2024-06-01") is None

    def test_empty_cache_returns_none(self) -> None:
        loader = HistoricalFearGreedLoader(fetcher=lambda: {"data": []})
        loader.load()
        assert loader.get_score("2024-06-01") is None

    def test_get_normalized_score(self) -> None:
        raw = _make_fng_data([("2024-06-01", 25)])
        loader = HistoricalFearGreedLoader(fetcher=lambda: raw)
        loader.load()
        # (25 - 50) * 2 = -50
        assert loader.get_normalized_score("2024-06-01") == -50.0

    def test_get_normalized_score_missing(self) -> None:
        loader = HistoricalFearGreedLoader(fetcher=lambda: {"data": []})
        loader.load()
        assert loader.get_normalized_score("2024-06-01") == 0.0

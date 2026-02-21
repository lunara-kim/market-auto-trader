"""히스토리컬 Fear & Greed 데이터 로더.

alternative.me API에서 과거 일별 Fear & Greed Index를 가져와
백테스트 날짜와 매칭합니다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

import httpx

from src.utils.logger import get_logger

logger = get_logger(__name__)

HISTORICAL_FNG_URL = "https://api.alternative.me/fng/?limit=365&format=json"


def normalize_fear_greed(score: int) -> float:
    """0~100 → -100~+100 (기존 하이브리드 방식과 동일: ``(score - 50) * 2``)."""
    return (score - 50) * 2.0


class HistoricalFearGreedLoader:
    """과거 Fear & Greed Index 데이터 로더.

    Parameters
    ----------
    fetcher:
        테스트에서 API 호출을 mock하기 위한 콜백.
        ``None`` 이면 실제 HTTP 호출을 수행합니다.
    """

    def __init__(self, fetcher: Callable[[], dict] | None = None) -> None:
        self._fetcher = fetcher
        # date string "YYYY-MM-DD" → raw score (0~100)
        self._cache: dict[str, int] = {}
        self._sorted_dates: list[str] = []

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def load(self) -> None:
        """API(또는 fetcher)에서 데이터를 가져와 캐시합니다."""
        raw = self._fetch_raw()
        data_list = raw.get("data", [])
        cache: dict[str, int] = {}
        for entry in data_list:
            ts = int(entry["timestamp"])
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            date_str = dt.strftime("%Y-%m-%d")
            cache[date_str] = int(entry["value"])
        self._cache = cache
        self._sorted_dates = sorted(cache.keys())
        logger.info("히스토리컬 F&G 로드 완료: %d일치", len(cache))

    def get_score(self, date_str: str) -> int | None:
        """주어진 날짜의 raw Fear & Greed score (0~100)를 반환합니다.

        정확히 매칭되는 날짜가 없으면 가장 가까운 *이전* 날짜의 값을 반환합니다.
        이전 날짜도 없으면 ``None``을 반환합니다.
        """
        if not self._cache:
            return None

        if date_str in self._cache:
            return self._cache[date_str]

        # bisect로 가장 가까운 이전 날짜 찾기
        import bisect

        idx = bisect.bisect_right(self._sorted_dates, date_str) - 1
        if idx < 0:
            return None
        return self._cache[self._sorted_dates[idx]]

    def get_normalized_score(self, date_str: str) -> float:
        """정규화된 센티멘트 점수(-100~+100)를 반환합니다.

        데이터가 없으면 0.0(중립)을 반환합니다.
        """
        raw = self.get_score(date_str)
        if raw is None:
            return 0.0
        return normalize_fear_greed(raw)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _fetch_raw(self) -> dict:
        if self._fetcher is not None:
            return self._fetcher()
        client = httpx.Client(timeout=15)
        resp = client.get(HISTORICAL_FNG_URL)
        resp.raise_for_status()
        return resp.json()

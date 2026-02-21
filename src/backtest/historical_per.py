"""히스토리컬 PER Quality 계산 모듈.

yfinance에서 분기별 EPS 데이터를 가져와 trailing PER을 역산하고,
기존 screener.py의 업종평균 PER 대비 저평가 여부를 판단합니다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from src.analysis.screener import ScreenerConfig
from src.utils.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_SCREENER_CONFIG = ScreenerConfig()


@dataclass(slots=True)
class PERQualityResult:
    """PER 품질 판단 결과."""

    per: float | None  # trailing PER (None이면 계산 불가)
    sector_avg_per: float
    is_undervalued: bool  # PER < 업종평균
    quality_score: float  # 0 or +25


class HistoricalPERCalculator:
    """히스토리컬 PER Quality 계산기.

    Parameters
    ----------
    yf_fetcher:
        테스트 mock용. ``symbol`` 을 받아 ``{"trailing_eps": float, "sector": str}``
        형태의 dict를 반환합니다. ``None``이면 yfinance를 직접 호출합니다.
    sector_map:
        종목코드 → 업종명 매핑. ``None``이면 ``STOCK_SECTOR_MAP`` 을 사용합니다.
    """

    def __init__(
        self,
        yf_fetcher: Callable[[str], dict[str, Any]] | None = None,
        sector_map: dict[str, str] | None = None,
        screener_config: ScreenerConfig | None = None,
    ) -> None:
        self._yf_fetcher = yf_fetcher
        self._sector_map = sector_map
        self._config = screener_config or _DEFAULT_SCREENER_CONFIG
        # symbol → PERQualityResult 캐시 (전 기간 동일 값 적용)
        self._cache: dict[str, PERQualityResult] = {}

    def get_quality(self, symbol: str, current_price: float | None = None) -> PERQualityResult:
        """종목의 PER quality를 반환합니다.

        캐시된 결과가 있으면 재사용합니다 (현재 PER 스냅샷을 전 기간 적용).
        """
        if symbol in self._cache:
            return self._cache[symbol]

        result = self._calculate(symbol, current_price)
        self._cache[symbol] = result
        return result

    def _calculate(self, symbol: str, current_price: float | None) -> PERQualityResult:
        """PER quality 계산."""
        sector = self._get_sector(symbol)
        sector_avg_per = self._get_sector_avg_per(symbol, sector)

        info = self._fetch_info(symbol)
        trailing_eps = info.get("trailing_eps")

        if trailing_eps is not None and trailing_eps > 0 and current_price is not None and current_price > 0:
            per = current_price / trailing_eps
        elif info.get("per") is not None and info["per"] > 0:
            per = info["per"]
        else:
            # PER 계산 불가 → 보수적으로 excluded
            logger.debug("PER 계산 불가: %s", symbol)
            return PERQualityResult(
                per=None,
                sector_avg_per=sector_avg_per,
                is_undervalued=False,
                quality_score=0.0,
            )

        is_undervalued = per < sector_avg_per
        quality_score = 25.0 if is_undervalued else 0.0

        return PERQualityResult(
            per=per,
            sector_avg_per=sector_avg_per,
            is_undervalued=is_undervalued,
            quality_score=quality_score,
        )

    def _fetch_info(self, symbol: str) -> dict[str, Any]:
        if self._yf_fetcher is not None:
            return self._yf_fetcher(symbol)
        try:
            import yfinance as yf

            ticker = yf.Ticker(symbol)
            info = ticker.info or {}
            return {
                "trailing_eps": info.get("trailingEps"),
                "per": info.get("trailingPE"),
            }
        except Exception:
            logger.warning("yfinance 정보 조회 실패: %s", symbol)
            return {}

    def _get_sector(self, symbol: str) -> str:
        if self._sector_map is not None:
            return self._sector_map.get(symbol, "기타")
        from src.analysis.stock_data import STOCK_SECTOR_MAP

        return STOCK_SECTOR_MAP.get(symbol, "기타")

    def _get_sector_avg_per(self, symbol: str, sector: str) -> float:
        from src.analysis.screener import is_domestic_stock

        if is_domestic_stock(symbol):
            defaults_map = self._config.sector_defaults
        else:
            defaults_map = self._config.us_sector_defaults
        fallback = defaults_map.get("기타", {"avg_per": 15.0})
        return defaults_map.get(sector, fallback).get("avg_per", 15.0)

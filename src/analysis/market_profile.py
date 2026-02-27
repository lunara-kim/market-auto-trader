"""시장/섹터별 프로필 및 PER/PEG 기반 품질 분류

이 모듈은 종목 코드/티커를 기반으로 시장(KR/US) 및 섹터 타입을 추론하고,
섹터 특성에 맞게 PER 또는 PEG ratio를 사용한 품질 분류를 제공합니다.

테스트 및 기존 코드와의 하위호환을 위해 최소한의 기능만 구현합니다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.analysis.stock_data import STOCK_EXCHANGE_MAP, STOCK_SECTOR_MAP
from src.utils.logger import get_logger

logger = get_logger(__name__)


class SectorType(Enum):
    """섹터/전략 타입"""

    VALUE = "value"
    GROWTH = "growth"
    ETF = "etf"


@dataclass
class StockProfile:
    """시장/섹터별 프로필

    - market: "KR" 또는 "US"
    - sector: SectorType
    - use_peg_ratio: US GROWTH 종목의 경우 PEG ratio 사용 여부
    - skip_per_filter: ETF 등 PER 필터를 생략할지 여부
    """

    market: str
    sector: SectorType
    use_peg_ratio: bool = False
    skip_per_filter: bool = False


# ---------------------------------------------------------------------------
# Helper: 시장/섹터 감지
# ---------------------------------------------------------------------------


def _detect_market(stock_code: str) -> str:
    """종목 코드/티커로 시장(KR/US) 추론"""
    # STOCK_EXCHANGE_MAP에 있으면 우선 사용
    if stock_code in STOCK_EXCHANGE_MAP:
        exch = STOCK_EXCHANGE_MAP[stock_code]
        if exch.startswith("KR"):
            return "KR"
        if exch.startswith("US"):
            return "US"

    # 숫자 6자리 → 한국 주식으로 가정
    if stock_code.isdigit() and len(stock_code) == 6:
        return "KR"

    # 나머지는 기본적으로 US로 간주
    return "US"


def _detect_sector(stock_code: str, market: str) -> SectorType:
    """종목 코드/티커로 섹터 타입 추론

    STOCK_SECTOR_MAP에 명시된 매핑이 있으면 우선 사용하고,
    없으면 시장별 기본값을 사용합니다.
    """

    sector_hint = STOCK_SECTOR_MAP.get(stock_code)
    if sector_hint == "ETF":
        return SectorType.ETF
    if sector_hint == "GROWTH":
        return SectorType.GROWTH
    if sector_hint == "VALUE":
        return SectorType.VALUE

    # 기본값: KR → VALUE, US → GROWTH
    if market == "KR":
        return SectorType.VALUE
    return SectorType.GROWTH


def get_stock_profile(stock_code: str) -> StockProfile:
    """종목 코드/티커에 대한 프로필 반환"""
    market = _detect_market(stock_code)
    sector = _detect_sector(stock_code, market)

    if sector == SectorType.ETF:
        return StockProfile(market=market, sector=sector, use_peg_ratio=False, skip_per_filter=True)

    if market == "US" and sector == SectorType.GROWTH:
        # US 성장주: PEG ratio 사용
        return StockProfile(market=market, sector=sector, use_peg_ratio=True, skip_per_filter=False)

    # 그 외: 전통적 VALUE PER 필터 사용
    return StockProfile(market=market, sector=sector, use_peg_ratio=False, skip_per_filter=False)


# ---------------------------------------------------------------------------
# PEG / PER 기반 품질 분류
# ---------------------------------------------------------------------------


def _compute_peg(
    per: float,
    earnings_growth: float | None,
    revenue_growth: float | None,
) -> float | None:
    """성장률 정보로 PEG ratio 계산

    음수 또는 0 성장률인 경우 None을 반환합니다.
    우선순위: earnings_growth → revenue_growth
    """

    growth = earnings_growth
    if growth is None or growth <= 0:
        growth = revenue_growth

    if growth is None or growth <= 0:
        return None

    try:
        return per / (growth * 100.0)
    except Exception:  # pragma: no cover - 방어적 코드
        return None


def classify_by_profile(
    *,
    profile: StockProfile,
    per: float,
    sector_avg_per: float,
    earnings_growth: float | None = None,
    revenue_growth: float | None = None,
) -> tuple[str, float, str]:
    """프로필에 따라 품질 분류

    Returns (quality, score_adj, reason)
    - quality: "undervalued", "overvalued", "fair", "unknown" 등
    - score_adj: 0 or +25 (AutoTrader 품질 점수용)
    - reason: 설명 문자열
    """

    # ETF: 품질 필터 스킵
    if profile.skip_per_filter or profile.sector == SectorType.ETF:
        return "etf", 0.0, "ETF: PER 필터 스킵"

    # US 성장주: PEG ratio 사용
    if profile.market == "US" and profile.use_peg_ratio:
        peg = _compute_peg(per, earnings_growth, revenue_growth)
        if peg is None:
            return "fair", 0.0, "PEG 계산 불가 (성장률 부족)"

        if peg < 1.5:
            return "undervalued", 25.0, f"PEG={peg:.2f} < 1.5"
        if peg > 2.5:
            return "overvalued", 0.0, f"PEG={peg:.2f} > 2.5"
        return "fair", 0.0, f"PEG={peg:.2f} 중립 구간"

    # 한국/가치주: 업종 평균 PER 대비 상대적 저평가 판단
    if per < sector_avg_per:
        return "undervalued", 25.0, f"PER {per:.1f} < 업종평균 {sector_avg_per:.1f}"

    return "overvalued", 0.0, f"PER {per:.1f} ≥ 업종평균 {sector_avg_per:.1f}"

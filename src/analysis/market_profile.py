"""
시장/섹터별 필터 프로필 시스템

시장(KR/US)과 섹터(GROWTH/VALUE/ETF)에 따라 차별화된
PER 필터링 규칙을 적용합니다.

- KR VALUE: 기존 PER < 업종평균 로직
- US GROWTH: PEG ratio 기반 (PER / EPS성장률)
- US VALUE: PER 기준 완화 (threshold 25)
- ETF: PER 필터 스킵, 기술적 분석만
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MarketType(Enum):
    """시장 유형"""
    KR = "KR"
    US = "US"


class SectorType(Enum):
    """섹터 유형"""
    GROWTH = "GROWTH"
    VALUE = "VALUE"
    ETF = "ETF"


@dataclass
class StockProfile:
    """종목별 프로필"""
    symbol: str
    market: MarketType
    sector: SectorType
    per_threshold: float  # PER 상한 (이 이상이면 overvalued)
    use_peg_ratio: bool  # PEG ratio 사용 여부
    min_growth_rate: float  # 최소 성장률 요구치 (%)
    skip_per_filter: bool  # PER 필터 완전 스킵 (ETF용)
    high_growth_per_cap: float  # 고성장 시 PER 허용 상한


# ───────────────── 종목→섹터 매핑 ─────────────────

# 명시적 섹터 매핑 (여기 없으면 시장 기본값 적용)
SECTOR_MAPPING: dict[str, SectorType] = {
    # US GROWTH
    "AAPL": SectorType.GROWTH,
    "MSFT": SectorType.GROWTH,
    "GOOGL": SectorType.GROWTH,
    "AMZN": SectorType.GROWTH,
    "NVDA": SectorType.GROWTH,
    "META": SectorType.GROWTH,
    "TSLA": SectorType.GROWTH,
    "AVGO": SectorType.GROWTH,
    "CRM": SectorType.GROWTH,
    "NFLX": SectorType.GROWTH,
    "AMD": SectorType.GROWTH,
    # US VALUE
    "BRK.B": SectorType.VALUE,
    "JNJ": SectorType.VALUE,
    "JPM": SectorType.VALUE,
    "V": SectorType.VALUE,
    "UNH": SectorType.VALUE,
    "XOM": SectorType.VALUE,
    "WMT": SectorType.VALUE,
    "PG": SectorType.VALUE,
    "MA": SectorType.VALUE,
    "HD": SectorType.VALUE,
    "CVX": SectorType.VALUE,
    "MRK": SectorType.VALUE,
    "ABBV": SectorType.VALUE,
    "LLY": SectorType.VALUE,
    "PEP": SectorType.VALUE,
    "KO": SectorType.VALUE,
    "COST": SectorType.VALUE,
    "TMO": SectorType.VALUE,
    "CSCO": SectorType.VALUE,
    "ACN": SectorType.VALUE,
    "MCD": SectorType.VALUE,
    "DHR": SectorType.VALUE,
    # ETF
    "QQQ": SectorType.ETF,
    "SPY": SectorType.ETF,
    "VOO": SectorType.ETF,
    "IWM": SectorType.ETF,
    "VTI": SectorType.ETF,
    "KODEX200": SectorType.ETF,
    "TIGER200": SectorType.ETF,
}

# ───────────────── 프로필 기본값 ─────────────────

_PROFILE_DEFAULTS: dict[tuple[MarketType, SectorType], dict] = {
    (MarketType.KR, SectorType.VALUE): {
        "per_threshold": 15.0,
        "use_peg_ratio": False,
        "min_growth_rate": 0.0,
        "skip_per_filter": False,
        "high_growth_per_cap": 40.0,
    },
    (MarketType.KR, SectorType.GROWTH): {
        "per_threshold": 25.0,
        "use_peg_ratio": False,
        "min_growth_rate": 5.0,
        "skip_per_filter": False,
        "high_growth_per_cap": 60.0,
    },
    (MarketType.KR, SectorType.ETF): {
        "per_threshold": 0.0,
        "use_peg_ratio": False,
        "min_growth_rate": 0.0,
        "skip_per_filter": True,
        "high_growth_per_cap": 0.0,
    },
    (MarketType.US, SectorType.GROWTH): {
        "per_threshold": 50.0,
        "use_peg_ratio": True,
        "min_growth_rate": 10.0,
        "skip_per_filter": False,
        "high_growth_per_cap": 100.0,
    },
    (MarketType.US, SectorType.VALUE): {
        "per_threshold": 25.0,
        "use_peg_ratio": False,
        "min_growth_rate": 0.0,
        "skip_per_filter": False,
        "high_growth_per_cap": 50.0,
    },
    (MarketType.US, SectorType.ETF): {
        "per_threshold": 0.0,
        "use_peg_ratio": False,
        "min_growth_rate": 0.0,
        "skip_per_filter": True,
        "high_growth_per_cap": 0.0,
    },
}


def detect_market(symbol: str) -> MarketType:
    """종목 코드로 시장 자동 감지."""
    if symbol.endswith(".KS") or symbol.endswith(".KQ"):
        return MarketType.KR
    # 숫자 6자리 → 국내
    if symbol.isdigit() and len(symbol) == 6:
        return MarketType.KR
    return MarketType.US


def detect_sector(symbol: str, market: MarketType) -> SectorType:
    """종목→섹터 매핑. 매핑에 없으면 시장 기본값."""
    if symbol in SECTOR_MAPPING:
        return SECTOR_MAPPING[symbol]
    # 시장 기본값
    if market == MarketType.KR:
        return SectorType.VALUE
    return SectorType.GROWTH


def get_stock_profile(symbol: str) -> StockProfile:
    """종목 프로필 조회. 자동 매핑."""
    market = detect_market(symbol)
    sector = detect_sector(symbol, market)
    defaults = _PROFILE_DEFAULTS.get(
        (market, sector),
        _PROFILE_DEFAULTS[(MarketType.US, SectorType.GROWTH)],
    )
    return StockProfile(
        symbol=symbol,
        market=market,
        sector=sector,
        **defaults,
    )


def calculate_peg_ratio(
    trailing_pe: float,
    earnings_growth: float | None,
    revenue_growth: float | None,
) -> float | None:
    """PEG ratio 계산.

    earnings_growth 우선, 없으면 revenue_growth fallback.
    성장률이 0 이하이거나 없으면 None 반환.
    성장률은 소수(0.25 = 25%) 형태로 입력.
    """
    growth = earnings_growth if earnings_growth and earnings_growth > 0 else revenue_growth
    if not growth or growth <= 0:
        return None
    # growth를 % 단위로 변환 (0.25 → 25)
    growth_pct = growth * 100
    if growth_pct <= 0:
        return None
    return trailing_pe / growth_pct


def classify_by_profile(
    profile: StockProfile,
    per: float,
    sector_avg_per: float,
    earnings_growth: float | None = None,
    revenue_growth: float | None = None,
) -> tuple[str, float, str]:
    """프로필별 PER 품질 분류.

    Returns:
        (quality, score_adjustment, reason)
        - quality: "undervalued", "fair", "overvalued", "skip"
        - score_adjustment: 시그널 점수에 더할 값
        - reason: 판단 사유
    """
    # ETF: PER 필터 스킵
    if profile.skip_per_filter:
        return "skip", 0.0, "ETF — PER 필터 스킵"

    # PEG ratio 모드 (US GROWTH)
    if profile.use_peg_ratio:
        peg = calculate_peg_ratio(per, earnings_growth, revenue_growth)

        # 고성장 기업 특례: 매출 성장률 > 20%면 PER 100까지 허용
        if revenue_growth and revenue_growth > 0.20:
            if per <= profile.high_growth_per_cap:
                if peg is not None and peg < 1.5:
                    return "undervalued", 25.0, (
                        f"PEG {peg:.2f} < 1.5 (고성장 {revenue_growth*100:.0f}%)"
                    )
                return "fair", 0.0, (
                    f"고성장 기업 (매출 +{revenue_growth*100:.0f}%), PER {per:.1f} 허용"
                )

        if peg is None:
            # 성장률 데이터 없음 → 기본 PER 필터 fallback
            if per > 0 and per < profile.per_threshold:
                return "fair", 0.0, f"PEG 계산 불가, PER {per:.1f} < {profile.per_threshold}"
            if per >= profile.per_threshold:
                return "overvalued", 0.0, f"PEG 계산 불가, PER {per:.1f} ≥ {profile.per_threshold}"
            return "fair", 0.0, "PEG 계산 불가, PER 데이터 없음"

        if peg < 1.5:
            return "undervalued", 25.0, f"PEG {peg:.2f} < 1.5 — 저평가"
        if peg <= 2.5:
            return "fair", 0.0, f"PEG {peg:.2f} (1.5~2.5) — 적정"
        return "overvalued", 0.0, f"PEG {peg:.2f} > 2.5 — 고평가"

    # 기본 PER 필터 (KR VALUE, US VALUE)
    if per <= 0:
        return "fair", 0.0, "PER 데이터 없음"

    per_discount = sector_avg_per * 0.7  # 업종평균의 70% 이하면 저평가
    if per < per_discount:
        return "undervalued", 25.0, (
            f"PER {per:.1f} < 업종평균 {sector_avg_per:.1f}×70% — 저평가"
        )
    if per < profile.per_threshold:
        return "fair", 0.0, f"PER {per:.1f} < {profile.per_threshold} — 적정"
    return "overvalued", 0.0, f"PER {per:.1f} ≥ {profile.per_threshold} — 고평가"

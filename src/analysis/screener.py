"""
종목 스크리너 — PER 품질 판단

PER이 낮은 종목을 3가지로 분류:
1. 진짜 저평가 (undervalued) → 매수 후보
2. 가치함정 (value_trap) → 제외
3. 주주환원 미흡 (poor_shareholder_return) → 제외
"""

from __future__ import annotations

from dataclasses import dataclass

from src.broker.kis_client import KISClient
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class StockFundamentals:
    """종목 재무지표"""

    stock_code: str
    stock_name: str
    per: float
    pbr: float
    roe: float
    dividend_yield: float
    operating_margin: float  # 영업이익률 (%)
    revenue_growth_yoy: float  # 매출 YoY 성장률 (%)
    sector: str
    sector_avg_per: float
    sector_avg_operating_margin: float
    has_buyback: bool = False  # 자사주 매입 이력


@dataclass
class ScreeningResult:
    """스크리닝 결과"""

    stock_code: str
    stock_name: str
    fundamentals: StockFundamentals
    quality: str  # "undervalued", "value_trap", "poor_shareholder_return"
    quality_score: float  # 0~100
    reason: str  # 판단 이유 설명
    eligible: bool  # 매수 후보 여부


# ───────────────── 업종 평균 기본값 (하드코딩) ─────────────────

SECTOR_DEFAULTS: dict[str, dict[str, float]] = {
    "반도체": {"avg_per": 15.0, "avg_operating_margin": 20.0},
    "바이오": {"avg_per": 40.0, "avg_operating_margin": 10.0},
    "자동차": {"avg_per": 8.0, "avg_operating_margin": 7.0},
    "금융": {"avg_per": 6.0, "avg_operating_margin": 25.0},
    "화학": {"avg_per": 10.0, "avg_operating_margin": 8.0},
    "IT": {"avg_per": 25.0, "avg_operating_margin": 15.0},
    "통신": {"avg_per": 10.0, "avg_operating_margin": 12.0},
    "에너지": {"avg_per": 8.0, "avg_operating_margin": 5.0},
    "소비재": {"avg_per": 12.0, "avg_operating_margin": 10.0},
    "기타": {"avg_per": 12.0, "avg_operating_margin": 10.0},
}


class StockScreener:
    """종목 스크리너 — PER 품질 판단"""

    def __init__(self, kis_client: KISClient) -> None:
        self._client = kis_client

    # ───────────────── 재무지표 조회 ─────────────────

    def get_fundamentals(self, stock_code: str) -> StockFundamentals:
        """KIS API로 종목 재무지표 조회.

        FHKST01010100 (현재가 시세)에서 PER/PBR 등 기본 지표를 가져오고,
        나머지는 업종 기본값으로 보완합니다.
        """
        price_data = self._client.get_price(stock_code)

        per = float(price_data.get("per", 0) or 0)
        pbr = float(price_data.get("pbr", 0) or 0)
        stock_name = price_data.get("hts_kor_isnm", stock_code)

        # 업종 기본값 적용
        sector = "기타"
        defaults = SECTOR_DEFAULTS.get(sector, SECTOR_DEFAULTS["기타"])

        return StockFundamentals(
            stock_code=stock_code,
            stock_name=stock_name,
            per=per,
            pbr=pbr,
            roe=0.0,  # KIS 기본 시세 API에 없음 → 추후 확장
            dividend_yield=0.0,
            operating_margin=0.0,
            revenue_growth_yoy=0.0,
            sector=sector,
            sector_avg_per=defaults["avg_per"],
            sector_avg_operating_margin=defaults["avg_operating_margin"],
            has_buyback=False,
        )

    # ───────────────── PER 품질 판단 ─────────────────

    def evaluate_quality(self, fundamentals: StockFundamentals) -> ScreeningResult:
        """PER 품질 판단 — 3가지 분류.

        판단 순서:
        1. 가치함정 체크 (ROE < 5% OR 매출 역성장)
        2. 진짜 저평가 체크 (PER/ROE/영업이익률/매출성장 모두 충족)
        3. 주주환원 미흡 체크 (배당 < 1% AND 자사주 매입 없음)
        4. 어디에도 해당 안 되면 주주환원 미흡으로 분류
        """
        f = fundamentals
        score = self.get_quality_score(f)

        per_low = f.per > 0 and f.per < f.sector_avg_per * 0.7

        # 1) 가치함정: PER 낮지만 ROE < 5% OR 매출 역성장
        if per_low and (f.roe < 5.0 or f.revenue_growth_yoy < 0):
            reasons = []
            if f.roe < 5.0:
                reasons.append(f"ROE {f.roe:.1f}% < 5%")
            if f.revenue_growth_yoy < 0:
                reasons.append(f"매출 역성장 {f.revenue_growth_yoy:.1f}%")
            return ScreeningResult(
                stock_code=f.stock_code,
                stock_name=f.stock_name,
                fundamentals=f,
                quality="value_trap",
                quality_score=score,
                reason=f"가치함정: {', '.join(reasons)}",
                eligible=False,
            )

        # 2) 진짜 저평가
        is_undervalued = (
            per_low
            and f.roe > 10.0
            and f.operating_margin > f.sector_avg_operating_margin
            and f.revenue_growth_yoy > 0
        )
        if is_undervalued:
            return ScreeningResult(
                stock_code=f.stock_code,
                stock_name=f.stock_name,
                fundamentals=f,
                quality="undervalued",
                quality_score=score,
                reason=(
                    f"진짜 저평가: PER {f.per:.1f} < 업종평균 {f.sector_avg_per:.1f}×70%, "
                    f"ROE {f.roe:.1f}%, 영업이익률 {f.operating_margin:.1f}%, "
                    f"매출성장 {f.revenue_growth_yoy:.1f}%"
                ),
                eligible=True,
            )

        # 3) 주주환원 미흡
        poor_return = f.dividend_yield < 1.0 and not f.has_buyback
        if per_low and poor_return:
            return ScreeningResult(
                stock_code=f.stock_code,
                stock_name=f.stock_name,
                fundamentals=f,
                quality="poor_shareholder_return",
                quality_score=score,
                reason=(
                    f"주주환원 미흡: 배당수익률 {f.dividend_yield:.1f}% < 1%, "
                    f"자사주 매입 이력 없음"
                ),
                eligible=False,
            )

        # 4) PER이 낮지 않거나 기타 → 기본적으로 제외
        return ScreeningResult(
            stock_code=f.stock_code,
            stock_name=f.stock_name,
            fundamentals=f,
            quality="poor_shareholder_return",
            quality_score=score,
            reason="PER 저평가 조건 미충족 또는 주주환원 미흡",
            eligible=False,
        )

    # ───────────────── 유니버스 스크리닝 ─────────────────

    def screen_universe(self, stock_codes: list[str]) -> list[ScreeningResult]:
        """종목 유니버스 전체 스크리닝."""
        results: list[ScreeningResult] = []
        for code in stock_codes:
            try:
                fundamentals = self.get_fundamentals(code)
                result = self.evaluate_quality(fundamentals)
                results.append(result)
            except Exception:
                logger.exception("스크리닝 실패: %s", code)
        return results

    # ───────────────── 품질 점수 ─────────────────

    def get_quality_score(self, fundamentals: StockFundamentals) -> float:
        """종목 품질 점수 (0~100).

        PER 상대가치: 30점
        ROE: 25점
        영업이익률: 20점
        매출성장률: 15점
        배당수익률: 10점
        """
        f = fundamentals
        score = 0.0

        # PER 상대가치 (30점): 업종평균 대비 낮을수록 높은 점수
        if f.sector_avg_per > 0 and f.per > 0:
            per_ratio = f.per / f.sector_avg_per
            # ratio 0.5 이하 → 30점, ratio 1.0 → 15점, ratio 1.5+ → 0점
            per_score = max(0.0, min(30.0, 30.0 * (1.5 - per_ratio)))
            score += per_score

        # ROE (25점): 높을수록 좋음
        # 0% → 0점, 15%+ → 25점
        roe_score = max(0.0, min(25.0, f.roe / 15.0 * 25.0))
        score += roe_score

        # 영업이익률 (20점): 업종평균 대비
        if f.sector_avg_operating_margin > 0:
            margin_ratio = f.operating_margin / f.sector_avg_operating_margin
            margin_score = max(0.0, min(20.0, margin_ratio * 10.0))
            score += margin_score

        # 매출성장률 (15점): 높을수록 좋음
        # -10% → 0점, 0% → 7.5점, 20%+ → 15점
        growth_score = max(0.0, min(15.0, (f.revenue_growth_yoy + 10) / 30.0 * 15.0))
        score += growth_score

        # 배당수익률 (10점): 높을수록 좋음
        # 0% → 0점, 5%+ → 10점
        div_score = max(0.0, min(10.0, f.dividend_yield / 5.0 * 10.0))
        score += div_score

        return round(score, 1)

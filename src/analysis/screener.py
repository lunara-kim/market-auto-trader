"""
종목 스크리너 — PER 품질 판단

PER이 낮은 종목을 3가지로 분류:
1. 진짜 저평가 (undervalued) → 매수 후보
2. 가치함정 (value_trap) → 제외
3. 주주환원 미흡 (poor_shareholder_return) → 제외
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.analysis.stock_data import STOCK_EXCHANGE_MAP, STOCK_FINANCIALS, STOCK_SECTOR_MAP
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


# ───────────────── 설정 ─────────────────


@dataclass
class ScreenerConfig:
    """스크리너 설정 — 모든 기준치를 파라미터로 관리"""

    # 업종 평균 기본값 (국내)
    sector_defaults: dict[str, dict[str, float]] = field(default_factory=lambda: {
        "반도체": {"avg_per": 15.0, "avg_operating_margin": 20.0},
        "바이오": {"avg_per": 40.0, "avg_operating_margin": 10.0},
        "자동차": {"avg_per": 8.0, "avg_operating_margin": 7.0},
        "금융": {"avg_per": 6.0, "avg_operating_margin": 25.0},
        "화학": {"avg_per": 10.0, "avg_operating_margin": 8.0},
        "IT": {"avg_per": 25.0, "avg_operating_margin": 15.0},
        "통신": {"avg_per": 10.0, "avg_operating_margin": 12.0},
        "에너지": {"avg_per": 8.0, "avg_operating_margin": 5.0},
        "소비재": {"avg_per": 12.0, "avg_operating_margin": 10.0},
        "헬스케어": {"avg_per": 25.0, "avg_operating_margin": 15.0},
        "기타": {"avg_per": 12.0, "avg_operating_margin": 10.0},
    })

    # US 업종 평균 기본값 (미국 시장은 밸류에이션이 다름)
    us_sector_defaults: dict[str, dict[str, float]] = field(default_factory=lambda: {
        "반도체": {"avg_per": 25.0, "avg_operating_margin": 30.0},
        "바이오": {"avg_per": 50.0, "avg_operating_margin": 15.0},
        "자동차": {"avg_per": 15.0, "avg_operating_margin": 10.0},
        "금융": {"avg_per": 12.0, "avg_operating_margin": 35.0},
        "화학": {"avg_per": 15.0, "avg_operating_margin": 12.0},
        "IT": {"avg_per": 30.0, "avg_operating_margin": 25.0},
        "통신": {"avg_per": 12.0, "avg_operating_margin": 15.0},
        "에너지": {"avg_per": 10.0, "avg_operating_margin": 10.0},
        "소비재": {"avg_per": 22.0, "avg_operating_margin": 12.0},
        "헬스케어": {"avg_per": 22.0, "avg_operating_margin": 20.0},
        "기타": {"avg_per": 18.0, "avg_operating_margin": 12.0},
    })

    # 판단 기준치
    value_trap_roe_threshold: float = 5.0  # ROE < 이 값이면 가치함정
    undervalued_roe_threshold: float = 10.0  # ROE > 이 값이면 저평가 후보
    per_discount_ratio: float = 0.7  # PER < 업종평균 × 이 비율이면 "PER 낮음"
    poor_return_dividend_threshold: float = 1.0  # 배당 < 이 값이면 주주환원 미흡


# 하위 호환: 기존 SECTOR_DEFAULTS를 기본 config에서 가져올 수 있도록
_DEFAULT_CONFIG = ScreenerConfig()
SECTOR_DEFAULTS = _DEFAULT_CONFIG.sector_defaults


def is_domestic_stock(stock_code: str) -> bool:
    """국내 종목 코드인지 판단 (숫자 6자리)."""
    return bool(re.fullmatch(r"\d{6}", stock_code))


class StockScreener:
    """종목 스크리너 — PER 품질 판단"""

    def __init__(
        self,
        kis_client: KISClient,
        config: ScreenerConfig | None = None,
    ) -> None:
        self._client = kis_client
        self._config = config or ScreenerConfig()

    # ───────────────── 재무지표 조회 ─────────────────

    def get_fundamentals(self, stock_code: str) -> StockFundamentals:
        """KIS API로 종목 재무지표 조회.

        국내 종목: FHKST01010100 (현재가 시세)에서 PER/PBR 조회
        해외 종목: get_overseas_price()에서 PER/PBR 조회

        ROE, 배당수익률, 영업이익률 등 API에서 제공하지 않는 지표는
        STOCK_FINANCIALS 딕셔너리에서 조회합니다.
        """
        domestic = is_domestic_stock(stock_code)

        if domestic:
            price_data = self._client.get_price(stock_code)
            per = float(price_data.get("per", 0) or 0)
            pbr = float(price_data.get("pbr", 0) or 0)
            stock_name = price_data.get("hts_kor_isnm", stock_code)
        else:
            exchange_code = STOCK_EXCHANGE_MAP.get(stock_code, "NASD")
            price_data = self._client.get_overseas_price(stock_code, exchange_code)
            per = float(price_data.get("per", 0) or 0)
            pbr = float(price_data.get("pbr", 0) or 0)
            stock_name = price_data.get("rsym", stock_code)

        # 업종 매핑
        sector = STOCK_SECTOR_MAP.get(stock_code, "기타")

        # 업종 기본값 (국내/해외 구분)
        if domestic:
            defaults_map = self._config.sector_defaults
        else:
            defaults_map = self._config.us_sector_defaults
        fallback = defaults_map.get("기타", {"avg_per": 12.0, "avg_operating_margin": 10.0})
        defaults = defaults_map.get(sector, fallback)

        # 종목별 재무지표 조회
        fin = STOCK_FINANCIALS.get(stock_code, {})
        roe = fin.get("roe", 0.0)
        dividend_yield = fin.get("dividend_yield", 0.0)
        operating_margin = fin.get("operating_margin", 0.0)
        revenue_growth_yoy = fin.get("revenue_growth_yoy", 0.0)

        return StockFundamentals(
            stock_code=stock_code,
            stock_name=stock_name,
            per=per,
            pbr=pbr,
            roe=roe,
            dividend_yield=dividend_yield,
            operating_margin=operating_margin,
            revenue_growth_yoy=revenue_growth_yoy,
            sector=sector,
            sector_avg_per=defaults["avg_per"],
            sector_avg_operating_margin=defaults["avg_operating_margin"],
            has_buyback=False,
        )

    # ───────────────── PER 품질 판단 ─────────────────

    def evaluate_quality(self, fundamentals: StockFundamentals) -> ScreeningResult:
        """PER 품질 판단 — 3가지 분류.

        판단 순서:
        1. 가치함정 체크 (ROE < threshold OR 매출 역성장)
        2. 진짜 저평가 체크 (PER/ROE/영업이익률/매출성장 모두 충족)
        3. 주주환원 미흡 체크 (배당 < threshold AND 자사주 매입 없음)
        4. 어디에도 해당 안 되면 주주환원 미흡으로 분류
        """
        f = fundamentals
        cfg = self._config
        score = self.get_quality_score(f)

        per_low = f.per > 0 and f.per < f.sector_avg_per * cfg.per_discount_ratio

        # 1) 가치함정: PER 낮지만 ROE 낮거나 매출 역성장
        if per_low and (
            f.roe < cfg.value_trap_roe_threshold or f.revenue_growth_yoy < 0
        ):
            reasons = []
            if f.roe < cfg.value_trap_roe_threshold:
                reasons.append(f"ROE {f.roe:.1f}% < {cfg.value_trap_roe_threshold}%")
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
            and f.roe > cfg.undervalued_roe_threshold
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
                    f"진짜 저평가: PER {f.per:.1f} < 업종평균 {f.sector_avg_per:.1f}×"
                    f"{cfg.per_discount_ratio:.0%}, "
                    f"ROE {f.roe:.1f}%, 영업이익률 {f.operating_margin:.1f}%, "
                    f"매출성장 {f.revenue_growth_yoy:.1f}%"
                ),
                eligible=True,
            )

        # 3) 주주환원 미흡
        poor_return = (
            f.dividend_yield < cfg.poor_return_dividend_threshold
            and not f.has_buyback
        )
        if per_low and poor_return:
            return ScreeningResult(
                stock_code=f.stock_code,
                stock_name=f.stock_name,
                fundamentals=f,
                quality="poor_shareholder_return",
                quality_score=score,
                reason=(
                    f"주주환원 미흡: 배당수익률 {f.dividend_yield:.1f}% "
                    f"< {cfg.poor_return_dividend_threshold}%, "
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
        growth_score = max(
            0.0, min(15.0, (f.revenue_growth_yoy + 10) / 30.0 * 15.0)
        )
        score += growth_score

        # 배당수익률 (10점): 높을수록 좋음
        # 0% → 0점, 5%+ → 10점
        div_score = max(0.0, min(10.0, f.dividend_yield / 5.0 * 10.0))
        score += div_score

        return round(score, 1)

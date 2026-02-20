"""
종목 유니버스 관리

KOSPI 시가총액 상위 종목 등 유니버스 프리셋을 제공하고,
사용자 정의 유니버스를 관리합니다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.utils.logger import get_logger

logger = get_logger(__name__)

# KOSPI 시가총액 상위 30 종목 코드
KOSPI_TOP30: list[str] = [
    "005930",  # 삼성전자
    "000660",  # SK하이닉스
    "373220",  # LG에너지솔루션
    "207940",  # 삼성바이오로직스
    "005380",  # 현대자동차
    "006400",  # 삼성SDI
    "051910",  # LG화학
    "035420",  # NAVER
    "000270",  # 기아
    "005490",  # POSCO홀딩스
    "035720",  # 카카오
    "105560",  # KB금융
    "055550",  # 신한지주
    "003550",  # LG
    "034730",  # SK
    "032830",  # 삼성생명
    "015760",  # 한국전력
    "066570",  # LG전자
    "003670",  # 포스코퓨처엠
    "086790",  # 하나금융지주
    "028260",  # 삼성물산
    "012330",  # 현대모비스
    "096770",  # SK이노베이션
    "259960",  # 크래프톤
    "034020",  # 두산에너빌리티
    "018260",  # 삼성에스디에스
    "316140",  # 우리금융지주
    "009150",  # 삼성전기
    "033780",  # KT&G
    "030200",  # KT
]

# US 시가총액 상위 30 종목
US_TOP30: list[str] = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK.B",
    "UNH", "JNJ", "V", "XOM", "JPM", "WMT", "PG", "MA", "HD", "CVX",
    "MRK", "ABBV", "LLY", "PEP", "KO", "COST", "AVGO", "TMO", "CSCO",
    "ACN", "MCD", "DHR",
]

# 기본 감시 종목 (KOSPI TOP 10)
DEFAULT_WATCHLIST: list[str] = KOSPI_TOP30[:10]


@dataclass
class StockUniverse:
    """종목 유니버스"""

    name: str
    stock_codes: list[str] = field(default_factory=list)
    description: str = ""


class UniverseManager:
    """종목 유니버스 관리"""

    def __init__(self) -> None:
        self._universes: dict[str, StockUniverse] = {
            "kospi_top30": StockUniverse(
                name="kospi_top30",
                stock_codes=list(KOSPI_TOP30),
                description="KOSPI 시가총액 상위 30",
            ),
            "us_top30": StockUniverse(
                name="us_top30",
                stock_codes=list(US_TOP30),
                description="US 시가총액 상위 30",
            ),
            "default_watchlist": StockUniverse(
                name="default_watchlist",
                stock_codes=list(DEFAULT_WATCHLIST),
                description="기본 감시 종목 (KOSPI TOP 10)",
            ),
        }

    def get_universe(self, name: str) -> StockUniverse | None:
        """유니버스 조회. 없으면 None 반환."""
        return self._universes.get(name)

    def list_universes(self) -> list[StockUniverse]:
        """전체 유니버스 목록 조회."""
        return list(self._universes.values())

    def add_stock(self, universe_name: str, stock_code: str) -> bool:
        """유니버스에 종목 추가. 성공 시 True."""
        universe = self._universes.get(universe_name)
        if universe is None:
            return False
        if stock_code not in universe.stock_codes:
            universe.stock_codes.append(stock_code)
            logger.info("종목 추가: %s → %s", stock_code, universe_name)
        return True

    def remove_stock(self, universe_name: str, stock_code: str) -> bool:
        """유니버스에서 종목 제거. 성공 시 True."""
        universe = self._universes.get(universe_name)
        if universe is None:
            return False
        if stock_code in universe.stock_codes:
            universe.stock_codes.remove(stock_code)
            logger.info("종목 제거: %s ← %s", stock_code, universe_name)
        return True

    def create_universe(
        self, name: str, stock_codes: list[str], description: str = ""
    ) -> StockUniverse:
        """새 유니버스 생성."""
        universe = StockUniverse(
            name=name,
            stock_codes=list(stock_codes),
            description=description,
        )
        self._universes[name] = universe
        logger.info("유니버스 생성: %s (%d종목)", name, len(stock_codes))
        return universe

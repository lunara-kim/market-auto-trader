"""
종목별 업종 매핑 및 재무지표 데이터

KOSPI_TOP30 + US_TOP30 종목에 대한 업종 분류와
최근 공시/리서치 기준 재무지표를 관리합니다.
주기적으로 업데이트가 필요합니다.

Last updated: 2025-02 (approximate values)
"""

from __future__ import annotations

# ───────────────── 종목 → 업종 매핑 ─────────────────

STOCK_SECTOR_MAP: dict[str, str] = {
    # 국내 (KOSPI TOP 30)
    "005930": "반도체",      # 삼성전자
    "000660": "반도체",      # SK하이닉스
    "373220": "에너지",      # LG에너지솔루션
    "207940": "바이오",      # 삼성바이오로직스
    "005380": "자동차",      # 현대자동차
    "006400": "에너지",      # 삼성SDI
    "051910": "화학",        # LG화학
    "035420": "IT",          # NAVER
    "000270": "자동차",      # 기아
    "005490": "화학",        # POSCO홀딩스
    "035720": "IT",          # 카카오
    "105560": "금융",        # KB금융
    "055550": "금융",        # 신한지주
    "003550": "화학",        # LG
    "034730": "화학",        # SK
    "032830": "금융",        # 삼성생명
    "015760": "에너지",      # 한국전력
    "066570": "소비재",      # LG전자
    "003670": "화학",        # 포스코퓨처엠
    "086790": "금융",        # 하나금융지주
    "028260": "소비재",      # 삼성물산
    "012330": "자동차",      # 현대모비스
    "096770": "에너지",      # SK이노베이션
    "259960": "IT",          # 크래프톤
    "034020": "에너지",      # 두산에너빌리티
    "018260": "IT",          # 삼성에스디에스
    "316140": "금융",        # 우리금융지주
    "009150": "반도체",      # 삼성전기
    "033780": "소비재",      # KT&G
    "030200": "통신",        # KT
    # 해외 (US TOP 30)
    "AAPL": "IT",
    "MSFT": "IT",
    "GOOGL": "IT",
    "AMZN": "소비재",
    "NVDA": "반도체",
    "META": "IT",
    "TSLA": "자동차",
    "BRK.B": "금융",
    "UNH": "헬스케어",
    "JNJ": "헬스케어",
    "V": "금융",
    "XOM": "에너지",
    "JPM": "금융",
    "WMT": "소비재",
    "PG": "소비재",
    "MA": "금융",
    "HD": "소비재",
    "CVX": "에너지",
    "MRK": "헬스케어",
    "ABBV": "헬스케어",
    "LLY": "헬스케어",
    "PEP": "소비재",
    "KO": "소비재",
    "COST": "소비재",
    "AVGO": "반도체",
    "TMO": "헬스케어",
    "CSCO": "IT",
    "ACN": "IT",
    "MCD": "소비재",
    "DHR": "헬스케어",
}

# ───────────────── 해외 종목 → 거래소 코드 매핑 ─────────────────

STOCK_EXCHANGE_MAP: dict[str, str] = {
    "AAPL": "NASD", "MSFT": "NASD", "GOOGL": "NASD", "AMZN": "NASD",
    "NVDA": "NASD", "META": "NASD", "TSLA": "NASD", "AVGO": "NASD",
    "COST": "NASD", "CSCO": "NASD", "PEP": "NASD", "TMO": "NYSE",
    "ACN": "NYSE", "MCD": "NYSE", "DHR": "NYSE",
    "BRK.B": "NYSE", "UNH": "NYSE", "JNJ": "NYSE", "V": "NYSE",
    "XOM": "NYSE", "JPM": "NYSE", "WMT": "NYSE", "PG": "NYSE",
    "MA": "NYSE", "HD": "NYSE", "CVX": "NYSE", "MRK": "NYSE",
    "ABBV": "NYSE", "LLY": "NYSE", "KO": "NYSE",
}

# ───────────────── 종목별 재무지표 (근사치) ─────────────────

STOCK_FINANCIALS: dict[str, dict[str, float]] = {
    # 국내 — roe(%), dividend_yield(%), operating_margin(%), revenue_growth_yoy(%)
    "005930": {"roe": 8.5, "dividend_yield": 2.1, "operating_margin": 15.0, "revenue_growth_yoy": 5.0},
    "000660": {"roe": 20.0, "dividend_yield": 1.2, "operating_margin": 30.0, "revenue_growth_yoy": 45.0},
    "373220": {"roe": 5.0, "dividend_yield": 0.0, "operating_margin": 8.0, "revenue_growth_yoy": 20.0},
    "207940": {"roe": 7.0, "dividend_yield": 0.0, "operating_margin": 20.0, "revenue_growth_yoy": 15.0},
    "005380": {"roe": 12.0, "dividend_yield": 3.5, "operating_margin": 9.0, "revenue_growth_yoy": 8.0},
    "006400": {"roe": 3.0, "dividend_yield": 0.0, "operating_margin": 5.0, "revenue_growth_yoy": -10.0},
    "051910": {"roe": 2.0, "dividend_yield": 3.0, "operating_margin": 4.0, "revenue_growth_yoy": -5.0},
    "035420": {"roe": 10.0, "dividend_yield": 0.5, "operating_margin": 20.0, "revenue_growth_yoy": 10.0},
    "000270": {"roe": 18.0, "dividend_yield": 4.0, "operating_margin": 11.0, "revenue_growth_yoy": 7.0},
    "005490": {"roe": 6.0, "dividend_yield": 4.0, "operating_margin": 5.0, "revenue_growth_yoy": -3.0},
    "035720": {"roe": 3.0, "dividend_yield": 0.0, "operating_margin": 8.0, "revenue_growth_yoy": -2.0},
    "105560": {"roe": 10.0, "dividend_yield": 5.0, "operating_margin": 30.0, "revenue_growth_yoy": 5.0},
    "055550": {"roe": 9.0, "dividend_yield": 4.5, "operating_margin": 28.0, "revenue_growth_yoy": 4.0},
    "003550": {"roe": 6.0, "dividend_yield": 2.5, "operating_margin": 8.0, "revenue_growth_yoy": 3.0},
    "034730": {"roe": 4.0, "dividend_yield": 2.0, "operating_margin": 6.0, "revenue_growth_yoy": -1.0},
    "032830": {"roe": 5.0, "dividend_yield": 3.5, "operating_margin": 15.0, "revenue_growth_yoy": 2.0},
    "015760": {"roe": -5.0, "dividend_yield": 0.0, "operating_margin": -3.0, "revenue_growth_yoy": 5.0},
    "066570": {"roe": 8.0, "dividend_yield": 2.0, "operating_margin": 5.0, "revenue_growth_yoy": 3.0},
    "003670": {"roe": -8.0, "dividend_yield": 0.0, "operating_margin": -5.0, "revenue_growth_yoy": -20.0},
    "086790": {"roe": 9.0, "dividend_yield": 5.0, "operating_margin": 27.0, "revenue_growth_yoy": 4.0},
    "028260": {"roe": 5.0, "dividend_yield": 1.5, "operating_margin": 6.0, "revenue_growth_yoy": 2.0},
    "012330": {"roe": 6.0, "dividend_yield": 3.0, "operating_margin": 7.0, "revenue_growth_yoy": 5.0},
    "096770": {"roe": 2.0, "dividend_yield": 1.0, "operating_margin": 3.0, "revenue_growth_yoy": -8.0},
    "259960": {"roe": 15.0, "dividend_yield": 0.0, "operating_margin": 35.0, "revenue_growth_yoy": 20.0},
    "034020": {"roe": 1.0, "dividend_yield": 0.0, "operating_margin": 2.0, "revenue_growth_yoy": 15.0},
    "018260": {"roe": 12.0, "dividend_yield": 2.0, "operating_margin": 10.0, "revenue_growth_yoy": 5.0},
    "316140": {"roe": 8.0, "dividend_yield": 6.0, "operating_margin": 25.0, "revenue_growth_yoy": 3.0},
    "009150": {"roe": 7.0, "dividend_yield": 2.5, "operating_margin": 10.0, "revenue_growth_yoy": 5.0},
    "033780": {"roe": 10.0, "dividend_yield": 5.0, "operating_margin": 15.0, "revenue_growth_yoy": 3.0},
    "030200": {"roe": 4.0, "dividend_yield": 5.0, "operating_margin": 10.0, "revenue_growth_yoy": 1.0},
    # 해외
    "AAPL": {"roe": 160.0, "dividend_yield": 0.5, "operating_margin": 33.0, "revenue_growth_yoy": 5.0},
    "MSFT": {"roe": 38.0, "dividend_yield": 0.7, "operating_margin": 45.0, "revenue_growth_yoy": 16.0},
    "GOOGL": {"roe": 30.0, "dividend_yield": 0.5, "operating_margin": 32.0, "revenue_growth_yoy": 14.0},
    "AMZN": {"roe": 22.0, "dividend_yield": 0.0, "operating_margin": 10.0, "revenue_growth_yoy": 12.0},
    "NVDA": {"roe": 115.0, "dividend_yield": 0.0, "operating_margin": 62.0, "revenue_growth_yoy": 120.0},
    "META": {"roe": 33.0, "dividend_yield": 0.4, "operating_margin": 40.0, "revenue_growth_yoy": 22.0},
    "TSLA": {"roe": 20.0, "dividend_yield": 0.0, "operating_margin": 8.0, "revenue_growth_yoy": 2.0},
    "BRK.B": {"roe": 16.0, "dividend_yield": 0.0, "operating_margin": 18.0, "revenue_growth_yoy": 8.0},
    "UNH": {"roe": 25.0, "dividend_yield": 1.3, "operating_margin": 8.5, "revenue_growth_yoy": 10.0},
    "JNJ": {"roe": 20.0, "dividend_yield": 3.0, "operating_margin": 22.0, "revenue_growth_yoy": 4.0},
    "V": {"roe": 47.0, "dividend_yield": 0.8, "operating_margin": 67.0, "revenue_growth_yoy": 10.0},
    "XOM": {"roe": 18.0, "dividend_yield": 3.3, "operating_margin": 14.0, "revenue_growth_yoy": -5.0},
    "JPM": {"roe": 17.0, "dividend_yield": 2.2, "operating_margin": 38.0, "revenue_growth_yoy": 12.0},
    "WMT": {"roe": 20.0, "dividend_yield": 1.3, "operating_margin": 4.5, "revenue_growth_yoy": 6.0},
    "PG": {"roe": 30.0, "dividend_yield": 2.4, "operating_margin": 23.0, "revenue_growth_yoy": 3.0},
    "MA": {"roe": 170.0, "dividend_yield": 0.6, "operating_margin": 58.0, "revenue_growth_yoy": 12.0},
    "HD": {"roe": 1500.0, "dividend_yield": 2.5, "operating_margin": 15.0, "revenue_growth_yoy": 3.0},
    "CVX": {"roe": 12.0, "dividend_yield": 4.2, "operating_margin": 12.0, "revenue_growth_yoy": -8.0},
    "MRK": {"roe": 35.0, "dividend_yield": 2.8, "operating_margin": 30.0, "revenue_growth_yoy": 7.0},
    "ABBV": {"roe": 60.0, "dividend_yield": 3.5, "operating_margin": 30.0, "revenue_growth_yoy": 5.0},
    "LLY": {"roe": 55.0, "dividend_yield": 0.7, "operating_margin": 30.0, "revenue_growth_yoy": 35.0},
    "PEP": {"roe": 50.0, "dividend_yield": 2.8, "operating_margin": 15.0, "revenue_growth_yoy": 2.0},
    "KO": {"roe": 40.0, "dividend_yield": 3.0, "operating_margin": 30.0, "revenue_growth_yoy": 3.0},
    "COST": {"roe": 28.0, "dividend_yield": 0.6, "operating_margin": 3.5, "revenue_growth_yoy": 8.0},
    "AVGO": {"roe": 30.0, "dividend_yield": 1.3, "operating_margin": 45.0, "revenue_growth_yoy": 44.0},
    "TMO": {"roe": 13.0, "dividend_yield": 0.3, "operating_margin": 22.0, "revenue_growth_yoy": 5.0},
    "CSCO": {"roe": 28.0, "dividend_yield": 2.8, "operating_margin": 30.0, "revenue_growth_yoy": -6.0},
    "ACN": {"roe": 28.0, "dividend_yield": 1.5, "operating_margin": 16.0, "revenue_growth_yoy": 3.0},
    "MCD": {"roe": 0.0, "dividend_yield": 2.3, "operating_margin": 45.0, "revenue_growth_yoy": 2.0},
    "DHR": {"roe": 8.0, "dividend_yield": 0.5, "operating_margin": 25.0, "revenue_growth_yoy": -3.0},
}

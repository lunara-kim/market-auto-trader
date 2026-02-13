"""
MarketDataCollector (시장 데이터 수집기) 테스트

초기화, 미구현 메서드의 NotImplementedError 확인,
그리고 파라미터 전달이 올바른지 검증합니다.
"""

import pytest
from datetime import datetime
from src.data.collector import MarketDataCollector


class TestMarketDataCollectorInit:
    """MarketDataCollector 초기화 테스트"""

    def test_init(self, collector):
        """MarketDataCollector가 정상 초기화되는지 확인"""
        assert isinstance(collector, MarketDataCollector)


class TestMarketDataCollectorMethods:
    """MarketDataCollector 메서드 테스트 (미구현 상태)"""

    def test_fetch_stock_price_raises_not_implemented(self, collector):
        """fetch_stock_price()가 NotImplementedError를 발생시키는지 확인"""
        with pytest.raises(NotImplementedError, match="fetch_stock_price"):
            collector.fetch_stock_price(
                stock_code="005930",
                start_date=datetime(2025, 1, 1),
                end_date=datetime(2025, 12, 31),
            )

    def test_fetch_economic_calendar_raises_not_implemented(self, collector):
        """fetch_economic_calendar()가 NotImplementedError를 발생시키는지 확인"""
        with pytest.raises(NotImplementedError, match="fetch_economic_calendar"):
            collector.fetch_economic_calendar(
                start_date=datetime(2025, 1, 1),
                end_date=datetime(2025, 1, 31),
            )

    def test_fetch_news_raises_not_implemented(self, collector):
        """fetch_news()가 NotImplementedError를 발생시키는지 확인"""
        with pytest.raises(NotImplementedError, match="fetch_news"):
            collector.fetch_news(stock_code="005930", limit=5)

    def test_fetch_news_default_limit_raises_not_implemented(self, collector):
        """fetch_news() limit 기본값(10)이 적용되는지 확인"""
        with pytest.raises(NotImplementedError, match="fetch_news"):
            collector.fetch_news(stock_code="035720")

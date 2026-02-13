"""
KISClient (한국투자증권 API 클라이언트) 테스트

초기화, 속성, 미구현 메서드의 NotImplementedError 확인,
그리고 모의투자/실전 모드 분기를 검증합니다.
"""

import pytest
from src.broker.kis_client import KISClient


class TestKISClientInit:
    """KISClient 초기화 테스트"""

    def test_init_with_mock_mode(self, kis_client):
        """모의투자 모드로 초기화되는지 확인"""
        assert kis_client.app_key == "test_app_key"
        assert kis_client.app_secret == "test_app_secret"
        assert kis_client.account_no == "12345678-01"
        assert kis_client.mock is True
        assert kis_client.access_token is None

    def test_init_with_real_mode(self, kis_client_real):
        """실전 모드로 초기화되는지 확인"""
        assert kis_client_real.mock is False

    def test_default_mock_mode(self):
        """mock 파라미터 생략 시 기본값이 True인지 확인"""
        client = KISClient(
            app_key="key",
            app_secret="secret",
            account_no="00000000-00",
        )
        assert client.mock is True

    def test_access_token_initially_none(self, kis_client):
        """초기 access_token이 None인지 확인"""
        assert kis_client.access_token is None


class TestKISClientMethods:
    """KISClient 메서드 테스트 (미구현 상태)"""

    def test_get_balance_raises_not_implemented(self, kis_client):
        """get_balance()가 NotImplementedError를 발생시키는지 확인"""
        with pytest.raises(NotImplementedError, match="get_balance"):
            kis_client.get_balance()

    def test_place_order_buy_raises_not_implemented(self, kis_client):
        """매수 주문이 NotImplementedError를 발생시키는지 확인"""
        with pytest.raises(NotImplementedError, match="place_order"):
            kis_client.place_order(
                stock_code="005930",
                order_type="buy",
                quantity=10,
                price=70000,
            )

    def test_place_order_sell_raises_not_implemented(self, kis_client):
        """매도 주문이 NotImplementedError를 발생시키는지 확인"""
        with pytest.raises(NotImplementedError, match="place_order"):
            kis_client.place_order(
                stock_code="005930",
                order_type="sell",
                quantity=5,
            )

    def test_place_order_market_price_raises_not_implemented(self, kis_client):
        """시장가 주문 (price=None)이 NotImplementedError를 발생시키는지 확인"""
        with pytest.raises(NotImplementedError, match="place_order"):
            kis_client.place_order(
                stock_code="035720",
                order_type="buy",
                quantity=1,
                price=None,
            )

    def test_get_price_raises_not_implemented(self, kis_client):
        """get_price()가 NotImplementedError를 발생시키는지 확인"""
        with pytest.raises(NotImplementedError, match="get_price"):
            kis_client.get_price("005930")

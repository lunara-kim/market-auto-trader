"""
KISClient 해외주식 메서드 테스트

해외주식 시세 조회, 주문, 잔고 조회 메서드를 모킹 기반으로 테스트합니다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import httpx
import pytest

from src.broker.kis_client import (
    KISClient,
    TR_ID_OVERSEAS_BALANCE,
    TR_ID_OVERSEAS_BUY,
    TR_ID_OVERSEAS_PRICE,
    VALID_EXCHANGE_CODES,
)
from src.exceptions import BrokerError, OrderError, ValidationError


MOCK_APP_KEY = "test_app_key_12345"
MOCK_APP_SECRET = "test_app_secret_67890"
MOCK_ACCOUNT = "12345678-01"

DUMMY_REQUEST = httpx.Request("GET", "http://test")


def _mock_response(status: int = 200, json_data: dict | None = None) -> httpx.Response:
    return httpx.Response(status, json=json_data or {}, request=DUMMY_REQUEST)


def _make_client(mock: bool = True) -> KISClient:
    """토큰이 세팅된 클라이언트 생성"""
    client = KISClient(MOCK_APP_KEY, MOCK_APP_SECRET, MOCK_ACCOUNT, mock=mock)
    client._access_token = "test_token"
    client._token_expired_at = datetime.now(timezone.utc) + timedelta(hours=1)
    return client


# ───────────────────── Overseas Price Tests ─────────────────────


class TestGetOverseasPrice:
    """해외주식 시세 조회 테스트"""

    @pytest.fixture
    def overseas_price_response(self):
        return {
            "rt_cd": "0",
            "msg_cd": "MCA00000",
            "msg1": "정상처리 되었습니다.",
            "output": {
                "last": "185.50",
                "diff": "2.30",
                "rate": "1.26",
                "tvol": "52345678",
                "tamt": "9876543210",
                "ordy": "Y",
            },
        }

    def test_get_overseas_price_success(self, overseas_price_response):
        """해외 시세 정상 조회"""
        client = _make_client()
        mock_resp = _mock_response(200, overseas_price_response)

        with patch.object(client._client, "get", return_value=mock_resp):
            result = client.get_overseas_price("AAPL", "NASD")

        assert result["last"] == "185.50"
        assert result["diff"] == "2.30"
        assert result["rate"] == "1.26"
        client.close()

    def test_get_overseas_price_passes_correct_params(self, overseas_price_response):
        """해외 시세 조회 시 올바른 파라미터 전달"""
        client = _make_client()
        mock_resp = _mock_response(200, overseas_price_response)

        with patch.object(client._client, "get", return_value=mock_resp) as mock_get:
            client.get_overseas_price("TSLA", "NASD")

        call_kwargs = mock_get.call_args
        assert call_kwargs.kwargs["params"]["EXCD"] == "NASD"
        assert call_kwargs.kwargs["params"]["SYMB"] == "TSLA"
        assert call_kwargs.kwargs["headers"]["tr_id"] == TR_ID_OVERSEAS_PRICE
        client.close()

    def test_get_overseas_price_invalid_ticker(self):
        """잘못된 티커 → ValidationError"""
        client = _make_client()
        with pytest.raises(ValidationError, match="해외 종목 티커"):
            client.get_overseas_price("", "NASD")
        with pytest.raises(ValidationError, match="해외 종목 티커"):
            client.get_overseas_price("123", "NASD")
        client.close()

    def test_get_overseas_price_invalid_exchange(self):
        """잘못된 거래소 코드 → ValidationError"""
        client = _make_client()
        with pytest.raises(ValidationError, match="거래소 코드"):
            client.get_overseas_price("AAPL", "INVALID")
        client.close()

    def test_get_overseas_price_api_error(self):
        """API 에러 응답 처리"""
        client = _make_client()
        error_resp = {
            "rt_cd": "1",
            "msg_cd": "EGW00123",
            "msg1": "기간이 만료된 token 입니다.",
        }
        mock_resp = _mock_response(200, error_resp)
        with patch.object(client._client, "get", return_value=mock_resp):
            with pytest.raises(BrokerError, match="기간이 만료된 token"):
                client.get_overseas_price("AAPL", "NASD")
        client.close()

    def test_get_overseas_price_all_exchanges(self, overseas_price_response):
        """모든 지원 거래소에서 조회 가능"""
        for excd in VALID_EXCHANGE_CODES:
            client = _make_client()
            mock_resp = _mock_response(200, overseas_price_response)
            with patch.object(client._client, "get", return_value=mock_resp):
                result = client.get_overseas_price("AAPL", excd)
            assert result["last"] == "185.50"
            client.close()


# ───────────────────── Overseas Order Tests ─────────────────────


class TestPlaceOverseasOrder:
    """해외주식 주문 테스트"""

    @pytest.fixture
    def overseas_order_response(self):
        return {
            "rt_cd": "0",
            "msg_cd": "APBK0013",
            "msg1": "주문 전송 완료 되었습니다.",
            "output": {
                "KRX_FWDG_ORD_ORGNO": "91252",
                "ODNO": "0000567890",
                "ORD_TMD": "093000",
            },
        }

    @pytest.fixture
    def hashkey_response(self):
        return {"HASH": "overseas_hash_key_123"}

    def test_place_overseas_order_success(self, overseas_order_response, hashkey_response):
        """해외주식 정상 주문"""
        client = _make_client()

        mock_hash_resp = _mock_response(200, hashkey_response)
        mock_order_resp = _mock_response(200, overseas_order_response)

        with patch.object(
            client._client, "post", side_effect=[mock_hash_resp, mock_order_resp]
        ):
            result = client.place_overseas_order("AAPL", "NASD", 1, 185.50)

        assert result["ODNO"] == "0000567890"
        assert result["ORD_TMD"] == "093000"
        client.close()

    def test_place_overseas_order_body_params(self, overseas_order_response, hashkey_response):
        """주문 요청 body 파라미터 확인"""
        client = _make_client()

        mock_hash_resp = _mock_response(200, hashkey_response)
        mock_order_resp = _mock_response(200, overseas_order_response)

        with patch.object(
            client._client, "post", side_effect=[mock_hash_resp, mock_order_resp]
        ) as mock_post:
            client.place_overseas_order("TSLA", "NYSE", 3, 250.75)

        order_call = mock_post.call_args_list[1]
        body = order_call.kwargs["json"]
        assert body["PDNO"] == "TSLA"
        assert body["OVRS_EXCG_CD"] == "NYSE"
        assert body["ORD_QTY"] == "3"
        assert body["OVRS_ORD_UNPR"] == "250.75"
        assert body["CANO"] == "12345678"
        assert body["ACNT_PRDT_CD"] == "01"
        client.close()

    def test_place_overseas_order_mock_tr_id(self, overseas_order_response, hashkey_response):
        """모의투자 → VTTT1002U"""
        client = _make_client(mock=True)

        mock_hash_resp = _mock_response(200, hashkey_response)
        mock_order_resp = _mock_response(200, overseas_order_response)

        with patch.object(
            client._client, "post", side_effect=[mock_hash_resp, mock_order_resp]
        ) as mock_post:
            client.place_overseas_order("AAPL", "NASD", 1, 185.50)

        order_call = mock_post.call_args_list[1]
        assert order_call.kwargs["headers"]["tr_id"] == TR_ID_OVERSEAS_BUY[0]
        client.close()

    def test_place_overseas_order_prod_tr_id(self, overseas_order_response, hashkey_response):
        """실전투자 → JTTT1002U"""
        client = _make_client(mock=False)

        mock_hash_resp = _mock_response(200, hashkey_response)
        mock_order_resp = _mock_response(200, overseas_order_response)

        with patch.object(
            client._client, "post", side_effect=[mock_hash_resp, mock_order_resp]
        ) as mock_post:
            client.place_overseas_order("AAPL", "NASD", 1, 185.50)

        order_call = mock_post.call_args_list[1]
        assert order_call.kwargs["headers"]["tr_id"] == TR_ID_OVERSEAS_BUY[1]
        client.close()

    def test_place_overseas_order_invalid_ticker(self):
        """잘못된 티커 → ValidationError"""
        client = _make_client()
        with pytest.raises(ValidationError, match="해외 종목 티커"):
            client.place_overseas_order("", "NASD", 1, 100.0)
        with pytest.raises(ValidationError, match="해외 종목 티커"):
            client.place_overseas_order("123ABC", "NASD", 1, 100.0)
        client.close()

    def test_place_overseas_order_invalid_exchange(self):
        """잘못된 거래소 코드 → ValidationError"""
        client = _make_client()
        with pytest.raises(ValidationError, match="거래소 코드"):
            client.place_overseas_order("AAPL", "KOSPI", 1, 100.0)
        client.close()

    def test_place_overseas_order_invalid_quantity(self):
        """수량 0 이하 → ValidationError"""
        client = _make_client()
        with pytest.raises(ValidationError, match="수량"):
            client.place_overseas_order("AAPL", "NASD", 0, 100.0)
        with pytest.raises(ValidationError, match="수량"):
            client.place_overseas_order("AAPL", "NASD", -1, 100.0)
        client.close()

    def test_place_overseas_order_invalid_price(self):
        """가격 0 이하 → ValidationError"""
        client = _make_client()
        with pytest.raises(ValidationError, match="가격"):
            client.place_overseas_order("AAPL", "NASD", 1, 0)
        with pytest.raises(ValidationError, match="가격"):
            client.place_overseas_order("AAPL", "NASD", 1, -10.0)
        client.close()

    def test_place_overseas_order_api_failure(self, hashkey_response):
        """주문 API 실패 → OrderError"""
        client = _make_client()

        mock_hash_resp = _mock_response(200, hashkey_response)
        error_resp = {
            "rt_cd": "1",
            "msg_cd": "APBK0919",
            "msg1": "주문 가능 수량을 초과하였습니다.",
        }
        mock_order_resp = _mock_response(200, error_resp)

        with patch.object(
            client._client, "post", side_effect=[mock_hash_resp, mock_order_resp]
        ):
            with pytest.raises(OrderError):
                client.place_overseas_order("AAPL", "NASD", 1, 185.50)
        client.close()

    def test_place_overseas_order_decimal_price(self, overseas_order_response, hashkey_response):
        """소수점 가격 정상 처리"""
        client = _make_client()

        mock_hash_resp = _mock_response(200, hashkey_response)
        mock_order_resp = _mock_response(200, overseas_order_response)

        with patch.object(
            client._client, "post", side_effect=[mock_hash_resp, mock_order_resp]
        ) as mock_post:
            client.place_overseas_order("AAPL", "NASD", 1, 185.99)

        order_body = mock_post.call_args_list[1].kwargs["json"]
        assert order_body["OVRS_ORD_UNPR"] == "185.99"
        client.close()


# ───────────────────── Overseas Balance Tests ─────────────────────


class TestGetOverseasBalance:
    """해외주식 잔고 조회 테스트"""

    @pytest.fixture
    def overseas_balance_response(self):
        return {
            "rt_cd": "0",
            "msg_cd": "MCA00000",
            "msg1": "정상처리 되었습니다.",
            "output1": [
                {
                    "ovrs_pdno": "AAPL",
                    "ovrs_item_name": "APPLE INC",
                    "ovrs_cblc_qty": "10",
                    "pchs_avg_pric": "175.50",
                    "now_pric2": "185.50",
                    "evlu_pfls_amt": "100.00",
                    "evlu_pfls_rt": "5.70",
                },
            ],
            "output2": {
                "frcr_pchs_amt1": "1755.00",
                "ovrs_tot_pfls": "100.00",
                "tot_evlu_pfls_amt": "100.00",
            },
        }

    def test_get_overseas_balance_success(self, overseas_balance_response):
        """해외 잔고 정상 조회"""
        client = _make_client()
        mock_resp = _mock_response(200, overseas_balance_response)

        with patch.object(client._client, "get", return_value=mock_resp):
            result = client.get_overseas_balance()

        assert len(result["holdings"]) == 1
        assert result["holdings"][0]["ovrs_pdno"] == "AAPL"
        assert result["summary"]["frcr_pchs_amt1"] == "1755.00"
        client.close()

    def test_get_overseas_balance_empty(self):
        """해외 보유 종목 없는 경우"""
        client = _make_client()
        empty_resp = {
            "rt_cd": "0",
            "msg_cd": "MCA00000",
            "msg1": "정상처리 되었습니다.",
            "output1": [],
            "output2": {},
        }
        mock_resp = _mock_response(200, empty_resp)

        with patch.object(client._client, "get", return_value=mock_resp):
            result = client.get_overseas_balance()

        assert result["holdings"] == []
        assert result["summary"] == {}
        client.close()

    def test_get_overseas_balance_uses_correct_tr_id(self, overseas_balance_response):
        """모의투자/실전투자 tr_id 확인"""
        # 모의투자
        client_mock = _make_client(mock=True)
        mock_resp = _mock_response(200, overseas_balance_response)
        with patch.object(client_mock._client, "get", return_value=mock_resp) as mock_get:
            client_mock.get_overseas_balance()
        assert mock_get.call_args.kwargs["headers"]["tr_id"] == TR_ID_OVERSEAS_BALANCE[0]
        client_mock.close()

        # 실전투자
        client_prod = _make_client(mock=False)
        with patch.object(client_prod._client, "get", return_value=mock_resp) as mock_get:
            client_prod.get_overseas_balance()
        assert mock_get.call_args.kwargs["headers"]["tr_id"] == TR_ID_OVERSEAS_BALANCE[1]
        client_prod.close()

    def test_get_overseas_balance_api_error(self):
        """해외 잔고 조회 API 에러"""
        client = _make_client()
        error_resp = {
            "rt_cd": "1",
            "msg_cd": "EGW00123",
            "msg1": "기간이 만료된 token 입니다.",
        }
        mock_resp = _mock_response(200, error_resp)
        with patch.object(client._client, "get", return_value=mock_resp):
            with pytest.raises(BrokerError, match="기간이 만료된 token"):
                client.get_overseas_balance()
        client.close()

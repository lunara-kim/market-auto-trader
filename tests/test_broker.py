"""
KISClient 테스트

모든 외부 API 호출은 모킹하여 테스트합니다.
실제 한투 API 키 없이도 전체 로직을 검증할 수 있습니다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.broker.kis_client import (
    BASE_URL_MOCK,
    BASE_URL_PROD,
    KISClient,
    MIN_REQUEST_INTERVAL,
    ORD_DVSN_LIMIT,
    ORD_DVSN_MARKET,
    TR_ID_BALANCE,
    TR_ID_BUY,
    TR_ID_PRICE,
    TR_ID_SELL,
)
from src.exceptions import BrokerAuthError, BrokerError, OrderError, ValidationError


# ───────────────────── Fixtures ─────────────────────


MOCK_APP_KEY = "test_app_key_12345"
MOCK_APP_SECRET = "test_app_secret_67890"
MOCK_ACCOUNT = "12345678-01"

# httpx mock 응답 생성 헬퍼
DUMMY_REQUEST = httpx.Request("GET", "http://test")

def _mock_response(status: int = 200, json_data: dict | None = None) -> httpx.Response:
    """request 속성이 설정된 mock Response 생성"""
    resp = httpx.Response(status, json=json_data or {}, request=DUMMY_REQUEST)
    return resp


@pytest.fixture
def mock_token_response():
    """토큰 발급 성공 응답"""
    expired = (datetime.now(timezone.utc) + timedelta(hours=24)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    return {
        "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.test_token",
        "access_token_token_expired": expired,
        "token_type": "Bearer",
        "expires_in": 86400,
    }


@pytest.fixture
def mock_price_response():
    """시세 조회 성공 응답"""
    return {
        "rt_cd": "0",
        "msg_cd": "MCA00000",
        "msg1": "정상처리 되었습니다.",
        "output": {
            "stck_prpr": "72300",
            "prdy_vrss": "300",
            "prdy_ctrt": "0.42",
            "acml_vol": "12345678",
            "acml_tr_pbmn": "893456789012",
            "stck_oprc": "72000",
            "stck_hgpr": "72500",
            "stck_lwpr": "71800",
            "stck_shrn_iscd": "005930",
            "hts_kor_isnm": "삼성전자",
        },
    }


@pytest.fixture
def mock_order_response():
    """주문 성공 응답"""
    return {
        "rt_cd": "0",
        "msg_cd": "APBK0013",
        "msg1": "주문 전송 완료 되었습니다.",
        "output": {
            "KRX_FWDG_ORD_ORGNO": "91252",
            "ODNO": "0000123456",
            "ORD_TMD": "131500",
        },
    }


@pytest.fixture
def mock_balance_response():
    """잔고 조회 성공 응답"""
    return {
        "rt_cd": "0",
        "msg_cd": "MCA00000",
        "msg1": "정상처리 되었습니다.",
        "output1": [
            {
                "pdno": "005930",
                "prdt_name": "삼성전자",
                "hldg_qty": "10",
                "pchs_avg_pric": "71000.0000",
                "prpr": "72300",
                "evlu_pfls_amt": "13000",
                "evlu_pfls_rt": "1.83",
            },
            {
                "pdno": "035720",
                "prdt_name": "카카오",
                "hldg_qty": "5",
                "pchs_avg_pric": "55000.0000",
                "prpr": "54000",
                "evlu_pfls_amt": "-5000",
                "evlu_pfls_rt": "-1.82",
            },
        ],
        "output2": [
            {
                "dnca_tot_amt": "5000000",
                "tot_evlu_amt": "6000000",
                "pchs_amt_smtl_amt": "985000",
                "evlu_amt_smtl_amt": "993000",
                "evlu_pfls_smtl_amt": "8000",
                "nass_amt": "5993000",
            }
        ],
    }


@pytest.fixture
def mock_hashkey_response():
    """해시키 발급 성공 응답"""
    return {"HASH": "abc123hashkey456"}


# ───────────────────── Initialization Tests ─────────────────────


class TestKISClientInit:
    """KISClient 초기화 테스트"""

    def test_init_mock_mode(self):
        """모의투자 모드 초기화"""
        client = KISClient(MOCK_APP_KEY, MOCK_APP_SECRET, MOCK_ACCOUNT, mock=True)
        assert client.mock is True
        assert client.base_url == BASE_URL_MOCK
        assert client.cano == "12345678"
        assert client.acnt_prdt_cd == "01"
        assert client._access_token is None
        client.close()

    def test_init_prod_mode(self):
        """실전투자 모드 초기화"""
        client = KISClient(MOCK_APP_KEY, MOCK_APP_SECRET, MOCK_ACCOUNT, mock=False)
        assert client.mock is False
        assert client.base_url == BASE_URL_PROD
        client.close()

    def test_init_empty_app_key_raises(self):
        """빈 app_key → ValidationError"""
        with pytest.raises(ValidationError, match="app_key.*필수"):
            KISClient("", MOCK_APP_SECRET, MOCK_ACCOUNT)

    def test_init_empty_app_secret_raises(self):
        """빈 app_secret → ValidationError"""
        with pytest.raises(ValidationError, match="app_key.*필수"):
            KISClient(MOCK_APP_KEY, "", MOCK_ACCOUNT)

    def test_init_invalid_account_format_raises(self):
        """잘못된 계좌번호 형식 → ValidationError"""
        with pytest.raises(ValidationError, match="계좌번호"):
            KISClient(MOCK_APP_KEY, MOCK_APP_SECRET, "12345678")

    def test_context_manager(self):
        """with 문으로 사용 가능"""
        with KISClient(MOCK_APP_KEY, MOCK_APP_SECRET, MOCK_ACCOUNT) as client:
            assert client.mock is True


# ───────────────────── Token Tests ─────────────────────


class TestTokenManagement:
    """토큰 발급/갱신 테스트"""

    def test_issue_token_success(self, mock_token_response):
        """토큰 정상 발급"""
        client = KISClient(MOCK_APP_KEY, MOCK_APP_SECRET, MOCK_ACCOUNT)

        mock_resp = _mock_response(200, mock_token_response)
        with patch.object(client._client, "post", return_value=mock_resp):
            token = client.access_token

        assert token == mock_token_response["access_token"]
        assert client._access_token is not None
        assert client._token_expired_at is not None
        client.close()

    def test_token_reuse_when_valid(self, mock_token_response):
        """유효한 토큰은 재사용"""
        client = KISClient(MOCK_APP_KEY, MOCK_APP_SECRET, MOCK_ACCOUNT)
        client._access_token = "cached_token"
        client._token_expired_at = datetime.now(timezone.utc) + timedelta(hours=1)

        # post가 호출되지 않아야 함
        with patch.object(client._client, "post") as mock_post:
            token = client.access_token
            mock_post.assert_not_called()

        assert token == "cached_token"
        client.close()

    def test_token_refresh_when_expired(self, mock_token_response):
        """만료된 토큰 → 자동 재발급"""
        client = KISClient(MOCK_APP_KEY, MOCK_APP_SECRET, MOCK_ACCOUNT)
        client._access_token = "old_token"
        client._token_expired_at = datetime.now(timezone.utc) - timedelta(hours=1)

        mock_resp = _mock_response(200, mock_token_response)
        with patch.object(client._client, "post", return_value=mock_resp):
            token = client.access_token

        assert token == mock_token_response["access_token"]
        assert token != "old_token"
        client.close()

    def test_token_issue_failure(self):
        """토큰 발급 실패 → BrokerAuthError"""
        client = KISClient(MOCK_APP_KEY, MOCK_APP_SECRET, MOCK_ACCOUNT)

        mock_resp = httpx.Response(
            401,
            json={"error": "invalid_client"},
            request=httpx.Request("POST", "http://test/oauth2/tokenP"),
        )
        with patch.object(
            client._client,
            "post",
            side_effect=httpx.HTTPStatusError(
                "401", request=mock_resp.request, response=mock_resp
            ),
        ):
            with pytest.raises(BrokerAuthError, match="토큰 발급 실패"):
                _ = client.access_token
        client.close()

    def test_token_network_error(self):
        """토큰 발급 네트워크 오류 → BrokerError"""
        client = KISClient(MOCK_APP_KEY, MOCK_APP_SECRET, MOCK_ACCOUNT)

        with patch.object(
            client._client,
            "post",
            side_effect=httpx.ConnectError("Connection refused"),
        ):
            with pytest.raises(BrokerError, match="네트워크 오류"):
                _ = client.access_token
        client.close()


# ───────────────────── Price Tests ─────────────────────


class TestGetPrice:
    """시세 조회 테스트"""

    def _make_client(self):
        """토큰이 세팅된 클라이언트 생성"""
        client = KISClient(MOCK_APP_KEY, MOCK_APP_SECRET, MOCK_ACCOUNT)
        client._access_token = "test_token"
        client._token_expired_at = datetime.now(timezone.utc) + timedelta(hours=1)
        return client

    def test_get_price_success(self, mock_price_response):
        """시세 정상 조회"""
        client = self._make_client()

        mock_resp = _mock_response(200, mock_price_response)
        with patch.object(client._client, "get", return_value=mock_resp):
            result = client.get_price("005930")

        assert result["stck_prpr"] == "72300"
        assert result["prdy_vrss"] == "300"
        assert result["prdy_ctrt"] == "0.42"
        assert result["acml_vol"] == "12345678"
        client.close()

    def test_get_price_invalid_code(self):
        """잘못된 종목코드 → ValidationError"""
        client = self._make_client()
        with pytest.raises(ValidationError, match="종목 코드"):
            client.get_price("12345")  # 5자리
        with pytest.raises(ValidationError, match="종목 코드"):
            client.get_price("")
        client.close()

    def test_get_price_api_error(self):
        """API 에러 응답 처리"""
        client = self._make_client()

        error_resp = {
            "rt_cd": "1",
            "msg_cd": "EGW00123",
            "msg1": "기간이 만료된 token 입니다.",
        }
        mock_resp = _mock_response(200, error_resp)
        with patch.object(client._client, "get", return_value=mock_resp):
            with pytest.raises(BrokerError, match="기간이 만료된 token"):
                client.get_price("005930")
        client.close()

    def test_get_price_passes_correct_params(self, mock_price_response):
        """시세 조회 시 올바른 파라미터 전달 확인"""
        client = self._make_client()

        mock_resp = _mock_response(200, mock_price_response)
        with patch.object(client._client, "get", return_value=mock_resp) as mock_get:
            client.get_price("035720")

        call_kwargs = mock_get.call_args
        assert call_kwargs.kwargs["params"]["FID_COND_MRKT_DIV_CODE"] == "J"
        assert call_kwargs.kwargs["params"]["FID_INPUT_ISCD"] == "035720"
        assert TR_ID_PRICE in call_kwargs.kwargs["headers"]["tr_id"]
        client.close()


# ───────────────────── Order Tests ─────────────────────


class TestPlaceOrder:
    """주문 테스트"""

    def _make_client(self, mock: bool = True):
        """토큰이 세팅된 클라이언트 생성"""
        client = KISClient(
            MOCK_APP_KEY, MOCK_APP_SECRET, MOCK_ACCOUNT, mock=mock
        )
        client._access_token = "test_token"
        client._token_expired_at = datetime.now(timezone.utc) + timedelta(hours=1)
        return client

    def test_buy_market_order(self, mock_order_response, mock_hashkey_response):
        """시장가 매수 주문"""
        client = self._make_client()

        mock_hash_resp = _mock_response(200, mock_hashkey_response)
        mock_order_resp = _mock_response(200, mock_order_response)

        with patch.object(
            client._client,
            "post",
            side_effect=[mock_hash_resp, mock_order_resp],
        ):
            result = client.place_order("005930", "buy", 10)

        assert result["ODNO"] == "0000123456"
        assert result["ORD_TMD"] == "131500"
        client.close()

    def test_sell_limit_order(self, mock_order_response, mock_hashkey_response):
        """지정가 매도 주문"""
        client = self._make_client()

        mock_hash_resp = _mock_response(200, mock_hashkey_response)
        mock_order_resp = _mock_response(200, mock_order_response)

        with patch.object(
            client._client,
            "post",
            side_effect=[mock_hash_resp, mock_order_resp],
        ) as mock_post:
            result = client.place_order("005930", "sell", 5, price=73000)

        # 두 번째 호출 (주문)의 body 확인
        order_call = mock_post.call_args_list[1]
        order_body = order_call.kwargs["json"]
        assert order_body["ORD_DVSN"] == ORD_DVSN_LIMIT
        assert order_body["ORD_UNPR"] == "73000"
        assert order_body["PDNO"] == "005930"
        assert order_body["ORD_QTY"] == "5"
        client.close()

    def test_buy_uses_mock_tr_id(self, mock_order_response, mock_hashkey_response):
        """모의투자 매수 → VTTC0802U"""
        client = self._make_client(mock=True)

        mock_hash_resp = _mock_response(200, mock_hashkey_response)
        mock_order_resp = _mock_response(200, mock_order_response)

        with patch.object(
            client._client,
            "post",
            side_effect=[mock_hash_resp, mock_order_resp],
        ) as mock_post:
            client.place_order("005930", "buy", 1)

        order_call = mock_post.call_args_list[1]
        assert order_call.kwargs["headers"]["tr_id"] == TR_ID_BUY[0]
        client.close()

    def test_sell_uses_prod_tr_id(self, mock_order_response, mock_hashkey_response):
        """실전투자 매도 → TTTC0801U"""
        client = self._make_client(mock=False)

        mock_hash_resp = _mock_response(200, mock_hashkey_response)
        mock_order_resp = _mock_response(200, mock_order_response)

        with patch.object(
            client._client,
            "post",
            side_effect=[mock_hash_resp, mock_order_resp],
        ) as mock_post:
            client.place_order("005930", "sell", 1)

        order_call = mock_post.call_args_list[1]
        assert order_call.kwargs["headers"]["tr_id"] == TR_ID_SELL[1]
        client.close()

    def test_order_invalid_stock_code(self):
        """잘못된 종목코드 → ValidationError"""
        client = self._make_client()
        with pytest.raises(ValidationError, match="종목 코드"):
            client.place_order("123", "buy", 10)
        client.close()

    def test_order_invalid_order_type(self):
        """잘못된 주문유형 → ValidationError"""
        client = self._make_client()
        with pytest.raises(ValidationError, match="order_type"):
            client.place_order("005930", "hold", 10)
        client.close()

    def test_order_invalid_quantity(self):
        """수량 0 이하 → ValidationError"""
        client = self._make_client()
        with pytest.raises(ValidationError, match="수량"):
            client.place_order("005930", "buy", 0)
        with pytest.raises(ValidationError, match="수량"):
            client.place_order("005930", "buy", -1)
        client.close()

    def test_order_negative_price(self):
        """음수 가격 → ValidationError"""
        client = self._make_client()
        with pytest.raises(ValidationError, match="가격"):
            client.place_order("005930", "buy", 10, price=-100)
        client.close()

    def test_market_order_uses_correct_dvsn(
        self, mock_order_response, mock_hashkey_response
    ):
        """시장가 주문 → ORD_DVSN=01, ORD_UNPR=0"""
        client = self._make_client()

        mock_hash_resp = _mock_response(200, mock_hashkey_response)
        mock_order_resp = _mock_response(200, mock_order_response)

        with patch.object(
            client._client,
            "post",
            side_effect=[mock_hash_resp, mock_order_resp],
        ) as mock_post:
            client.place_order("005930", "buy", 10)

        order_body = mock_post.call_args_list[1].kwargs["json"]
        assert order_body["ORD_DVSN"] == ORD_DVSN_MARKET
        assert order_body["ORD_UNPR"] == "0"
        client.close()


# ───────────────────── Balance Tests ─────────────────────


class TestGetBalance:
    """잔고 조회 테스트"""

    def _make_client(self, mock: bool = True):
        client = KISClient(
            MOCK_APP_KEY, MOCK_APP_SECRET, MOCK_ACCOUNT, mock=mock
        )
        client._access_token = "test_token"
        client._token_expired_at = datetime.now(timezone.utc) + timedelta(hours=1)
        return client

    def test_get_balance_success(self, mock_balance_response):
        """잔고 정상 조회"""
        client = self._make_client()

        mock_resp = _mock_response(200, mock_balance_response)
        with patch.object(client._client, "get", return_value=mock_resp):
            result = client.get_balance()

        assert len(result["holdings"]) == 2
        assert result["holdings"][0]["pdno"] == "005930"
        assert result["holdings"][1]["prdt_name"] == "카카오"
        assert result["summary"]["dnca_tot_amt"] == "5000000"
        assert result["summary"]["nass_amt"] == "5993000"
        client.close()

    def test_get_balance_empty_holdings(self):
        """보유 종목 없는 경우"""
        client = self._make_client()

        empty_resp = {
            "rt_cd": "0",
            "msg_cd": "MCA00000",
            "msg1": "정상처리 되었습니다.",
            "output1": [],
            "output2": [{"dnca_tot_amt": "10000000", "nass_amt": "10000000"}],
        }
        mock_resp = _mock_response(200, empty_resp)
        with patch.object(client._client, "get", return_value=mock_resp):
            result = client.get_balance()

        assert result["holdings"] == []
        assert result["summary"]["dnca_tot_amt"] == "10000000"
        client.close()

    def test_get_balance_uses_correct_tr_id(self, mock_balance_response):
        """모의투자 → VTTC8434R, 실전 → TTTC8434R"""
        # 모의투자
        client_mock = self._make_client(mock=True)
        mock_resp = _mock_response(200, mock_balance_response)
        with patch.object(
            client_mock._client, "get", return_value=mock_resp
        ) as mock_get:
            client_mock.get_balance()
        assert mock_get.call_args.kwargs["headers"]["tr_id"] == TR_ID_BALANCE[0]
        client_mock.close()

        # 실전투자
        client_prod = self._make_client(mock=False)
        with patch.object(
            client_prod._client, "get", return_value=mock_resp
        ) as mock_get:
            client_prod.get_balance()
        assert mock_get.call_args.kwargs["headers"]["tr_id"] == TR_ID_BALANCE[1]
        client_prod.close()

    def test_get_balance_api_error(self):
        """잔고 조회 API 에러"""
        client = self._make_client()

        error_resp = {
            "rt_cd": "1",
            "msg_cd": "EGW00123",
            "msg1": "기간이 만료된 token 입니다.",
        }
        mock_resp = _mock_response(200, error_resp)
        with patch.object(client._client, "get", return_value=mock_resp):
            with pytest.raises(BrokerError, match="기간이 만료된 token"):
                client.get_balance()
        client.close()


# ───────────────────── Hashkey Tests ─────────────────────


class TestHashkey:
    """해시키 테스트"""

    def test_hashkey_success(self, mock_hashkey_response):
        """해시키 정상 발급"""
        client = KISClient(MOCK_APP_KEY, MOCK_APP_SECRET, MOCK_ACCOUNT)

        mock_resp = _mock_response(200, mock_hashkey_response)
        with patch.object(client._client, "post", return_value=mock_resp):
            hashkey = client._get_hashkey({"test": "body"})

        assert hashkey == "abc123hashkey456"
        client.close()

    def test_hashkey_failure(self):
        """해시키 발급 실패 → BrokerError"""
        client = KISClient(MOCK_APP_KEY, MOCK_APP_SECRET, MOCK_ACCOUNT)

        with patch.object(
            client._client,
            "post",
            side_effect=httpx.ConnectError("Connection refused"),
        ):
            with pytest.raises(BrokerError, match="해시키 발급 실패"):
                client._get_hashkey({"test": "body"})
        client.close()


# ───────────────────── Error Handling Tests ─────────────────────


class TestErrorHandling:
    """에러 핸들링 테스트"""

    def _make_client(self):
        client = KISClient(MOCK_APP_KEY, MOCK_APP_SECRET, MOCK_ACCOUNT)
        client._access_token = "test_token"
        client._token_expired_at = datetime.now(timezone.utc) + timedelta(hours=1)
        return client

    def test_401_clears_token_and_raises_auth_error(self):
        """401 응답 → 토큰 초기화 + BrokerAuthError"""
        client = self._make_client()

        mock_resp = httpx.Response(
            401,
            json={"error": "expired_token"},
            request=httpx.Request(
                "GET", "http://test/uapi/domestic-stock/v1/quotations/inquire-price"
            ),
        )
        with patch.object(
            client._client,
            "get",
            side_effect=httpx.HTTPStatusError(
                "401", request=mock_resp.request, response=mock_resp
            ),
        ):
            with pytest.raises(BrokerAuthError, match="인증 실패"):
                client.get_price("005930")

        assert client._access_token is None
        client.close()

    def test_500_raises_broker_error(self):
        """500 응답 → BrokerError"""
        client = self._make_client()

        mock_resp = httpx.Response(
            500,
            json={"error": "internal_server_error"},
            request=httpx.Request(
                "GET", "http://test/uapi/domestic-stock/v1/quotations/inquire-price"
            ),
        )
        with patch.object(
            client._client,
            "get",
            side_effect=httpx.HTTPStatusError(
                "500", request=mock_resp.request, response=mock_resp
            ),
        ):
            with pytest.raises(BrokerError, match="HTTP 오류"):
                client.get_price("005930")
        client.close()

    def test_network_error_raises_broker_error(self):
        """네트워크 오류 → BrokerError"""
        client = self._make_client()

        with patch.object(
            client._client,
            "get",
            side_effect=httpx.ConnectError("Connection refused"),
        ):
            with pytest.raises(BrokerError, match="네트워크 오류"):
                client.get_price("005930")
        client.close()

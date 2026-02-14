"""
MarketDataCollector 테스트

KISClient의 내부 메서드를 모킹하여 외부 API 의존성 없이 테스트합니다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from src.broker.kis_client import KISClient
from src.data.collector import (
    PATH_DAILY_CHART,
    PATH_MINUTE_CHART,
    TR_ID_DAILY_CHART,
    TR_ID_MINUTE_CHART,
    VALID_PERIODS,
    MarketDataCollector,
    _safe_int,
)
from src.exceptions import DataCollectionError, ValidationError


# ───────────────────── Fixtures ─────────────────────

MOCK_APP_KEY = "test_app_key_12345"
MOCK_APP_SECRET = "test_app_secret_67890"
MOCK_ACCOUNT = "12345678-01"


@pytest.fixture
def kis_client():
    """토큰이 세팅된 KISClient"""
    client = KISClient(MOCK_APP_KEY, MOCK_APP_SECRET, MOCK_ACCOUNT)
    client._access_token = "test_token"
    client._token_expired_at = datetime.now(timezone.utc) + timedelta(hours=1)
    return client


@pytest.fixture
def collector(kis_client):
    """MarketDataCollector 인스턴스"""
    return MarketDataCollector(kis_client)


@pytest.fixture
def mock_daily_response():
    """일봉 조회 성공 응답"""
    return {
        "rt_cd": "0",
        "msg_cd": "MCA00000",
        "msg1": "정상처리 되었습니다.",
        "output1": {
            "stck_shrn_iscd": "005930",
            "hts_kor_isnm": "삼성전자",
        },
        "output2": [
            {
                "stck_bsop_date": "20260212",
                "stck_oprc": "72000",
                "stck_hgpr": "72500",
                "stck_lwpr": "71800",
                "stck_clpr": "72300",
                "acml_vol": "12345678",
                "acml_tr_pbmn": "893456789012",
                "prdy_vrss": "300",
                "prdy_vrss_sign": "2",
            },
            {
                "stck_bsop_date": "20260211",
                "stck_oprc": "71500",
                "stck_hgpr": "72200",
                "stck_lwpr": "71300",
                "stck_clpr": "72000",
                "acml_vol": "11234567",
                "acml_tr_pbmn": "810456789012",
                "prdy_vrss": "500",
                "prdy_vrss_sign": "2",
            },
            {
                "stck_bsop_date": "20260210",
                "stck_oprc": "71000",
                "stck_hgpr": "71800",
                "stck_lwpr": "70800",
                "stck_clpr": "71500",
                "acml_vol": "10234567",
                "acml_tr_pbmn": "730456789012",
                "prdy_vrss": "-200",
                "prdy_vrss_sign": "5",
            },
        ],
    }


@pytest.fixture
def mock_minute_response():
    """분봉 조회 성공 응답"""
    return {
        "rt_cd": "0",
        "msg_cd": "MCA00000",
        "msg1": "정상처리 되었습니다.",
        "output1": {
            "stck_shrn_iscd": "005930",
            "hts_kor_isnm": "삼성전자",
            "stck_prpr": "72300",
        },
        "output2": [
            {
                "stck_cntg_hour": "153000",
                "stck_prpr": "72300",
                "stck_oprc": "72200",
                "stck_hgpr": "72400",
                "stck_lwpr": "72100",
                "cntg_vol": "45678",
                "acml_vol": "12345678",
                "acml_tr_pbmn": "893456789012",
            },
            {
                "stck_cntg_hour": "152900",
                "stck_prpr": "72200",
                "stck_oprc": "72100",
                "stck_hgpr": "72300",
                "stck_lwpr": "72000",
                "cntg_vol": "34567",
                "acml_vol": "12300000",
                "acml_tr_pbmn": "890000000000",
            },
        ],
    }


@pytest.fixture
def mock_price_response():
    """현재가 조회 응답"""
    return {
        "stck_prpr": "72300",
        "prdy_vrss": "300",
        "prdy_ctrt": "0.42",
        "acml_vol": "12345678",
    }


# ───────────────────── Initialization Tests ─────────────────────


class TestCollectorInit:
    """MarketDataCollector 초기화 테스트"""

    def test_init_with_kis_client(self, kis_client):
        """정상 초기화"""
        collector = MarketDataCollector(kis_client)
        assert collector._client is kis_client

    def test_init_invalid_client_type(self):
        """잘못된 클라이언트 타입 → ValidationError"""
        with pytest.raises(ValidationError, match="KISClient"):
            MarketDataCollector("not_a_client")  # type: ignore

    def test_init_none_client(self):
        """None 클라이언트 → ValidationError"""
        with pytest.raises(ValidationError, match="KISClient"):
            MarketDataCollector(None)  # type: ignore


# ───────────────────── Daily Prices Tests ─────────────────────


class TestFetchDailyPrices:
    """일봉 데이터 조회 테스트"""

    def test_fetch_daily_success(self, collector, mock_daily_response):
        """일봉 정상 조회"""
        with patch.object(
            collector._client, "_request_get", return_value=mock_daily_response
        ):
            result = collector.fetch_daily_prices("005930", "20260210", "20260212")

        assert len(result) == 3
        assert result[0]["stck_bsop_date"] == "20260212"
        assert result[0]["stck_clpr"] == "72300"
        assert result[2]["stck_bsop_date"] == "20260210"

    def test_fetch_daily_passes_correct_params(self, collector, mock_daily_response):
        """올바른 파라미터 전달 확인"""
        with patch.object(
            collector._client, "_request_get", return_value=mock_daily_response
        ) as mock_get:
            collector.fetch_daily_prices(
                "035720", "20260101", "20260212", period="W", adjusted=False
            )

        call_kwargs = mock_get.call_args
        assert call_kwargs.kwargs["path"] == PATH_DAILY_CHART
        assert call_kwargs.kwargs["tr_id"] == TR_ID_DAILY_CHART
        params = call_kwargs.kwargs["params"]
        assert params["FID_COND_MRKT_DIV_CODE"] == "J"
        assert params["FID_INPUT_ISCD"] == "035720"
        assert params["FID_INPUT_DATE_1"] == "20260101"
        assert params["FID_INPUT_DATE_2"] == "20260212"
        assert params["FID_PERIOD_DIV_CODE"] == "W"
        assert params["FID_ORG_ADJ_PRC"] == "0"  # adjusted=False

    def test_fetch_daily_adjusted_default(self, collector, mock_daily_response):
        """수정주가 기본 적용"""
        with patch.object(
            collector._client, "_request_get", return_value=mock_daily_response
        ) as mock_get:
            collector.fetch_daily_prices("005930", "20260210", "20260212")

        params = mock_get.call_args.kwargs["params"]
        assert params["FID_ORG_ADJ_PRC"] == "1"

    def test_fetch_daily_empty_response(self, collector):
        """빈 응답 처리"""
        empty_resp = {
            "rt_cd": "0",
            "msg_cd": "MCA00000",
            "msg1": "정상처리 되었습니다.",
            "output2": [],
        }
        with patch.object(
            collector._client, "_request_get", return_value=empty_resp
        ):
            result = collector.fetch_daily_prices("005930", "20260210", "20260212")

        assert result == []

    def test_fetch_daily_filters_empty_records(self, collector):
        """빈 레코드 필터링"""
        resp_with_empty = {
            "rt_cd": "0",
            "msg_cd": "MCA00000",
            "msg1": "정상처리 되었습니다.",
            "output2": [
                {"stck_bsop_date": "20260212", "stck_clpr": "72300"},
                {"stck_bsop_date": "", "stck_clpr": ""},  # 빈 레코드
                {},  # 완전히 빈 레코드
            ],
        }
        with patch.object(
            collector._client, "_request_get", return_value=resp_with_empty
        ):
            result = collector.fetch_daily_prices("005930", "20260210", "20260212")

        assert len(result) == 1
        assert result[0]["stck_bsop_date"] == "20260212"

    def test_fetch_daily_invalid_stock_code(self, collector):
        """잘못된 종목코드 → ValidationError"""
        with pytest.raises(ValidationError, match="종목 코드"):
            collector.fetch_daily_prices("12345", "20260210", "20260212")
        with pytest.raises(ValidationError, match="종목 코드"):
            collector.fetch_daily_prices("", "20260210", "20260212")
        with pytest.raises(ValidationError, match="종목 코드"):
            collector.fetch_daily_prices("abcdef", "20260210", "20260212")

    def test_fetch_daily_invalid_date(self, collector):
        """잘못된 날짜 → ValidationError"""
        with pytest.raises(ValidationError, match="start_date"):
            collector.fetch_daily_prices("005930", "2026021", "20260212")
        with pytest.raises(ValidationError, match="end_date"):
            collector.fetch_daily_prices("005930", "20260210", "20261301")

    def test_fetch_daily_invalid_period(self, collector):
        """잘못된 기간 코드 → ValidationError"""
        with pytest.raises(ValidationError, match="period"):
            collector.fetch_daily_prices(
                "005930", "20260210", "20260212", period="X"
            )

    def test_fetch_daily_all_periods(self, collector, mock_daily_response):
        """모든 유효 기간 코드 테스트"""
        for period in VALID_PERIODS:
            with patch.object(
                collector._client, "_request_get", return_value=mock_daily_response
            ):
                result = collector.fetch_daily_prices(
                    "005930", "20260210", "20260212", period=period
                )
            assert isinstance(result, list)

    def test_fetch_daily_api_error(self, collector):
        """API 오류 → DataCollectionError"""
        with patch.object(
            collector._client,
            "_request_get",
            side_effect=Exception("네트워크 오류"),
        ):
            with pytest.raises(DataCollectionError, match="일봉 데이터 수집 실패"):
                collector.fetch_daily_prices("005930", "20260210", "20260212")


# ───────────────────── Minute Prices Tests ─────────────────────


class TestFetchMinutePrices:
    """분봉 데이터 조회 테스트"""

    def test_fetch_minute_success(self, collector, mock_minute_response):
        """분봉 정상 조회"""
        with patch.object(
            collector._client, "_request_get", return_value=mock_minute_response
        ):
            result = collector.fetch_minute_prices("005930")

        assert len(result) == 2
        assert result[0]["stck_cntg_hour"] == "153000"
        assert result[0]["stck_prpr"] == "72300"

    def test_fetch_minute_passes_correct_params(self, collector, mock_minute_response):
        """올바른 파라미터 전달 확인"""
        with patch.object(
            collector._client, "_request_get", return_value=mock_minute_response
        ) as mock_get:
            collector.fetch_minute_prices("005930", hour="130000")

        call_kwargs = mock_get.call_args
        assert call_kwargs.kwargs["path"] == PATH_MINUTE_CHART
        assert call_kwargs.kwargs["tr_id"] == TR_ID_MINUTE_CHART
        params = call_kwargs.kwargs["params"]
        assert params["FID_INPUT_ISCD"] == "005930"
        assert params["FID_INPUT_HOUR_1"] == "130000"
        assert params["FID_PW_DATA_INCU_YN"] == "N"

    def test_fetch_minute_include_premarket(self, collector, mock_minute_response):
        """장전 데이터 포함"""
        with patch.object(
            collector._client, "_request_get", return_value=mock_minute_response
        ) as mock_get:
            collector.fetch_minute_prices(
                "005930", include_premarket=True
            )

        params = mock_get.call_args.kwargs["params"]
        assert params["FID_PW_DATA_INCU_YN"] == "Y"

    def test_fetch_minute_default_hour(self, collector, mock_minute_response):
        """기본 시각 155900"""
        with patch.object(
            collector._client, "_request_get", return_value=mock_minute_response
        ) as mock_get:
            collector.fetch_minute_prices("005930")

        params = mock_get.call_args.kwargs["params"]
        assert params["FID_INPUT_HOUR_1"] == "155900"

    def test_fetch_minute_invalid_stock_code(self, collector):
        """잘못된 종목코드 → ValidationError"""
        with pytest.raises(ValidationError, match="종목 코드"):
            collector.fetch_minute_prices("12345")

    def test_fetch_minute_invalid_hour(self, collector):
        """잘못된 시각 형식 → ValidationError"""
        with pytest.raises(ValidationError, match="hour"):
            collector.fetch_minute_prices("005930", hour="1300")
        with pytest.raises(ValidationError, match="hour"):
            collector.fetch_minute_prices("005930", hour="abcdef")
        with pytest.raises(ValidationError, match="hour"):
            collector.fetch_minute_prices("005930", hour="")

    def test_fetch_minute_empty_response(self, collector):
        """빈 응답 처리"""
        empty_resp = {
            "rt_cd": "0",
            "msg_cd": "MCA00000",
            "msg1": "정상처리 되었습니다.",
            "output2": [],
        }
        with patch.object(
            collector._client, "_request_get", return_value=empty_resp
        ):
            result = collector.fetch_minute_prices("005930")

        assert result == []

    def test_fetch_minute_filters_empty_records(self, collector):
        """빈 레코드 필터링"""
        resp = {
            "rt_cd": "0",
            "msg_cd": "MCA00000",
            "msg1": "정상처리 되었습니다.",
            "output2": [
                {"stck_cntg_hour": "153000", "stck_prpr": "72300"},
                {"stck_cntg_hour": "", "stck_prpr": ""},
                {},
            ],
        }
        with patch.object(
            collector._client, "_request_get", return_value=resp
        ):
            result = collector.fetch_minute_prices("005930")

        assert len(result) == 1

    def test_fetch_minute_api_error(self, collector):
        """API 오류 → DataCollectionError"""
        with patch.object(
            collector._client,
            "_request_get",
            side_effect=Exception("연결 실패"),
        ):
            with pytest.raises(DataCollectionError, match="분봉 데이터 수집 실패"):
                collector.fetch_minute_prices("005930")


# ───────────────────── Current Price Tests ─────────────────────


class TestFetchCurrentPrice:
    """현재가 조회 테스트"""

    def test_fetch_current_price_success(self, collector, mock_price_response):
        """현재가 정상 조회"""
        with patch.object(
            collector._client, "get_price", return_value=mock_price_response
        ):
            result = collector.fetch_current_price("005930")

        assert result["stck_prpr"] == "72300"
        assert result["prdy_ctrt"] == "0.42"

    def test_fetch_current_price_invalid_code(self, collector):
        """잘못된 종목코드 → ValidationError"""
        with pytest.raises(ValidationError, match="종목 코드"):
            collector.fetch_current_price("123")

    def test_fetch_current_price_api_error(self, collector):
        """API 오류 → DataCollectionError"""
        with patch.object(
            collector._client,
            "get_price",
            side_effect=Exception("시세 조회 오류"),
        ):
            with pytest.raises(DataCollectionError, match="현재가 조회 실패"):
                collector.fetch_current_price("005930")


# ───────────────────── fetch_stock_price Tests ─────────────────────


class TestFetchStockPrice:
    """fetch_stock_price (datetime 인터페이스) 테스트"""

    def test_fetch_stock_price_normalizes_data(self, collector, mock_daily_response):
        """데이터 정규화 확인 (한투 필드 → OHLCV)"""
        with patch.object(
            collector._client, "_request_get", return_value=mock_daily_response
        ):
            result = collector.fetch_stock_price(
                "005930",
                datetime(2026, 2, 10),
                datetime(2026, 2, 12),
            )

        assert len(result) == 3
        # 날짜 오름차순 정렬
        assert result[0]["date"] == "2026-02-10"
        assert result[1]["date"] == "2026-02-11"
        assert result[2]["date"] == "2026-02-12"

        # OHLCV 필드 확인
        assert result[2]["open"] == 72000
        assert result[2]["high"] == 72500
        assert result[2]["low"] == 71800
        assert result[2]["close"] == 72300
        assert result[2]["volume"] == 12345678

    def test_fetch_stock_price_date_format(self, collector, mock_daily_response):
        """datetime → YYYYMMDD 변환"""
        with patch.object(
            collector._client, "_request_get", return_value=mock_daily_response
        ) as mock_get:
            collector.fetch_stock_price(
                "005930",
                datetime(2026, 2, 10),
                datetime(2026, 2, 12),
            )

        params = mock_get.call_args.kwargs["params"]
        assert params["FID_INPUT_DATE_1"] == "20260210"
        assert params["FID_INPUT_DATE_2"] == "20260212"

    def test_fetch_stock_price_empty(self, collector):
        """빈 데이터"""
        empty_resp = {
            "rt_cd": "0",
            "msg_cd": "MCA00000",
            "msg1": "정상처리 되었습니다.",
            "output2": [],
        }
        with patch.object(
            collector._client, "_request_get", return_value=empty_resp
        ):
            result = collector.fetch_stock_price(
                "005930",
                datetime(2026, 2, 10),
                datetime(2026, 2, 12),
            )

        assert result == []

    def test_fetch_stock_price_handles_none_values(self, collector):
        """None 값 안전 처리"""
        resp = {
            "rt_cd": "0",
            "msg_cd": "MCA00000",
            "msg1": "정상처리 되었습니다.",
            "output2": [
                {
                    "stck_bsop_date": "20260212",
                    "stck_oprc": None,
                    "stck_hgpr": "",
                    "stck_lwpr": "abc",
                    "stck_clpr": "72300",
                    "acml_vol": None,
                },
            ],
        }
        with patch.object(
            collector._client, "_request_get", return_value=resp
        ):
            result = collector.fetch_stock_price(
                "005930",
                datetime(2026, 2, 12),
                datetime(2026, 2, 12),
            )

        assert len(result) == 1
        assert result[0]["open"] == 0  # None → 0
        assert result[0]["high"] == 0  # "" → 0
        assert result[0]["low"] == 0  # "abc" → 0
        assert result[0]["close"] == 72300
        assert result[0]["volume"] == 0  # None → 0


# ───────────────────── Validation Tests ─────────────────────


class TestValidation:
    """검증 헬퍼 테스트"""

    def test_validate_stock_code_valid(self):
        """유효한 종목코드"""
        # 예외 없이 통과
        MarketDataCollector._validate_stock_code("005930")
        MarketDataCollector._validate_stock_code("035720")

    def test_validate_stock_code_invalid(self):
        """잘못된 종목코드"""
        with pytest.raises(ValidationError):
            MarketDataCollector._validate_stock_code("")
        with pytest.raises(ValidationError):
            MarketDataCollector._validate_stock_code("12345")
        with pytest.raises(ValidationError):
            MarketDataCollector._validate_stock_code("abcdef")
        with pytest.raises(ValidationError):
            MarketDataCollector._validate_stock_code("1234567")

    def test_validate_date_valid(self):
        """유효한 날짜"""
        MarketDataCollector._validate_date("20260212", "test")
        MarketDataCollector._validate_date("20260101", "test")

    def test_validate_date_invalid_format(self):
        """잘못된 날짜 형식"""
        with pytest.raises(ValidationError):
            MarketDataCollector._validate_date("2026021", "test")
        with pytest.raises(ValidationError):
            MarketDataCollector._validate_date("", "test")
        with pytest.raises(ValidationError):
            MarketDataCollector._validate_date("abcdefgh", "test")

    def test_validate_date_invalid_date(self):
        """유효하지 않은 날짜"""
        with pytest.raises(ValidationError):
            MarketDataCollector._validate_date("20261301", "test")  # 13월
        with pytest.raises(ValidationError):
            MarketDataCollector._validate_date("20260230", "test")  # 2월 30일


# ───────────────────── Utility Tests ─────────────────────


class TestSafeInt:
    """_safe_int 유틸리티 테스트"""

    def test_normal_int_string(self):
        assert _safe_int("72300") == 72300

    def test_normal_int(self):
        assert _safe_int(72300) == 72300

    def test_none(self):
        assert _safe_int(None) == 0

    def test_empty_string(self):
        assert _safe_int("") == 0

    def test_non_numeric_string(self):
        assert _safe_int("abc") == 0

    def test_float_string(self):
        """소수점 포함 문자열 → 0 (int 변환 불가)"""
        assert _safe_int("72300.5") == 0

    def test_negative(self):
        assert _safe_int("-300") == -300

    def test_zero(self):
        assert _safe_int("0") == 0
        assert _safe_int(0) == 0

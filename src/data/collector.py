"""
시장 데이터 수집기

한국투자증권 OpenAPI를 활용하여:
- 일봉/주봉/월봉 데이터 수집 (기간별 시세)
- 분봉 데이터 수집 (당일 분봉)
- 현재가 시세 조회

KISClient를 주입받아 API 호출을 위임합니다.

References:
    - https://apiportal.koreainvestment.com
    - 일봉: /uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice
    - 분봉: /uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from src.broker.kis_client import KISClient
from src.exceptions import DataCollectionError, ValidationError
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ───────────────────── Constants ─────────────────────

# 일봉 조회
TR_ID_DAILY_CHART = "FHKST03010100"
PATH_DAILY_CHART = "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"

# 분봉 조회
TR_ID_MINUTE_CHART = "FHKST03010200"
PATH_MINUTE_CHART = "/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"

# 기간 구분 코드
PERIOD_DAY = "D"
PERIOD_WEEK = "W"
PERIOD_MONTH = "M"
PERIOD_YEAR = "Y"

VALID_PERIODS = {PERIOD_DAY, PERIOD_WEEK, PERIOD_MONTH, PERIOD_YEAR}

# 한투 API 일봉 응답 최대 건수 (한 번 요청당)
MAX_DAILY_RECORDS = 100


class MarketDataCollector:
    """시장 데이터 수집기

    KISClient를 사용하여 한국투자증권 OpenAPI에서
    주식 시세 데이터를 수집합니다.

    Usage::

        client = KISClient(app_key, app_secret, account_no)
        collector = MarketDataCollector(client)

        # 일봉 데이터
        daily = collector.fetch_daily_prices("005930", "20260101", "20260212")

        # 분봉 데이터 (당일)
        minute = collector.fetch_minute_prices("005930")
    """

    def __init__(self, kis_client: KISClient) -> None:
        """
        Args:
            kis_client: 한국투자증권 API 클라이언트 인스턴스
        """
        if not isinstance(kis_client, KISClient):
            raise ValidationError(
                "kis_client는 KISClient 인스턴스여야 합니다.",
                detail={"type": type(kis_client).__name__},
            )
        self._client = kis_client
        logger.info("MarketDataCollector 초기화 (KISClient 연동)")

    # ───────────────────── Daily Prices ─────────────────────

    def fetch_daily_prices(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
        *,
        period: str = PERIOD_DAY,
        adjusted: bool = True,
    ) -> list[dict[str, Any]]:
        """
        주식 기간별 시세 조회 (일/주/월/년봉)

        GET /uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice

        Args:
            stock_code: 종목 코드 (예: "005930")
            start_date: 시작일 (YYYYMMDD 형식)
            end_date: 종료일 (YYYYMMDD 형식)
            period: 기간 구분 — "D"(일), "W"(주), "M"(월), "Y"(년)
            adjusted: 수정주가 반영 여부 (기본 True)

        Returns:
            시세 데이터 리스트 (최신 날짜 먼저). 각 항목:
                - stck_bsop_date: 영업일자 (YYYYMMDD)
                - stck_oprc: 시가
                - stck_hgpr: 고가
                - stck_lwpr: 저가
                - stck_clpr: 종가
                - acml_vol: 누적 거래량
                - acml_tr_pbmn: 누적 거래대금
                - prdy_vrss: 전일 대비
                - prdy_vrss_sign: 전일 대비 부호 (1:상한,2:상승,3:보합,4:하한,5:하락)

        Raises:
            ValidationError: 잘못된 파라미터
            DataCollectionError: 데이터 수집 실패
        """
        self._validate_stock_code(stock_code)
        self._validate_date(start_date, "start_date")
        self._validate_date(end_date, "end_date")

        if period not in VALID_PERIODS:
            raise ValidationError(
                f"period는 {VALID_PERIODS} 중 하나여야 합니다.",
                detail={"period": period},
            )

        logger.info(
            "일봉 조회: %s (%s ~ %s, 기간: %s)",
            stock_code,
            start_date,
            end_date,
            period,
        )

        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": stock_code,
            "FID_INPUT_DATE_1": start_date,
            "FID_INPUT_DATE_2": end_date,
            "FID_PERIOD_DIV_CODE": period,
            "FID_ORG_ADJ_PRC": "1" if adjusted else "0",
        }

        try:
            data = self._client._request_get(
                path=PATH_DAILY_CHART,
                tr_id=TR_ID_DAILY_CHART,
                params=params,
            )
        except Exception as e:
            raise DataCollectionError(
                f"일봉 데이터 수집 실패 ({stock_code})",
                detail={"stock_code": stock_code, "error": str(e)},
            ) from e

        records = data.get("output2", [])

        # 빈 레코드 필터링 (한투 API가 빈 dict를 포함할 수 있음)
        records = [r for r in records if r.get("stck_bsop_date")]

        logger.info(
            "일봉 조회 완료: %s — %d건 (%s ~ %s)",
            stock_code,
            len(records),
            records[-1]["stck_bsop_date"] if records else "N/A",
            records[0]["stck_bsop_date"] if records else "N/A",
        )
        return records

    # ───────────────────── Minute Prices ─────────────────────

    def fetch_minute_prices(
        self,
        stock_code: str,
        *,
        hour: str = "155900",
        include_premarket: bool = False,
    ) -> list[dict[str, Any]]:
        """
        주식 당일 분봉 데이터 조회

        GET /uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice

        한 번 호출에 최대 30건. 장 시작(09:00)부터 조회 시점까지의
        분봉을 수집합니다. hour 파라미터로 조회 시점을 지정합니다.

        Args:
            stock_code: 종목 코드 (예: "005930")
            hour: 조회 기준 시각 (HHMMSS 형식, 기본 "155900" = 장 마감)
            include_premarket: 장전 데이터 포함 여부

        Returns:
            분봉 데이터 리스트 (최신 시각 먼저). 각 항목:
                - stck_cntg_hour: 체결 시각 (HHMMSS)
                - stck_prpr: 현재가
                - stck_oprc: 시가
                - stck_hgpr: 고가
                - stck_lwpr: 저가
                - cntg_vol: 체결 거래량
                - acml_vol: 누적 거래량
                - acml_tr_pbmn: 누적 거래대금

        Raises:
            ValidationError: 잘못된 파라미터
            DataCollectionError: 데이터 수집 실패
        """
        self._validate_stock_code(stock_code)

        if not hour or len(hour) != 6 or not hour.isdigit():
            raise ValidationError(
                "hour는 HHMMSS 형식 6자리 숫자여야 합니다.",
                detail={"hour": hour},
            )

        logger.info("분봉 조회: %s (기준시각: %s)", stock_code, hour)

        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": stock_code,
            "FID_INPUT_HOUR_1": hour,
            "FID_ETC_CLS_CODE": "",
            "FID_PW_DATA_INCU_YN": "Y" if include_premarket else "N",
        }

        try:
            data = self._client._request_get(
                path=PATH_MINUTE_CHART,
                tr_id=TR_ID_MINUTE_CHART,
                params=params,
            )
        except Exception as e:
            raise DataCollectionError(
                f"분봉 데이터 수집 실패 ({stock_code})",
                detail={"stock_code": stock_code, "error": str(e)},
            ) from e

        records = data.get("output2", [])

        # 빈 레코드 필터링
        records = [r for r in records if r.get("stck_cntg_hour")]

        logger.info(
            "분봉 조회 완료: %s — %d건",
            stock_code,
            len(records),
        )
        return records

    # ───────────────────── Current Price ─────────────────────

    def fetch_current_price(self, stock_code: str) -> dict[str, Any]:
        """
        주식 현재가 시세 조회 (KISClient.get_price 래퍼)

        Args:
            stock_code: 종목 코드 (예: "005930")

        Returns:
            시세 정보 dict (stck_prpr, prdy_vrss, prdy_ctrt, acml_vol 등)

        Raises:
            DataCollectionError: 시세 조회 실패
        """
        self._validate_stock_code(stock_code)

        try:
            return self._client.get_price(stock_code)
        except Exception as e:
            raise DataCollectionError(
                f"현재가 조회 실패 ({stock_code})",
                detail={"stock_code": stock_code, "error": str(e)},
            ) from e

    # ───────────────────── Convenience: fetch_stock_price ─────────────────────

    def fetch_stock_price(
        self,
        stock_code: str,
        start_date: datetime,
        end_date: datetime,
    ) -> list[dict[str, Any]]:
        """
        주식 가격 데이터 수집 (datetime 인터페이스)

        기존 인터페이스 호환용. 내부적으로 fetch_daily_prices()를 호출합니다.

        Args:
            stock_code: 종목 코드
            start_date: 시작 날짜
            end_date: 종료 날짜

        Returns:
            정규화된 일봉 데이터 리스트. 각 항목:
                - date: 날짜 (YYYY-MM-DD)
                - open: 시가 (int)
                - high: 고가 (int)
                - low: 저가 (int)
                - close: 종가 (int)
                - volume: 거래량 (int)
        """
        start_str = start_date.strftime("%Y%m%d")
        end_str = end_date.strftime("%Y%m%d")

        raw = self.fetch_daily_prices(stock_code, start_str, end_str)

        # 정규화: 한투 API 필드명 → 일반적인 OHLCV 형식
        normalized = []
        for r in raw:
            date_str = r.get("stck_bsop_date", "")
            if len(date_str) == 8:
                formatted_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
            else:
                formatted_date = date_str

            normalized.append({
                "date": formatted_date,
                "open": _safe_int(r.get("stck_oprc")),
                "high": _safe_int(r.get("stck_hgpr")),
                "low": _safe_int(r.get("stck_lwpr")),
                "close": _safe_int(r.get("stck_clpr")),
                "volume": _safe_int(r.get("acml_vol")),
            })

        # 날짜 오름차순 정렬 (한투 API는 최신 먼저 반환)
        normalized.sort(key=lambda x: x["date"])

        logger.info(
            "fetch_stock_price 완료: %s — %d건 (%s ~ %s)",
            stock_code,
            len(normalized),
            normalized[0]["date"] if normalized else "N/A",
            normalized[-1]["date"] if normalized else "N/A",
        )
        return normalized

    # ───────────────────── Validation Helpers ─────────────────────

    @staticmethod
    def _validate_stock_code(stock_code: str) -> None:
        """종목 코드 검증"""
        if not stock_code or len(stock_code) != 6 or not stock_code.isdigit():
            raise ValidationError(
                "종목 코드는 6자리 숫자여야 합니다.",
                detail={"stock_code": stock_code},
            )

    @staticmethod
    def _validate_date(date_str: str, field_name: str) -> None:
        """날짜 문자열 검증 (YYYYMMDD)"""
        if not date_str or len(date_str) != 8 or not date_str.isdigit():
            raise ValidationError(
                f"{field_name}은 YYYYMMDD 형식 8자리 숫자여야 합니다.",
                detail={field_name: date_str},
            )
        # 실제 날짜인지 파싱 검증
        try:
            datetime.strptime(date_str, "%Y%m%d")
        except ValueError as e:
            raise ValidationError(
                f"{field_name}이 유효한 날짜가 아닙니다.",
                detail={field_name: date_str, "error": str(e)},
            ) from e


def _safe_int(value: Any) -> int:
    """문자열/숫자를 안전하게 int로 변환. 실패 시 0 반환."""
    if value is None:
        return 0
    try:
        return int(value)
    except (ValueError, TypeError):
        return 0

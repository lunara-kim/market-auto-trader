"""
한국투자증권 OpenAPI 클라이언트

한국투자증권의 REST API를 사용하여:
- 접근 토큰 발급/갱신
- 주식 현재가 시세 조회 (국내/해외)
- 현금 매수/매도 주문 (국내/해외)
- 계좌 잔고 조회 (국내/해외)

모의투자(VPS)와 실전투자(PROD) 모두 지원합니다.

References:
    - https://apiportal.koreainvestment.com
    - https://github.com/koreainvestment/open-trading-api
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import httpx

from src.exceptions import BrokerAuthError, BrokerError, OrderError, ValidationError
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ───────────────────── Constants ─────────────────────

BASE_URL_PROD = "https://openapi.koreainvestment.com:9443"
BASE_URL_MOCK = "https://openapivts.koreainvestment.com:29443"

# Transaction IDs
TR_ID_TOKEN = "oauth2/tokenP"

# 시세 조회 (실전/모의 동일)
TR_ID_PRICE = "FHKST01010100"

# 주문 tr_id: (mock, prod)
TR_ID_BUY = ("VTTC0802U", "TTTC0802U")
TR_ID_SELL = ("VTTC0801U", "TTTC0801U")

# 잔고 조회 tr_id: (mock, prod)
TR_ID_BALANCE = ("VTTC8434R", "TTTC8434R")

# 주문 구분 코드
ORD_DVSN_MARKET = "01"  # 시장가
ORD_DVSN_LIMIT = "00"  # 지정가

# ───────────────────── Overseas Constants ─────────────────────

# 해외주식 시세 tr_id
TR_ID_OVERSEAS_PRICE = "HHDFS00000300"

# 해외주식 주문 tr_id: (mock, prod)
TR_ID_OVERSEAS_BUY = ("VTTT1002U", "JTTT1002U")

# 해외주식 잔고 조회 tr_id: (mock, prod)
TR_ID_OVERSEAS_BALANCE = ("VTTS3012R", "TTTS3012R")

# 지원 거래소 코드
VALID_EXCHANGE_CODES = {"NASD", "NYSE", "AMEX"}

# API rate limit: 초당 20건 (안전 마진 포함)
MIN_REQUEST_INTERVAL = 0.06  # 60ms


class KISClient:
    """한국투자증권 API 클라이언트

    httpx 기반 동기 HTTP 클라이언트로 한투 OpenAPI를 호출합니다.
    토큰은 자동으로 발급/갱신되며, 모든 API 오류는
    BrokerError 계열 예외로 변환됩니다.

    Usage::

        client = KISClient(
            app_key="...",
            app_secret="...",
            account_no="12345678-01",
            mock=True,
        )
        price = client.get_price("005930")
        print(price["stck_prpr"])  # 현재가
    """

    def __init__(
        self,
        app_key: str,
        app_secret: str,
        account_no: str,
        *,
        mock: bool = True,
        timeout: float = 10.0,
    ) -> None:
        if not app_key or not app_secret:
            raise ValidationError(
                "app_key와 app_secret은 필수입니다.",
                detail={"app_key": bool(app_key), "app_secret": bool(app_secret)},
            )
        if not account_no or "-" not in account_no:
            raise ValidationError(
                "계좌번호는 'XXXXXXXX-XX' 형식이어야 합니다.",
                detail={"account_no": account_no},
            )

        self.app_key = app_key
        self.app_secret = app_secret
        self.mock = mock

        # 계좌번호 파싱: "12345678-01" → ("12345678", "01")
        parts = account_no.split("-", 1)
        self.cano = parts[0]  # 종합계좌번호 8자리
        self.acnt_prdt_cd = parts[1]  # 계좌상품코드 2자리

        self.base_url = BASE_URL_MOCK if mock else BASE_URL_PROD

        # 토큰 관리
        self._access_token: str | None = None
        self._token_expired_at: datetime | None = None

        # Rate limiting
        self._last_request_time: float = 0.0

        # HTTP 클라이언트
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            headers={"Content-Type": "application/json", "Accept": "text/plain"},
        )

        logger.info(
            "KISClient 초기화 (모의투자: %s, 계좌: %s***)",
            mock,
            self.cano[:4] if len(self.cano) > 4 else "****",
        )

    def close(self) -> None:
        """HTTP 클라이언트 종료"""
        self._client.close()

    def __enter__(self) -> KISClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    # ───────────────────── Authentication ─────────────────────

    @property
    def access_token(self) -> str:
        """유효한 접근 토큰 반환. 만료 시 자동 재발급."""
        if self._is_token_valid():
            return self._access_token  # type: ignore[return-value]
        self._issue_token()
        return self._access_token  # type: ignore[return-value]

    def _is_token_valid(self) -> bool:
        """토큰 유효성 검사"""
        if self._access_token is None or self._token_expired_at is None:
            return False
        # 만료 5분 전에 미리 갱신
        now = datetime.now(timezone.utc)
        return now < self._token_expired_at.replace(
            tzinfo=timezone.utc
        ) - __import__("datetime").timedelta(minutes=5)

    def _issue_token(self) -> None:
        """POST /oauth2/tokenP 로 접근 토큰 발급"""
        logger.info("접근 토큰 발급 요청 중...")
        body = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
        }
        try:
            resp = self._client.post("/oauth2/tokenP", json=body)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise BrokerAuthError(
                "토큰 발급 실패",
                detail={"status": e.response.status_code, "body": e.response.text},
            ) from e
        except httpx.RequestError as e:
            raise BrokerError(
                "토큰 발급 중 네트워크 오류",
                detail={"error": str(e)},
            ) from e

        data = resp.json()
        self._access_token = data["access_token"]

        # 만료 시각 파싱 (KIS 포맷: "2026-02-14 06:11:00")
        expired_str = data.get("access_token_token_expired", "")
        if expired_str:
            self._token_expired_at = datetime.strptime(
                expired_str, "%Y-%m-%d %H:%M:%S"
            )
        else:
            # 기본 24시간
            from datetime import timedelta

            self._token_expired_at = datetime.now(timezone.utc) + timedelta(hours=24)

        logger.info(
            "토큰 발급 완료 (만료: %s)",
            self._token_expired_at.strftime("%Y-%m-%d %H:%M:%S"),
        )

    # ───────────────────── Hashkey ─────────────────────

    def _get_hashkey(self, body: dict[str, Any]) -> str:
        """POST /uapi/hashkey 로 해시키 발급 (주문 요청 시 필요)"""
        headers = {
            "Content-Type": "application/json",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
        }
        try:
            resp = self._client.post("/uapi/hashkey", json=body, headers=headers)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise BrokerError(
                "해시키 발급 실패",
                detail={"error": str(e)},
            ) from e

        return resp.json().get("HASH", "")

    # ───────────────────── Common Request ─────────────────────

    def _build_headers(self, tr_id: str) -> dict[str, str]:
        """API 호출용 공통 헤더 구성"""
        return {
            "Content-Type": "application/json",
            "authorization": f"Bearer {self.access_token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
            "custtype": "P",
        }

    def _rate_limit(self) -> None:
        """API rate limiting (초당 20건 제한 준수)"""
        now = time.monotonic()
        elapsed = now - self._last_request_time
        if elapsed < MIN_REQUEST_INTERVAL:
            time.sleep(MIN_REQUEST_INTERVAL - elapsed)
        self._last_request_time = time.monotonic()

    def _request_get(
        self,
        path: str,
        tr_id: str,
        params: dict[str, str],
    ) -> dict[str, Any]:
        """GET 요청 공통 처리"""
        self._rate_limit()
        headers = self._build_headers(tr_id)

        try:
            resp = self._client.get(path, params=params, headers=headers)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            self._handle_api_error(e)
        except httpx.RequestError as e:
            raise BrokerError(
                "API 요청 중 네트워크 오류",
                detail={"path": path, "error": str(e)},
            ) from e

        data = resp.json()
        self._check_response(data, path)
        return data

    def _request_post(
        self,
        path: str,
        tr_id: str,
        body: dict[str, Any],
        *,
        use_hashkey: bool = False,
    ) -> dict[str, Any]:
        """POST 요청 공통 처리"""
        self._rate_limit()
        headers = self._build_headers(tr_id)

        if use_hashkey:
            headers["hashkey"] = self._get_hashkey(body)

        try:
            resp = self._client.post(path, json=body, headers=headers)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            self._handle_api_error(e)
        except httpx.RequestError as e:
            raise BrokerError(
                "API 요청 중 네트워크 오류",
                detail={"path": path, "error": str(e)},
            ) from e

        data = resp.json()
        self._check_response(data, path)
        return data

    def _check_response(self, data: dict[str, Any], path: str) -> None:
        """API 응답 코드 확인"""
        rt_cd = data.get("rt_cd")
        if rt_cd != "0":
            msg = data.get("msg1", "알 수 없는 오류")
            msg_cd = data.get("msg_cd", "")
            raise BrokerError(
                f"API 오류 ({msg_cd}): {msg}",
                detail={"path": path, "rt_cd": rt_cd, "msg_cd": msg_cd, "msg1": msg},
            )

    def _handle_api_error(self, exc: httpx.HTTPStatusError) -> None:
        """HTTP 상태 에러를 BrokerError로 변환"""
        status = exc.response.status_code
        body = exc.response.text

        if status == 401:
            # 토큰 만료 → 재발급 후 재시도 가능
            self._access_token = None
            raise BrokerAuthError(
                "인증 실패 (토큰 만료 가능성)",
                detail={"status": status, "body": body},
            ) from exc

        raise BrokerError(
            f"API HTTP 오류 ({status})",
            detail={"status": status, "body": body},
        ) from exc

    # ───────────────────── Price Query ─────────────────────

    def get_price(self, stock_code: str) -> dict[str, Any]:
        """
        주식 현재가 시세 조회

        GET /uapi/domestic-stock/v1/quotations/inquire-price

        Args:
            stock_code: 종목 코드 (예: "005930" — 삼성전자)

        Returns:
            시세 정보 dict. 주요 키:
                - stck_prpr: 현재가
                - prdy_vrss: 전일 대비
                - prdy_ctrt: 전일 대비율 (%)
                - acml_vol: 누적 거래량
                - acml_tr_pbmn: 누적 거래대금
                - stck_oprc: 시가
                - stck_hgpr: 고가
                - stck_lwpr: 저가

        Raises:
            BrokerError: API 호출 실패
            BrokerAuthError: 인증 실패
        """
        if not stock_code or len(stock_code) != 6:
            raise ValidationError(
                "종목 코드는 6자리여야 합니다.",
                detail={"stock_code": stock_code},
            )

        logger.info("시세 조회: %s", stock_code)
        data = self._request_get(
            path="/uapi/domestic-stock/v1/quotations/inquire-price",
            tr_id=TR_ID_PRICE,
            params={
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": stock_code,
            },
        )
        return data.get("output", {})

    # ───────────────────── Order ─────────────────────

    def place_order(
        self,
        stock_code: str,
        order_type: str,
        quantity: int,
        price: int | None = None,
    ) -> dict[str, Any]:
        """
        주식 현금 주문 (매수/매도)

        POST /uapi/domestic-stock/v1/trading/order-cash

        Args:
            stock_code: 종목 코드 (예: "005930")
            order_type: "buy" (매수) 또는 "sell" (매도)
            quantity: 주문 수량 (1 이상)
            price: 주문 가격. None이면 시장가 주문.

        Returns:
            주문 결과 dict. 주요 키:
                - KRX_FWDG_ORD_ORGNO: 주문 조직번호
                - ODNO: 주문번호
                - ORD_TMD: 주문 시각

        Raises:
            ValidationError: 잘못된 파라미터
            OrderError: 주문 실패
            BrokerError: API 호출 실패
        """
        # 파라미터 검증
        if not stock_code or len(stock_code) != 6:
            raise ValidationError(
                "종목 코드는 6자리여야 합니다.",
                detail={"stock_code": stock_code},
            )
        if order_type not in ("buy", "sell"):
            raise ValidationError(
                "order_type은 'buy' 또는 'sell'이어야 합니다.",
                detail={"order_type": order_type},
            )
        if quantity < 1:
            raise ValidationError(
                "주문 수량은 1 이상이어야 합니다.",
                detail={"quantity": quantity},
            )
        if price is not None and price < 0:
            raise ValidationError(
                "주문 가격은 0 이상이어야 합니다.",
                detail={"price": price},
            )

        # tr_id 결정
        if order_type == "buy":
            tr_id = TR_ID_BUY[0] if self.mock else TR_ID_BUY[1]
        else:
            tr_id = TR_ID_SELL[0] if self.mock else TR_ID_SELL[1]

        # 주문 구분 (시장가/지정가)
        ord_dvsn = ORD_DVSN_MARKET if price is None else ORD_DVSN_LIMIT
        ord_unpr = "0" if price is None else str(price)

        body = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "PDNO": stock_code,
            "ORD_DVSN": ord_dvsn,
            "ORD_QTY": str(quantity),
            "ORD_UNPR": ord_unpr,
        }

        logger.info(
            "주문 요청: %s %s %d주 (가격: %s)",
            order_type.upper(),
            stock_code,
            quantity,
            ord_unpr if price else "시장가",
        )

        try:
            data = self._request_post(
                path="/uapi/domestic-stock/v1/trading/order-cash",
                tr_id=tr_id,
                body=body,
                use_hashkey=True,
            )
        except BrokerError as e:
            # 주문 관련 에러를 OrderError로 변환
            raise OrderError(
                str(e),
                detail=e.detail,
            ) from e

        result = data.get("output", {})
        logger.info(
            "주문 완료: 주문번호 %s (시각: %s)",
            result.get("ODNO", "N/A"),
            result.get("ORD_TMD", "N/A"),
        )
        return result

    # ───────────────────── Balance ─────────────────────

    def get_balance(self) -> dict[str, Any]:
        """
        계좌 잔고 조회

        GET /uapi/domestic-stock/v1/trading/inquire-balance

        Returns:
            잔고 정보 dict:
                - holdings: 보유 종목 리스트 (output1)
                    - pdno: 종목코드
                    - prdt_name: 종목명
                    - hldg_qty: 보유수량
                    - pchs_avg_pric: 매입평균가
                    - prpr: 현재가
                    - evlu_pfls_amt: 평가손익금액
                    - evlu_pfls_rt: 평가손익률
                - summary: 계좌 요약 (output2)
                    - dnca_tot_amt: 예수금 총액
                    - tot_evlu_amt: 총 평가금액
                    - pchs_amt_smtl_amt: 매입금액 합계
                    - evlu_amt_smtl_amt: 평가금액 합계
                    - evlu_pfls_smtl_amt: 평가손익 합계
                    - nass_amt: 순자산금액

        Raises:
            BrokerError: API 호출 실패
        """
        tr_id = TR_ID_BALANCE[0] if self.mock else TR_ID_BALANCE[1]

        logger.info("잔고 조회 요청")
        data = self._request_get(
            path="/uapi/domestic-stock/v1/trading/inquire-balance",
            tr_id=tr_id,
            params={
                "CANO": self.cano,
                "ACNT_PRDT_CD": self.acnt_prdt_cd,
                "AFHR_FLPR_YN": "N",
                "OFL_YN": "",
                "INQR_DVSN": "02",
                "UNPR_DVSN": "01",
                "FUND_STTL_ICLD_YN": "N",
                "FNCG_AMT_AUTO_RDPT_YN": "N",
                "PRCS_DVSN": "01",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": "",
            },
        )

        holdings = data.get("output1", [])
        summary = data.get("output2", [{}])

        result = {
            "holdings": holdings,
            "summary": summary[0] if summary else {},
        }

        logger.info(
            "잔고 조회 완료: 보유종목 %d건",
            len(holdings),
        )
        return result

    # ───────────────────── Overseas Price ─────────────────────

    def get_overseas_price(
        self, ticker: str, exchange_code: str
    ) -> dict[str, Any]:
        """
        해외주식 현재가 시세 조회

        GET /uapi/overseas-price/v1/quotations/price

        Args:
            ticker: 해외 종목 티커 (예: "AAPL", "TSLA")
            exchange_code: 거래소 코드 ("NASD", "NYSE", "AMEX")

        Returns:
            시세 정보 dict. 주요 키:
                - last: 현재가
                - diff: 전일 대비
                - rate: 전일 대비율 (%)
                - tvol: 거래량
                - tamt: 거래대금

        Raises:
            ValidationError: 잘못된 파라미터
            BrokerError: API 호출 실패
        """
        if not ticker or not ticker.isalpha():
            raise ValidationError(
                "해외 종목 티커는 영문자로만 구성되어야 합니다.",
                detail={"ticker": ticker},
            )
        if exchange_code not in VALID_EXCHANGE_CODES:
            raise ValidationError(
                f"거래소 코드는 {VALID_EXCHANGE_CODES} 중 하나여야 합니다.",
                detail={"exchange_code": exchange_code},
            )

        logger.info("해외 시세 조회: %s (%s)", ticker, exchange_code)
        data = self._request_get(
            path="/uapi/overseas-price/v1/quotations/price",
            tr_id=TR_ID_OVERSEAS_PRICE,
            params={
                "AUTH": "",
                "EXCD": exchange_code,
                "SYMB": ticker,
            },
        )
        return data.get("output", {})

    # ───────────────────── Overseas Order ─────────────────────

    def place_overseas_order(
        self,
        ticker: str,
        exchange_code: str,
        quantity: int,
        price: float,
    ) -> dict[str, Any]:
        """
        해외주식 매수 주문

        POST /uapi/overseas-stock/v1/trading/order

        해외주식은 시장가 주문이 제한적이므로 지정가(price)를 필수로 받습니다.

        Args:
            ticker: 해외 종목 티커 (예: "AAPL")
            exchange_code: 거래소 코드 ("NASD", "NYSE", "AMEX")
            quantity: 주문 수량 (1 이상 정수)
            price: 주문 가격 (소수점 가능, 0 초과)

        Returns:
            주문 결과 dict. 주요 키:
                - KRX_FWDG_ORD_ORGNO: 주문 조직번호
                - ODNO: 주문번호
                - ORD_TMD: 주문 시각

        Raises:
            ValidationError: 잘못된 파라미터
            OrderError: 주문 실패
        """
        if not ticker or not ticker.isalpha():
            raise ValidationError(
                "해외 종목 티커는 영문자로만 구성되어야 합니다.",
                detail={"ticker": ticker},
            )
        if exchange_code not in VALID_EXCHANGE_CODES:
            raise ValidationError(
                f"거래소 코드는 {VALID_EXCHANGE_CODES} 중 하나여야 합니다.",
                detail={"exchange_code": exchange_code},
            )
        if quantity < 1:
            raise ValidationError(
                "주문 수량은 1 이상이어야 합니다.",
                detail={"quantity": quantity},
            )
        if price <= 0:
            raise ValidationError(
                "해외주식 주문 가격은 0보다 커야 합니다.",
                detail={"price": price},
            )

        tr_id = TR_ID_OVERSEAS_BUY[0] if self.mock else TR_ID_OVERSEAS_BUY[1]

        # 거래소별 주문 구분 코드 매핑
        ovrs_excg_cd_map = {
            "NASD": "NASD",
            "NYSE": "NYSE",
            "AMEX": "AMEX",
        }

        body = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "OVRS_EXCG_CD": ovrs_excg_cd_map[exchange_code],
            "PDNO": ticker,
            "ORD_QTY": str(quantity),
            "OVRS_ORD_UNPR": f"{price:.2f}",
            "ORD_SVR_DVSN_CD": "0",
            "ORD_DVSN": "00",  # 지정가
        }

        logger.info(
            "해외주식 매수 주문: %s (%s) %d주 × $%.2f",
            ticker,
            exchange_code,
            quantity,
            price,
        )

        try:
            data = self._request_post(
                path="/uapi/overseas-stock/v1/trading/order",
                tr_id=tr_id,
                body=body,
                use_hashkey=True,
            )
        except BrokerError as e:
            raise OrderError(
                str(e),
                detail=e.detail,
            ) from e

        result = data.get("output", {})
        logger.info(
            "해외주식 주문 완료: 주문번호 %s (시각: %s)",
            result.get("ODNO", "N/A"),
            result.get("ORD_TMD", "N/A"),
        )
        return result

    # ───────────────────── Overseas Balance ─────────────────────

    def get_overseas_balance(self) -> dict[str, Any]:
        """
        해외주식 잔고 조회

        GET /uapi/overseas-stock/v1/trading/inquire-balance

        Returns:
            잔고 정보 dict:
                - holdings: 해외 보유 종목 리스트 (output1)
                - summary: 계좌 요약 (output2)

        Raises:
            BrokerError: API 호출 실패
        """
        tr_id = TR_ID_OVERSEAS_BALANCE[0] if self.mock else TR_ID_OVERSEAS_BALANCE[1]

        logger.info("해외주식 잔고 조회 요청")
        data = self._request_get(
            path="/uapi/overseas-stock/v1/trading/inquire-balance",
            tr_id=tr_id,
            params={
                "CANO": self.cano,
                "ACNT_PRDT_CD": self.acnt_prdt_cd,
                "OVRS_EXCG_CD": "NASD",
                "TR_CRCY_CD": "USD",
                "CTX_AREA_FK200": "",
                "CTX_AREA_NK200": "",
            },
        )

        holdings = data.get("output1", [])
        summary = data.get("output2", {})

        result = {
            "holdings": holdings,
            "summary": summary,
        }

        logger.info(
            "해외주식 잔고 조회 완료: 보유종목 %d건",
            len(holdings),
        )
        return result

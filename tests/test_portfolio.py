"""
포트폴리오 API 테스트

KISClient를 모킹하여 포트폴리오 엔드포인트를 검증합니다.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.api.dependencies import get_kis_client
from src.api.portfolio import _safe_float, _safe_int
from src.main import app


# ─────────────────────────────────────────────
# 유틸리티 함수 테스트
# ─────────────────────────────────────────────

class TestSafeFloat:
    """_safe_float 변환 테스트"""

    def test_valid_string(self) -> None:
        assert _safe_float("12345.67") == 12345.67

    def test_integer_string(self) -> None:
        assert _safe_float("10000") == 10000.0

    def test_none_returns_default(self) -> None:
        assert _safe_float(None) == 0.0

    def test_empty_string_returns_default(self) -> None:
        assert _safe_float("") == 0.0

    def test_invalid_string_returns_default(self) -> None:
        assert _safe_float("abc") == 0.0

    def test_custom_default(self) -> None:
        assert _safe_float(None, default=-1.0) == -1.0


class TestSafeInt:
    """_safe_int 변환 테스트"""

    def test_valid_string(self) -> None:
        assert _safe_int("42") == 42

    def test_none_returns_default(self) -> None:
        assert _safe_int(None) == 0

    def test_empty_string_returns_default(self) -> None:
        assert _safe_int("") == 0

    def test_invalid_string_returns_default(self) -> None:
        assert _safe_int("xyz") == 0


# ─────────────────────────────────────────────
# 포트폴리오 API 엔드포인트 테스트
# ─────────────────────────────────────────────

def _mock_kis_client(balance_data: dict) -> MagicMock:
    """KISClient 모킹"""
    mock = MagicMock()
    mock.get_balance.return_value = balance_data
    mock.close.return_value = None
    return mock


SAMPLE_BALANCE = {
    "holdings": [
        {
            "pdno": "005930",
            "prdt_name": "삼성전자",
            "hldg_qty": "10",
            "pchs_avg_pric": "65000",
            "prpr": "68000",
            "evlu_amt": "680000",
            "evlu_pfls_amt": "30000",
            "evlu_pfls_rt": "4.62",
        },
        {
            "pdno": "035720",
            "prdt_name": "카카오",
            "hldg_qty": "5",
            "pchs_avg_pric": "50000",
            "prpr": "48000",
            "evlu_amt": "240000",
            "evlu_pfls_amt": "-10000",
            "evlu_pfls_rt": "-4.00",
        },
        {
            # 보유수량 0인 종목은 제외
            "pdno": "000000",
            "prdt_name": "빈종목",
            "hldg_qty": "0",
            "pchs_avg_pric": "0",
            "prpr": "0",
            "evlu_amt": "0",
            "evlu_pfls_amt": "0",
            "evlu_pfls_rt": "0",
        },
    ],
    "summary": {
        "dnca_tot_amt": "5000000",
        "tot_evlu_amt": "5920000",
        "pchs_amt_smtl_amt": "900000",
        "evlu_pfls_smtl_amt": "20000",
        "nass_amt": "5920000",
    },
}


class TestGetPortfolio:
    """GET /api/v1/portfolio 테스트"""

    def setup_method(self) -> None:
        self.client = TestClient(app)

    def test_success(self) -> None:
        """정상 포트폴리오 조회"""
        mock = _mock_kis_client(SAMPLE_BALANCE)
        app.dependency_overrides[get_kis_client] = lambda: mock

        resp = self.client.get("/api/v1/portfolio")
        assert resp.status_code == 200

        data = resp.json()
        assert len(data["holdings"]) == 2  # 보유수량 0인 종목 제외
        assert data["holdings"][0]["stock_code"] == "005930"
        assert data["holdings"][0]["quantity"] == 10
        assert data["holdings"][0]["current_price"] == 68000.0
        assert data["summary"]["cash"] == 5000000.0
        assert data["summary"]["net_asset"] == 5920000.0
        assert "updated_at" in data

        app.dependency_overrides.clear()

    def test_empty_holdings(self) -> None:
        """보유종목 없는 경우"""
        mock = _mock_kis_client({
            "holdings": [],
            "summary": {
                "dnca_tot_amt": "10000000",
                "tot_evlu_amt": "10000000",
                "pchs_amt_smtl_amt": "0",
                "evlu_pfls_smtl_amt": "0",
                "nass_amt": "10000000",
            },
        })
        app.dependency_overrides[get_kis_client] = lambda: mock

        resp = self.client.get("/api/v1/portfolio")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["holdings"]) == 0
        assert data["summary"]["cash"] == 10000000.0

        app.dependency_overrides.clear()

    def test_missing_fields_use_defaults(self) -> None:
        """한투 API 응답에 필드 없으면 기본값 사용"""
        mock = _mock_kis_client({
            "holdings": [
                {"pdno": "005930", "hldg_qty": "3"},  # 최소 필드만
            ],
            "summary": {},
        })
        app.dependency_overrides[get_kis_client] = lambda: mock

        resp = self.client.get("/api/v1/portfolio")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["holdings"]) == 1
        assert data["holdings"][0]["stock_name"] == ""
        assert data["holdings"][0]["avg_price"] == 0.0
        assert data["summary"]["cash"] == 0.0

        app.dependency_overrides.clear()


class TestGetPortfolioSummary:
    """GET /api/v1/portfolio/summary 테스트"""

    def setup_method(self) -> None:
        self.client = TestClient(app)

    def test_success(self) -> None:
        """정상 계좌 요약 조회"""
        mock = _mock_kis_client(SAMPLE_BALANCE)
        app.dependency_overrides[get_kis_client] = lambda: mock

        resp = self.client.get("/api/v1/portfolio/summary")
        assert resp.status_code == 200

        data = resp.json()
        assert data["cash"] == 5000000.0
        assert data["total_eval"] == 5920000.0
        assert data["net_asset"] == 5920000.0

        app.dependency_overrides.clear()

    def test_no_credentials_error(self) -> None:
        """API 인증 정보 없으면 에러"""
        # 기본 의존성 (settings에 키 없음)이면 ValidationError (422)
        app.dependency_overrides.pop(get_kis_client, None)

        resp = self.client.get("/api/v1/portfolio/summary")
        assert resp.status_code == 422  # ValidationError → 422
        assert "error" in resp.json()

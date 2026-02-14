"""
매매 신호 API 테스트

KISClient + DB를 모킹하여 신호 생성 및 조회 엔드포인트를 검증합니다.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.api.dependencies import get_db, get_kis_client
from src.api.schemas import MATypeEnum, SignalRequest
from src.broker.kis_client import KISClient
from src.main import app


def _mock_kis_client_with_prices() -> MagicMock:
    """일봉 데이터를 반환하는 KISClient 모킹"""
    mock = MagicMock(spec=KISClient)

    # get_price 모킹
    mock.get_price.return_value = {
        "stck_prpr": "68000",
        "prdy_vrss": "1000",
        "prdy_ctrt": "1.49",
        "acml_vol": "12345678",
    }

    # _request_get 모킹 (collector.fetch_daily_prices가 사용)
    # 30일치 일봉 데이터 생성 (상승 추세)
    daily_records = []
    base_price = 60000
    for i in range(30):
        date = f"2026{(i // 28) + 1:02d}{(i % 28) + 1:02d}"
        price = base_price + i * 500
        daily_records.append({
            "stck_bsop_date": date,
            "stck_oprc": str(price - 200),
            "stck_hgpr": str(price + 300),
            "stck_lwpr": str(price - 500),
            "stck_clpr": str(price),
            "acml_vol": str(100000 + i * 1000),
            "acml_tr_pbmn": str(price * 100000),
            "prdy_vrss": "500",
            "prdy_vrss_sign": "2",
        })

    def fake_request_get(path, tr_id, params):
        return {"rt_cd": "0", "output2": daily_records}

    mock._request_get = MagicMock(side_effect=fake_request_get)
    mock.close.return_value = None

    return mock


class FakeDBSession:
    """가짜 DB 세션"""

    def __init__(self) -> None:
        self.added: list = []

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass

    async def execute(self, stmt):
        class FakeResult:
            def scalars(self):
                return self

            def all(self):
                return []

            def scalar(self):
                return 0

        return FakeResult()


# ─────────────────────────────────────────────
# SignalRequest 스키마 검증
# ─────────────────────────────────────────────

class TestSignalRequest:
    """SignalRequest 입력 검증"""

    def test_default_values(self) -> None:
        req = SignalRequest(stock_code="005930")
        assert req.short_window == 5
        assert req.long_window == 20
        assert req.ma_type == MATypeEnum.SMA

    def test_custom_values(self) -> None:
        req = SignalRequest(
            stock_code="035720",
            short_window=10,
            long_window=50,
            ma_type=MATypeEnum.EMA,
        )
        assert req.short_window == 10
        assert req.long_window == 50

    def test_invalid_stock_code(self) -> None:
        with pytest.raises(Exception):
            SignalRequest(stock_code="12345")

    def test_short_window_min(self) -> None:
        with pytest.raises(Exception):
            SignalRequest(stock_code="005930", short_window=1)


# ─────────────────────────────────────────────
# POST /api/v1/signals 테스트
# ─────────────────────────────────────────────

class TestCreateSignal:
    """POST /api/v1/signals 테스트"""

    def setup_method(self) -> None:
        self.client = TestClient(app)
        self.fake_db = FakeDBSession()

    def _override_deps(self, mock_client: MagicMock) -> None:
        app.dependency_overrides[get_kis_client] = lambda: mock_client

        async def _get_fake_db():
            yield self.fake_db

        app.dependency_overrides[get_db] = _get_fake_db

    def teardown_method(self) -> None:
        app.dependency_overrides.clear()

    def test_success_sma(self) -> None:
        """SMA 전략으로 신호 생성 성공"""
        mock = _mock_kis_client_with_prices()
        self._override_deps(mock)

        resp = self.client.post("/api/v1/signals", json={
            "stock_code": "005930",
            "short_window": 5,
            "long_window": 20,
            "ma_type": "sma",
        })
        assert resp.status_code == 200

        data = resp.json()
        assert data["stock_code"] == "005930"
        assert data["signal"] in ("buy", "sell", "hold")
        assert 0.0 <= data["strength"] <= 1.0
        assert data["reason"]
        assert "SMA" in data["strategy_name"]
        assert "metrics" in data
        assert data["metrics"]["current_price"] > 0
        assert "timestamp" in data

        # DB에 기록됐는지
        assert len(self.fake_db.added) == 1

    def test_success_ema(self) -> None:
        """EMA 전략으로 신호 생성"""
        mock = _mock_kis_client_with_prices()
        self._override_deps(mock)

        resp = self.client.post("/api/v1/signals", json={
            "stock_code": "005930",
            "short_window": 5,
            "long_window": 20,
            "ma_type": "ema",
        })
        assert resp.status_code == 200
        assert "EMA" in resp.json()["strategy_name"]

    def test_custom_windows(self) -> None:
        """커스텀 기간 설정"""
        mock = _mock_kis_client_with_prices()
        self._override_deps(mock)

        resp = self.client.post("/api/v1/signals", json={
            "stock_code": "005930",
            "short_window": 3,
            "long_window": 10,
        })
        assert resp.status_code == 200
        assert "(3,10)" in resp.json()["strategy_name"]

    def test_short_ge_long_rejected(self) -> None:
        """단기 >= 장기 → 에러"""
        mock = _mock_kis_client_with_prices()
        self._override_deps(mock)

        resp = self.client.post("/api/v1/signals", json={
            "stock_code": "005930",
            "short_window": 20,
            "long_window": 20,
        })
        assert resp.status_code == 422  # ValidationError

    def test_invalid_stock_code(self) -> None:
        """잘못된 종목코드 → 422"""
        mock = _mock_kis_client_with_prices()
        self._override_deps(mock)

        resp = self.client.post("/api/v1/signals", json={
            "stock_code": "ABC",
        })
        assert resp.status_code == 422

    def test_response_has_metrics(self) -> None:
        """응답에 metrics 필드 포함"""
        mock = _mock_kis_client_with_prices()
        self._override_deps(mock)

        resp = self.client.post("/api/v1/signals", json={
            "stock_code": "005930",
        })
        assert resp.status_code == 200

        metrics = resp.json()["metrics"]
        assert "current_short_ma" in metrics
        assert "current_long_ma" in metrics
        assert "ma_spread" in metrics
        assert "trend" in metrics
        assert "current_price" in metrics


# ─────────────────────────────────────────────
# GET /api/v1/signals 테스트
# ─────────────────────────────────────────────

class TestGetSignals:
    """GET /api/v1/signals 테스트"""

    def setup_method(self) -> None:
        self.client = TestClient(app)
        self.fake_db = FakeDBSession()

    def _override_db(self) -> None:
        async def _get_fake_db():
            yield self.fake_db

        app.dependency_overrides[get_db] = _get_fake_db

    def teardown_method(self) -> None:
        app.dependency_overrides.clear()

    def test_empty_signals(self) -> None:
        """신호 내역 없을 때"""
        self._override_db()

        resp = self.client.get("/api/v1/signals")
        assert resp.status_code == 200

        data = resp.json()
        assert data["signals"] == []
        assert data["total"] == 0

    def test_with_filters(self) -> None:
        """필터 파라미터 전달"""
        self._override_db()

        resp = self.client.get(
            "/api/v1/signals",
            params={"stock_code": "005930", "signal_type": "buy", "limit": 10},
        )
        assert resp.status_code == 200

    def test_invalid_limit(self) -> None:
        """limit > 200 → 422"""
        self._override_db()

        resp = self.client.get("/api/v1/signals", params={"limit": 999})
        assert resp.status_code == 422

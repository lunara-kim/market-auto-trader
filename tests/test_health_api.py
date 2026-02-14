"""
상세 헬스체크 API 테스트

DB 연결 상태, 한투 API 설정 상태, 전체 상태 판정 등을 검증합니다.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from httpx import AsyncClient, ASGITransport

from src.api.health import (
    ComponentHealth,
    ComponentStatus,
    OverallStatus,
    _check_broker,
    _check_database,
    _determine_overall_status,
)
from src.main import app


@pytest.fixture
def client():
    """httpx AsyncClient fixture"""
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


# ────────────────── _determine_overall_status ──────────────────


class TestDetermineOverallStatus:
    """전체 상태 판정 로직 테스트"""

    def test_all_up(self) -> None:
        """모든 컴포넌트 UP → HEALTHY"""
        components = {
            "database": ComponentHealth(status=ComponentStatus.UP),
            "broker": ComponentHealth(status=ComponentStatus.UP),
        }
        assert _determine_overall_status(components) == OverallStatus.HEALTHY

    def test_unconfigured_is_healthy(self) -> None:
        """UNCONFIGURED는 정상 취급"""
        components = {
            "database": ComponentHealth(status=ComponentStatus.UP),
            "broker": ComponentHealth(status=ComponentStatus.UNCONFIGURED),
        }
        assert _determine_overall_status(components) == OverallStatus.HEALTHY

    def test_degraded_component(self) -> None:
        """하나라도 DEGRADED → DEGRADED"""
        components = {
            "database": ComponentHealth(status=ComponentStatus.UP),
            "broker": ComponentHealth(status=ComponentStatus.DEGRADED),
        }
        assert _determine_overall_status(components) == OverallStatus.DEGRADED

    def test_critical_down(self) -> None:
        """필수 컴포넌트(database) DOWN → UNHEALTHY"""
        components = {
            "database": ComponentHealth(status=ComponentStatus.DOWN),
            "broker": ComponentHealth(status=ComponentStatus.UP),
        }
        assert _determine_overall_status(components) == OverallStatus.UNHEALTHY

    def test_non_critical_down(self) -> None:
        """비필수 컴포넌트 DOWN → DEGRADED (UNHEALTHY는 아님)"""
        components = {
            "database": ComponentHealth(status=ComponentStatus.UP),
            "some_service": ComponentHealth(status=ComponentStatus.DOWN),
        }
        assert _determine_overall_status(components) == OverallStatus.DEGRADED


# ────────────────── _check_broker ──────────────────


class TestCheckBroker:
    """한투 API 설정 상태 확인 테스트"""

    def test_all_configured(self) -> None:
        """모든 설정이 있으면 UP"""
        with patch("src.api.health.settings") as mock_settings:
            mock_settings.kis_app_key = "test_key"
            mock_settings.kis_app_secret = "test_secret"
            mock_settings.kis_account_no = "12345678-01"
            mock_settings.kis_mock = True

            result = _check_broker()
            assert result.status == ComponentStatus.UP
            assert "모의투자" in (result.message or "")

    def test_prod_mode_label(self) -> None:
        """실전투자 모드 라벨 확인"""
        with patch("src.api.health.settings") as mock_settings:
            mock_settings.kis_app_key = "key"
            mock_settings.kis_app_secret = "secret"
            mock_settings.kis_account_no = "12345678-01"
            mock_settings.kis_mock = False

            result = _check_broker()
            assert result.status == ComponentStatus.UP
            assert "실전투자" in (result.message or "")

    def test_no_config(self) -> None:
        """설정 없으면 UNCONFIGURED"""
        with patch("src.api.health.settings") as mock_settings:
            mock_settings.kis_app_key = ""
            mock_settings.kis_app_secret = ""
            mock_settings.kis_account_no = ""

            result = _check_broker()
            assert result.status == ComponentStatus.UNCONFIGURED

    def test_partial_config(self) -> None:
        """일부만 설정되면 DEGRADED"""
        with patch("src.api.health.settings") as mock_settings:
            mock_settings.kis_app_key = "test_key"
            mock_settings.kis_app_secret = ""
            mock_settings.kis_account_no = ""

            result = _check_broker()
            assert result.status == ComponentStatus.DEGRADED
            assert "불완전" in (result.message or "")


# ────────────────── _check_database ──────────────────


class TestCheckDatabase:
    """DB 연결 상태 확인 테스트"""

    @pytest.mark.asyncio
    async def test_db_up(self) -> None:
        """DB 연결 성공 → UP"""
        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 1
        mock_conn.execute = AsyncMock(return_value=mock_result)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        with patch("src.api.health.engine") as mock_engine:
            mock_engine.connect.return_value = mock_cm
            mock_pool = MagicMock()
            mock_pool.size.return_value = 5
            mock_pool.checkedin.return_value = 5
            mock_pool.checkedout.return_value = 0
            mock_pool.overflow.return_value = 0
            mock_engine.pool = mock_pool

            result = await _check_database()
            assert result.status == ComponentStatus.UP
            assert result.latency_ms is not None
            assert result.details is not None
            assert "pool_size" in result.details

    @pytest.mark.asyncio
    async def test_db_down(self) -> None:
        """DB 연결 실패 → DOWN"""
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(side_effect=ConnectionError("DB 연결 불가"))
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        with patch("src.api.health.engine") as mock_engine:
            mock_engine.connect.return_value = mock_cm

            result = await _check_database()
            assert result.status == ComponentStatus.DOWN
            assert result.latency_ms is not None
            assert "ConnectionError" in (result.message or "")


# ────────────────── API 엔드포인트 ──────────────────


class TestHealthEndpoint:
    """/api/v1/health/detailed API 테스트"""

    @pytest.mark.asyncio
    async def test_endpoint_returns_200(self, client: AsyncClient) -> None:
        """상세 헬스체크 엔드포인트 기본 응답"""
        # DB mock (테스트 환경에서는 실제 DB가 없을 수 있으므로)
        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 1
        mock_conn.execute = AsyncMock(return_value=mock_result)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        with patch("src.api.health.engine") as mock_engine:
            mock_engine.connect.return_value = mock_cm
            mock_pool = MagicMock()
            mock_pool.size.return_value = 5
            mock_pool.checkedin.return_value = 5
            mock_pool.checkedout.return_value = 0
            mock_pool.overflow.return_value = 0
            mock_engine.pool = mock_pool

            resp = await client.get("/api/v1/health/detailed")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("healthy", "degraded", "unhealthy")
        assert "version" in data
        assert "uptime_seconds" in data
        assert "components" in data
        assert "database" in data["components"]

    @pytest.mark.asyncio
    async def test_endpoint_without_broker(self, client: AsyncClient) -> None:
        """include_broker=false 시 broker 상태 제외"""
        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 1
        mock_conn.execute = AsyncMock(return_value=mock_result)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        with patch("src.api.health.engine") as mock_engine:
            mock_engine.connect.return_value = mock_cm
            mock_pool = MagicMock()
            mock_pool.size.return_value = 5
            mock_pool.checkedin.return_value = 5
            mock_pool.checkedout.return_value = 0
            mock_pool.overflow.return_value = 0
            mock_engine.pool = mock_pool

            resp = await client.get("/api/v1/health/detailed?include_broker=false")

        assert resp.status_code == 200
        data = resp.json()
        assert "broker" not in data["components"]

    @pytest.mark.asyncio
    async def test_endpoint_db_down_is_unhealthy(self, client: AsyncClient) -> None:
        """DB 다운 시 전체 상태 UNHEALTHY"""
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(side_effect=ConnectionError("DB 다운"))
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        with patch("src.api.health.engine") as mock_engine:
            mock_engine.connect.return_value = mock_cm

            resp = await client.get("/api/v1/health/detailed?include_broker=false")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "unhealthy"
        assert data["components"]["database"]["status"] == "down"

    @pytest.mark.asyncio
    async def test_response_structure(self, client: AsyncClient) -> None:
        """응답 구조 상세 검증"""
        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 1
        mock_conn.execute = AsyncMock(return_value=mock_result)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=None)

        with patch("src.api.health.engine") as mock_engine:
            mock_engine.connect.return_value = mock_cm
            mock_pool = MagicMock()
            mock_pool.size.return_value = 5
            mock_pool.checkedin.return_value = 5
            mock_pool.checkedout.return_value = 0
            mock_pool.overflow.return_value = 0
            mock_engine.pool = mock_pool

            resp = await client.get("/api/v1/health/detailed")

        data = resp.json()
        # 필수 필드 존재 확인
        assert "env" in data
        assert "started_at" in data
        assert "checked_at" in data
        assert isinstance(data["uptime_seconds"], (int, float))
        assert data["uptime_seconds"] >= 0


# ────────────────── ComponentHealth 모델 ──────────────────


class TestComponentHealthModel:
    """ComponentHealth Pydantic 모델 테스트"""

    def test_minimal(self) -> None:
        """최소 필드만으로 생성"""
        h = ComponentHealth(status=ComponentStatus.UP)
        assert h.status == ComponentStatus.UP
        assert h.latency_ms is None
        assert h.message is None
        assert h.details is None

    def test_full(self) -> None:
        """모든 필드 지정"""
        h = ComponentHealth(
            status=ComponentStatus.DOWN,
            latency_ms=42.5,
            message="연결 실패",
            details={"host": "localhost", "port": 5432},
        )
        assert h.status == ComponentStatus.DOWN
        assert h.latency_ms == 42.5
        assert h.details["port"] == 5432

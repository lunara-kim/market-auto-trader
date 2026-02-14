"""
리밸런싱 API 테스트

src/api/rebalancing.py의 엔드포인트를 검증합니다.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from config.portfolio import PortfolioSettings
from src.api.rebalancing import (
    _get_portfolio_settings,
    _get_scheduler,
    get_db,
)
from src.main import app
from src.strategy.rebalance_scheduler import RebalanceScheduler

client = TestClient(app)


async def _mock_get_db():  # type: ignore[no-untyped-def]
    """DB 세션 모킹"""
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.execute = AsyncMock()
    yield session


def _test_config(**kwargs: object) -> PortfolioSettings:
    """테스트용 PortfolioSettings"""
    defaults: dict[str, object] = {
        "rebalance_enabled": False,
        "rebalance_schedule": "weekly",
        "rebalance_day_of_week": 0,
        "rebalance_day_of_month": 1,
        "rebalance_hour": 9,
    }
    defaults.update(kwargs)
    return PortfolioSettings(**defaults)  # type: ignore[arg-type]


# ───────────────── POST /execute (dry_run) ─────────────────


class TestExecuteRebalance:
    """리밸런싱 실행 엔드포인트 테스트"""

    def test_dry_run_returns_plan(self) -> None:
        """dry_run=True이면 계획만 반환, rebalance_id는 None"""
        config = _test_config()
        app.dependency_overrides[_get_portfolio_settings] = lambda: config
        app.dependency_overrides[get_db] = _mock_get_db

        try:
            response = client.post(
                "/api/v1/rebalancing/execute",
                json={"dry_run": True},
            )
            assert response.status_code == 200

            data = response.json()
            assert data["dry_run"] is True
            assert data["rebalance_id"] is None
            assert data["trigger_type"] == "manual"
            assert data["status"] == "planned"
            assert "order_details" in data
        finally:
            app.dependency_overrides.pop(_get_portfolio_settings, None)
            app.dependency_overrides.pop(get_db, None)

    def test_default_is_dry_run(self) -> None:
        """body 없이 호출해도 기본값 dry_run=True"""
        config = _test_config()
        app.dependency_overrides[_get_portfolio_settings] = lambda: config
        app.dependency_overrides[get_db] = _mock_get_db

        try:
            response = client.post(
                "/api/v1/rebalancing/execute",
                json={},
            )
            assert response.status_code == 200

            data = response.json()
            assert data["dry_run"] is True
        finally:
            app.dependency_overrides.pop(_get_portfolio_settings, None)
            app.dependency_overrides.pop(get_db, None)


# ───────────────── GET /schedule ─────────────────


class TestScheduleEndpoint:
    """스케줄 조회 엔드포인트 테스트"""

    def test_schedule_disabled(self) -> None:
        """비활성화 상태에서 스케줄 조회"""
        config = _test_config(rebalance_enabled=False)
        scheduler = RebalanceScheduler(config)

        app.dependency_overrides[_get_portfolio_settings] = lambda: config
        app.dependency_overrides[_get_scheduler] = lambda: scheduler

        try:
            response = client.get("/api/v1/rebalancing/schedule")
            assert response.status_code == 200

            data = response.json()
            assert data["enabled"] is False
            assert data["next_run_at"] is None
            assert data["schedule"] == "weekly"
        finally:
            app.dependency_overrides.pop(_get_portfolio_settings, None)
            app.dependency_overrides.pop(_get_scheduler, None)

    def test_schedule_enabled(self) -> None:
        """활성화 상태에서 스케줄 조회 — next_run_at 포함"""
        config = _test_config(rebalance_enabled=True)
        scheduler = RebalanceScheduler(config)

        app.dependency_overrides[_get_portfolio_settings] = lambda: config
        app.dependency_overrides[_get_scheduler] = lambda: scheduler

        try:
            response = client.get("/api/v1/rebalancing/schedule")
            assert response.status_code == 200

            data = response.json()
            assert data["enabled"] is True
            assert data["next_run_at"] is not None
            assert data["schedule"] == "weekly"
            assert data["day_of_week"] == 0
            assert data["hour"] == 9
        finally:
            app.dependency_overrides.pop(_get_portfolio_settings, None)
            app.dependency_overrides.pop(_get_scheduler, None)


# ───────────────── POST /schedule/toggle ─────────────────


class TestToggleEndpoint:
    """자동 리밸런싱 토글 테스트"""

    def test_toggle_enable(self) -> None:
        """비활성 → 활성화"""
        config = _test_config(rebalance_enabled=False)
        scheduler = RebalanceScheduler(config)

        app.dependency_overrides[_get_portfolio_settings] = lambda: config
        app.dependency_overrides[_get_scheduler] = lambda: scheduler

        try:
            response = client.post(
                "/api/v1/rebalancing/schedule/toggle",
                json={"enabled": True},
            )
            assert response.status_code == 200

            data = response.json()
            assert data["enabled"] is True
            assert data["next_run_at"] is not None
        finally:
            app.dependency_overrides.pop(_get_portfolio_settings, None)
            app.dependency_overrides.pop(_get_scheduler, None)

    def test_toggle_disable(self) -> None:
        """활성 → 비활성화"""
        config = _test_config(rebalance_enabled=True)
        scheduler = RebalanceScheduler(config)

        app.dependency_overrides[_get_portfolio_settings] = lambda: config
        app.dependency_overrides[_get_scheduler] = lambda: scheduler

        try:
            response = client.post(
                "/api/v1/rebalancing/schedule/toggle",
                json={"enabled": False},
            )
            assert response.status_code == 200

            data = response.json()
            assert data["enabled"] is False
            assert data["next_run_at"] is None
        finally:
            app.dependency_overrides.pop(_get_portfolio_settings, None)
            app.dependency_overrides.pop(_get_scheduler, None)


# ───────────────── GET /history ─────────────────


class TestHistoryEndpoint:
    """리밸런싱 내역 조회 테스트"""

    def test_history_empty(self) -> None:
        """DB에 내역이 없을 때 빈 목록 반환"""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 0

        async def _mock_db():  # type: ignore[no-untyped-def]
            session = MagicMock()
            session.execute = AsyncMock(
                side_effect=[mock_result, mock_count_result],
            )
            yield session

        app.dependency_overrides[get_db] = _mock_db

        try:
            response = client.get("/api/v1/rebalancing/history?page=1&size=10")
            assert response.status_code == 200

            data = response.json()
            assert data["items"] == []
            assert data["total"] == 0
        finally:
            app.dependency_overrides.pop(get_db, None)

    def test_history_detail_not_found(self) -> None:
        """존재하지 않는 ID 조회 시 404"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        async def _mock_db():  # type: ignore[no-untyped-def]
            session = MagicMock()
            session.execute = AsyncMock(return_value=mock_result)
            yield session

        app.dependency_overrides[get_db] = _mock_db

        try:
            response = client.get("/api/v1/rebalancing/history/999999")
            assert response.status_code == 404

            data = response.json()
            assert data["error"]["code"] == "NOT_FOUND"
        finally:
            app.dependency_overrides.pop(get_db, None)


# ───────────────── OpenAPI 태그 확인 ─────────────────


class TestOpenAPITag:
    """OpenAPI 스키마에 Rebalancing 태그가 등록되었는지 확인"""

    def test_rebalancing_tag_exists(self) -> None:
        """Rebalancing 태그가 OpenAPI 스키마에 존재"""
        response = client.get("/openapi.json")
        assert response.status_code == 200

        schema = response.json()
        tag_names = [t["name"] for t in schema.get("tags", [])]
        assert "Rebalancing" in tag_names

    def test_rebalancing_paths_exist(self) -> None:
        """리밸런싱 관련 경로가 OpenAPI 스키마에 존재"""
        response = client.get("/openapi.json")
        assert response.status_code == 200

        paths = response.json().get("paths", {})
        assert "/api/v1/rebalancing/execute" in paths
        assert "/api/v1/rebalancing/history" in paths
        assert "/api/v1/rebalancing/schedule" in paths
        assert "/api/v1/rebalancing/schedule/toggle" in paths

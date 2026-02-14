"""알림 API 엔드포인트 테스트"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from src.api.alerts import get_db
from src.main import app
from src.models.schema import AlertRule as DBAlertRule

client = TestClient(app)


# ─────────────────── Helper ─────────────────────


def _create_mock_db() -> MagicMock:
    """Mock DB 세션 생성"""
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
    db.execute = AsyncMock()
    return db


async def _mock_db_generator():  # type: ignore[no-untyped-def]
    """DB 세션 제너레이터 (dependency override용)"""
    db = _create_mock_db()
    yield db


# ─────────────────── Tests ─────────────────────


def test_create_alert() -> None:
    """알림 규칙 생성 테스트"""
    db = _create_mock_db()

    # flush 후 refresh에서 id 할당
    async def _refresh_side_effect(obj: DBAlertRule) -> None:
        if obj.id is None:
            obj.id = 1

    db.refresh.side_effect = _refresh_side_effect

    async def _mock_db_gen():  # type: ignore[no-untyped-def]
        yield db

    app.dependency_overrides[get_db] = _mock_db_gen

    try:
        payload = {
            "stock_code": "005930",
            "stock_name": "삼성전자",
            "condition": "stop_loss",
            "threshold": 70000.0,
            "cooldown_minutes": 60,
        }

        response = client.post("/api/v1/alerts", json=payload)
        assert response.status_code == 200

        data = response.json()
        assert data["stock_code"] == "005930"
        assert data["stock_name"] == "삼성전자"
        assert data["condition"] == "stop_loss"
        assert data["threshold"] == 70000.0
        assert data["is_active"] is True
        assert data["cooldown_minutes"] == 60
        assert "created_at" in data
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_list_alerts() -> None:
    """알림 규칙 목록 조회 테스트"""
    db = _create_mock_db()

    rule1 = DBAlertRule(
        id=1,
        stock_code="005930",
        stock_name="삼성전자",
        condition="stop_loss",
        threshold=70000.0,
        is_active=True,
        cooldown_minutes=60,
        created_at=datetime.now(UTC),
        last_triggered_at=None,
    )
    rule2 = DBAlertRule(
        id=2,
        stock_code="000660",
        stock_name="SK하이닉스",
        condition="target_price",
        threshold=150000.0,
        is_active=True,
        cooldown_minutes=60,
        created_at=datetime.now(UTC),
        last_triggered_at=None,
    )

    mock_result = MagicMock()
    mock_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[rule2, rule1])))
    db.execute.return_value = mock_result

    async def _mock_db_gen():  # type: ignore[no-untyped-def]
        yield db

    app.dependency_overrides[get_db] = _mock_db_gen

    try:
        response = client.get("/api/v1/alerts")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 2
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_get_alert_by_id() -> None:
    """특정 알림 규칙 조회 테스트"""
    db = _create_mock_db()

    rule = DBAlertRule(
        id=1,
        stock_code="005930",
        stock_name="삼성전자",
        condition="stop_loss",
        threshold=70000.0,
        is_active=True,
        cooldown_minutes=60,
        created_at=datetime.now(UTC),
        last_triggered_at=None,
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=rule)
    db.execute.return_value = mock_result

    async def _mock_db_gen():  # type: ignore[no-untyped-def]
        yield db

    app.dependency_overrides[get_db] = _mock_db_gen

    try:
        response = client.get("/api/v1/alerts/1")
        assert response.status_code == 200

        data = response.json()
        assert data["id"] == 1
        assert data["stock_code"] == "005930"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_get_alert_not_found() -> None:
    """존재하지 않는 알림 규칙 조회 테스트"""
    db = _create_mock_db()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=None)
    db.execute.return_value = mock_result

    async def _mock_db_gen():  # type: ignore[no-untyped-def]
        yield db

    app.dependency_overrides[get_db] = _mock_db_gen

    try:
        response = client.get("/api/v1/alerts/99999")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_delete_alert() -> None:
    """알림 규칙 삭제 테스트"""
    db = _create_mock_db()

    rule = DBAlertRule(
        id=1,
        stock_code="005930",
        condition="stop_loss",
        threshold=70000.0,
        is_active=True,
        cooldown_minutes=60,
        created_at=datetime.now(UTC),
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=rule)
    db.execute.return_value = mock_result

    async def _mock_db_gen():  # type: ignore[no-untyped-def]
        yield db

    app.dependency_overrides[get_db] = _mock_db_gen

    try:
        response = client.delete("/api/v1/alerts/1")
        assert response.status_code == 200

        data = response.json()
        assert "message" in data
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_delete_alert_not_found() -> None:
    """존재하지 않는 알림 규칙 삭제 테스트"""
    db = _create_mock_db()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=None)
    db.execute.return_value = mock_result

    async def _mock_db_gen():  # type: ignore[no-untyped-def]
        yield db

    app.dependency_overrides[get_db] = _mock_db_gen

    try:
        response = client.delete("/api/v1/alerts/99999")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_toggle_alert() -> None:
    """알림 규칙 활성/비활성 토글 테스트"""
    db = _create_mock_db()

    rule = DBAlertRule(
        id=1,
        stock_code="005930",
        condition="stop_loss",
        threshold=70000.0,
        is_active=True,
        cooldown_minutes=60,
        created_at=datetime.now(UTC),
    )

    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=rule)
    db.execute.return_value = mock_result

    async def _mock_db_gen():  # type: ignore[no-untyped-def]
        yield db

    app.dependency_overrides[get_db] = _mock_db_gen

    try:
        response = client.put("/api/v1/alerts/1/toggle")
        assert response.status_code == 200

        data = response.json()
        assert data["id"] == 1
        assert data["is_active"] is False
        assert "비활성화" in data["message"]
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_check_alert_stop_loss() -> None:
    """수동 알림 체크 테스트 - 손절가"""
    db = _create_mock_db()

    rule = DBAlertRule(
        id=1,
        stock_code="005930",
        condition="stop_loss",
        threshold=70000.0,
        is_active=True,
        cooldown_minutes=60,
        created_at=datetime.now(UTC),
        last_triggered_at=None,
    )

    mock_result = MagicMock()
    mock_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[rule])))
    db.execute.return_value = mock_result

    async def _mock_db_gen():  # type: ignore[no-untyped-def]
        yield db

    app.dependency_overrides[get_db] = _mock_db_gen

    try:
        payload = {
            "stock_code": "005930",
            "current_price": 69000.0,
        }

        response = client.post("/api/v1/alerts/check", json=payload)
        assert response.status_code == 200

        data = response.json()
        assert data["stock_code"] == "005930"
        assert data["current_price"] == 69000.0
        assert data["triggered_count"] == 1
        assert len(data["triggered_alerts"]) == 1
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_check_alert_no_trigger() -> None:
    """수동 알림 체크 테스트 - 트리거 안됨"""
    db = _create_mock_db()

    rule = DBAlertRule(
        id=1,
        stock_code="005930",
        condition="stop_loss",
        threshold=70000.0,
        is_active=True,
        cooldown_minutes=60,
        created_at=datetime.now(UTC),
        last_triggered_at=None,
    )

    mock_result = MagicMock()
    mock_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[rule])))
    db.execute.return_value = mock_result

    async def _mock_db_gen():  # type: ignore[no-untyped-def]
        yield db

    app.dependency_overrides[get_db] = _mock_db_gen

    try:
        payload = {
            "stock_code": "005930",
            "current_price": 71000.0,  # 손절가보다 높음
        }

        response = client.post("/api/v1/alerts/check", json=payload)
        assert response.status_code == 200

        data = response.json()
        assert data["triggered_count"] == 0
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_check_alert_no_active_rules() -> None:
    """수동 알림 체크 테스트 - 활성 규칙 없음"""
    db = _create_mock_db()

    mock_result = MagicMock()
    mock_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    db.execute.return_value = mock_result

    async def _mock_db_gen():  # type: ignore[no-untyped-def]
        yield db

    app.dependency_overrides[get_db] = _mock_db_gen

    try:
        payload = {
            "stock_code": "999999",
            "current_price": 10000.0,
        }

        response = client.post("/api/v1/alerts/check", json=payload)
        assert response.status_code == 200

        data = response.json()
        assert data["triggered_count"] == 0
        assert "활성화된 알림 규칙이 없습니다" in data["message"]
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_create_alert_validation_error() -> None:
    """알림 규칙 생성 검증 오류 테스트"""
    db = _create_mock_db()

    async def _mock_db_gen():  # type: ignore[no-untyped-def]
        yield db

    app.dependency_overrides[get_db] = _mock_db_gen

    try:
        payload = {
            "stock_code": "",  # 빈 문자열
            "condition": "stop_loss",
            "threshold": 70000.0,
        }

        response = client.post("/api/v1/alerts", json=payload)
        assert response.status_code == 422
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_create_alert_invalid_threshold() -> None:
    """알림 규칙 생성 - 잘못된 임계값 테스트"""
    db = _create_mock_db()

    async def _mock_db_gen():  # type: ignore[no-untyped-def]
        yield db

    app.dependency_overrides[get_db] = _mock_db_gen

    try:
        payload = {
            "stock_code": "005930",
            "condition": "stop_loss",
            "threshold": -1000.0,  # 음수
        }

        response = client.post("/api/v1/alerts", json=payload)
        assert response.status_code == 422
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_create_alert_invalid_condition() -> None:
    """알림 규칙 생성 - 잘못된 조건 타입 테스트"""
    db = _create_mock_db()

    async def _mock_db_gen():  # type: ignore[no-untyped-def]
        yield db

    app.dependency_overrides[get_db] = _mock_db_gen

    try:
        payload = {
            "stock_code": "005930",
            "condition": "invalid_condition",
            "threshold": 70000.0,
        }

        response = client.post("/api/v1/alerts", json=payload)
        assert response.status_code == 422
    finally:
        app.dependency_overrides.pop(get_db, None)

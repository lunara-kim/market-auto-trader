"""긴급 정지 + 안전장치 테스트"""

from src.strategy.safety import DailyLossGuard, EmergencyStop, SafetyCheck


class TestEmergencyStop:
    def test_initial_state(self):
        es = EmergencyStop()
        assert not es.is_stopped()
        assert es.status()["emergency_stopped"] is False

    def test_stop_and_resume(self):
        es = EmergencyStop()
        es.stop("테스트 정지")
        assert es.is_stopped()
        assert es.status()["reason"] == "테스트 정지"
        assert es.status()["stopped_at"] is not None

        es.resume()
        assert not es.is_stopped()
        assert es.status()["reason"] == ""


class TestDailyLossGuard:
    def test_no_trigger_on_profit(self):
        es = EmergencyStop()
        guard = DailyLossGuard(es, max_daily_loss_pct=0.03)
        guard.reset_daily(1_000_000)
        triggered = guard.record_pnl(10_000)
        assert not triggered
        assert not es.is_stopped()

    def test_trigger_on_excess_loss(self):
        es = EmergencyStop()
        guard = DailyLossGuard(es, max_daily_loss_pct=0.03)
        guard.reset_daily(1_000_000)
        triggered = guard.record_pnl(-31_000)  # 3.1% loss
        assert triggered
        assert es.is_stopped()

    def test_cumulative_loss(self):
        es = EmergencyStop()
        guard = DailyLossGuard(es, max_daily_loss_pct=0.05)
        guard.reset_daily(1_000_000)
        guard.record_pnl(-20_000)
        assert not es.is_stopped()
        guard.record_pnl(-20_000)
        assert not es.is_stopped()
        triggered = guard.record_pnl(-15_000)  # cumulative: -55,000 = 5.5%
        assert triggered
        assert es.is_stopped()

    def test_status(self):
        es = EmergencyStop()
        guard = DailyLossGuard(es, max_daily_loss_pct=0.03)
        guard.reset_daily(1_000_000)
        guard.record_pnl(-10_000)
        status = guard.status()
        assert status["daily_pnl"] == -10_000
        assert status["max_daily_loss_pct"] == 0.03


class TestSafetyCheck:
    def test_safe_when_all_clear(self):
        es = EmergencyStop()
        guard = DailyLossGuard(es)
        guard.reset_daily(1_000_000)
        sc = SafetyCheck(es, guard)
        result = sc.check(order_amount=100_000, available_cash=500_000)
        assert result.safe
        assert len(result.reasons) == 0

    def test_blocked_when_emergency_stopped(self):
        es = EmergencyStop()
        es.stop("test")
        guard = DailyLossGuard(es)
        guard.reset_daily(1_000_000)
        sc = SafetyCheck(es, guard)
        result = sc.check()
        assert not result.safe
        assert "긴급 정지" in result.reasons[0]

    def test_blocked_when_insufficient_cash(self):
        es = EmergencyStop()
        guard = DailyLossGuard(es)
        guard.reset_daily(1_000_000)
        sc = SafetyCheck(es, guard)
        result = sc.check(order_amount=500_000, available_cash=100_000)
        assert not result.safe
        assert "잔고 부족" in result.reasons[0]


class TestSafetyAPI:
    def test_emergency_stop_api(self):
        from fastapi.testclient import TestClient
        from src.api.safety import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        # 정지
        resp = client.post("/api/v1/safety/emergency-stop", json={"reason": "API 테스트"})
        assert resp.status_code == 200
        assert resp.json()["emergency_stopped"] is True

        # 상태
        resp = client.get("/api/v1/safety/status")
        assert resp.status_code == 200
        assert resp.json()["emergency_stopped"] is True

        # 재개
        resp = client.post("/api/v1/safety/resume")
        assert resp.status_code == 200
        assert resp.json()["emergency_stopped"] is False

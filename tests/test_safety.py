"""안전장치(SafetyCheck) 테스트 — Phase 5 버전"""

from src.strategy.safety import SafetyCheck, SafetyCheckResult


class TestSafetyCheck:
    def test_safe_when_all_clear(self):
        sc = SafetyCheck(emergency_stop=False)
        result = sc.check(order_amount=100_000, available_cash=500_000)
        assert result.safe
        assert len(result.reasons) == 0

    def test_blocked_when_emergency_stopped(self):
        sc = SafetyCheck(emergency_stop=True)
        result = sc.check(order_amount=100_000, available_cash=500_000)
        assert not result.safe
        assert any("emergency_stop" in r for r in result.reasons)

    def test_blocked_when_insufficient_cash(self):
        sc = SafetyCheck(emergency_stop=False)
        result = sc.check(order_amount=500_000, available_cash=100_000)
        assert not result.safe
        assert any("현금" in r for r in result.reasons)

    def test_multiple_reasons(self):
        sc = SafetyCheck(emergency_stop=True)
        result = sc.check(order_amount=500_000, available_cash=100_000)
        assert not result.safe
        assert len(result.reasons) == 2

    def test_result_dataclass(self):
        r = SafetyCheckResult(safe=True, reasons=[])
        assert r.safe
        assert r.reasons == []

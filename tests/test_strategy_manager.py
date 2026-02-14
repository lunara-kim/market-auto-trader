"""
StrategyManager 유닛 테스트

복합 전략 매니저의 등록/제거/투표/백테스트 비교 기능을 검증합니다.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.strategy.base import BaseStrategy
from src.strategy.strategy_manager import (
    CombinedSignal,
    CombinedSignalType,
    StrategyManager,
    VotingMethod,
)


# ─────────────────────────────────────────────
# 테스트용 더미 전략
# ─────────────────────────────────────────────

class DummyStrategy(BaseStrategy):
    """테스트용 더미 전략 — 고정된 신호와 백테스트 결과를 반환"""

    def __init__(
        self,
        name: str,
        signal: str = "hold",
        strength: float = 0.0,
        backtest_return: float = 0.0,
    ) -> None:
        super().__init__(name=name)
        self._signal = signal
        self._strength = strength
        self._backtest_return = backtest_return

    def analyze(self, market_data: dict[str, Any]) -> dict[str, Any]:
        return {"analyzed": True, "data": market_data}

    def generate_signal(self, analysis_result: dict[str, Any]) -> dict[str, Any]:
        return {
            "signal": self._signal,
            "strength": self._strength,
            "reason": f"Dummy {self._signal}",
            "strategy_name": self.name,
            "timestamp": "2026-01-01T00:00:00+00:00",
        }

    def backtest(
        self,
        historical_data: list[dict[str, Any]],
        initial_capital: float,
    ) -> dict[str, Any]:
        final = initial_capital * (1 + self._backtest_return / 100)
        return {
            "strategy_name": self.name,
            "initial_capital": initial_capital,
            "final_capital": round(final, 2),
            "total_return": self._backtest_return,
            "total_trades": 5,
            "winning_trades": 3,
            "losing_trades": 2,
            "win_rate": 60.0,
            "max_drawdown": 5.0,
            "sharpe_ratio": 1.2,
            "trades": [],
            "equity_curve": [],
        }


class ErrorStrategy(BaseStrategy):
    """항상 예외를 발생시키는 전략"""

    def __init__(self, name: str = "ErrorBot") -> None:
        super().__init__(name=name)

    def analyze(self, market_data: dict[str, Any]) -> dict[str, Any]:
        msg = "분석 실패!"
        raise RuntimeError(msg)

    def generate_signal(self, analysis_result: dict[str, Any]) -> dict[str, Any]:
        msg = "신호 생성 실패!"
        raise RuntimeError(msg)

    def backtest(
        self,
        historical_data: list[dict[str, Any]],
        initial_capital: float,
    ) -> dict[str, Any]:
        msg = "백테스트 실패!"
        raise RuntimeError(msg)


# ─────────────────────────────────────────────
# 등록 / 제거 / 설정
# ─────────────────────────────────────────────

class TestStrategyRegistration:
    """전략 등록/제거/활성화/가중치 테스트"""

    def test_register_strategy(self) -> None:
        mgr = StrategyManager()
        s = DummyStrategy("Alpha")
        mgr.register(s, weight=2.0)

        assert "Alpha" in mgr.strategies
        assert mgr.strategies["Alpha"].weight == 2.0
        assert mgr.strategies["Alpha"].enabled is True

    def test_register_duplicate_overwrites(self) -> None:
        mgr = StrategyManager()
        s1 = DummyStrategy("Alpha", signal="buy")
        s2 = DummyStrategy("Alpha", signal="sell")
        mgr.register(s1, weight=1.0)
        mgr.register(s2, weight=3.0)

        assert mgr.strategies["Alpha"].weight == 3.0

    def test_register_zero_weight_raises(self) -> None:
        mgr = StrategyManager()
        s = DummyStrategy("Alpha")
        with pytest.raises(ValueError, match="0보다 커야"):
            mgr.register(s, weight=0)

    def test_register_negative_weight_raises(self) -> None:
        mgr = StrategyManager()
        s = DummyStrategy("Alpha")
        with pytest.raises(ValueError, match="0보다 커야"):
            mgr.register(s, weight=-1.0)

    def test_unregister(self) -> None:
        mgr = StrategyManager()
        mgr.register(DummyStrategy("Alpha"))
        assert mgr.unregister("Alpha") is True
        assert "Alpha" not in mgr.strategies

    def test_unregister_nonexistent(self) -> None:
        mgr = StrategyManager()
        assert mgr.unregister("Ghost") is False

    def test_set_enabled(self) -> None:
        mgr = StrategyManager()
        mgr.register(DummyStrategy("Alpha"))

        mgr.set_enabled("Alpha", False)
        assert mgr.strategies["Alpha"].enabled is False
        assert len(mgr.active_strategies) == 0

        mgr.set_enabled("Alpha", True)
        assert mgr.strategies["Alpha"].enabled is True
        assert len(mgr.active_strategies) == 1

    def test_set_enabled_nonexistent(self) -> None:
        mgr = StrategyManager()
        assert mgr.set_enabled("Ghost", True) is False

    def test_set_weight(self) -> None:
        mgr = StrategyManager()
        mgr.register(DummyStrategy("Alpha"), weight=1.0)
        mgr.set_weight("Alpha", 5.0)
        assert mgr.strategies["Alpha"].weight == 5.0

    def test_set_weight_zero_raises(self) -> None:
        mgr = StrategyManager()
        mgr.register(DummyStrategy("Alpha"))
        with pytest.raises(ValueError, match="0보다 커야"):
            mgr.set_weight("Alpha", 0)

    def test_set_weight_nonexistent(self) -> None:
        mgr = StrategyManager()
        assert mgr.set_weight("Ghost", 1.0) is False

    def test_list_strategies(self) -> None:
        mgr = StrategyManager()
        mgr.register(DummyStrategy("Alpha"), weight=1.0)
        mgr.register(DummyStrategy("Beta"), weight=2.0, enabled=False)

        result = mgr.list_strategies()
        assert len(result) == 2
        names = {s["name"] for s in result}
        assert names == {"Alpha", "Beta"}

    def test_active_strategies_excludes_disabled(self) -> None:
        mgr = StrategyManager()
        mgr.register(DummyStrategy("Alpha"), enabled=True)
        mgr.register(DummyStrategy("Beta"), enabled=False)
        mgr.register(DummyStrategy("Gamma"), enabled=True)

        active = mgr.active_strategies
        assert len(active) == 2
        assert "Beta" not in active


# ─────────────────────────────────────────────
# 다수결 투표 (MAJORITY)
# ─────────────────────────────────────────────

class TestMajorityVoting:
    """다수결 투표 방식 테스트"""

    def test_clear_buy_majority(self) -> None:
        """3개 중 2개 buy → BUY"""
        mgr = StrategyManager(voting_method=VotingMethod.MAJORITY)
        mgr.register(DummyStrategy("A", signal="buy", strength=0.8))
        mgr.register(DummyStrategy("B", signal="buy", strength=0.6))
        mgr.register(DummyStrategy("C", signal="sell", strength=0.5))

        result = mgr.generate_combined_signal({"prices": []})
        assert result.signal == CombinedSignalType.BUY
        assert result.confidence > 0

    def test_clear_sell_majority(self) -> None:
        """3개 중 2개 sell → SELL"""
        mgr = StrategyManager(voting_method=VotingMethod.MAJORITY)
        mgr.register(DummyStrategy("A", signal="sell", strength=0.7))
        mgr.register(DummyStrategy("B", signal="sell", strength=0.9))
        mgr.register(DummyStrategy("C", signal="buy", strength=0.3))

        result = mgr.generate_combined_signal({"prices": []})
        assert result.signal == CombinedSignalType.SELL

    def test_no_majority_hold(self) -> None:
        """buy 1, sell 1, hold 1 → 과반 미달 HOLD"""
        mgr = StrategyManager(voting_method=VotingMethod.MAJORITY)
        mgr.register(DummyStrategy("A", signal="buy", strength=0.8))
        mgr.register(DummyStrategy("B", signal="sell", strength=0.8))
        mgr.register(DummyStrategy("C", signal="hold", strength=0.0))

        result = mgr.generate_combined_signal({"prices": []})
        assert result.signal == CombinedSignalType.HOLD

    def test_all_hold(self) -> None:
        """모두 hold → HOLD"""
        mgr = StrategyManager(voting_method=VotingMethod.MAJORITY)
        mgr.register(DummyStrategy("A", signal="hold"))
        mgr.register(DummyStrategy("B", signal="hold"))

        result = mgr.generate_combined_signal({"prices": []})
        assert result.signal == CombinedSignalType.HOLD
        assert result.confidence == 0.0

    def test_empty_strategies_hold(self) -> None:
        """전략 없음 → HOLD"""
        mgr = StrategyManager()
        result = mgr.generate_combined_signal({"prices": []})
        assert result.signal == CombinedSignalType.HOLD
        assert "활성 전략 없음" in result.reason

    def test_min_confidence_filter(self) -> None:
        """과반 달성해도 확신도 미달이면 HOLD"""
        mgr = StrategyManager(
            voting_method=VotingMethod.MAJORITY,
            min_confidence=0.9,
        )
        mgr.register(DummyStrategy("A", signal="buy", strength=0.3))
        mgr.register(DummyStrategy("B", signal="buy", strength=0.2))
        mgr.register(DummyStrategy("C", signal="hold"))

        result = mgr.generate_combined_signal({"prices": []})
        # confidence = (2/3) * avg(0.3,0.2) = 0.667 * 0.25 ≈ 0.167 < 0.9
        assert result.signal == CombinedSignalType.HOLD
        assert "HOLD 전환" in result.reason

    def test_single_strategy_buy(self) -> None:
        """전략 1개만 등록 — 1/1 = 100% → BUY"""
        mgr = StrategyManager(voting_method=VotingMethod.MAJORITY)
        mgr.register(DummyStrategy("Solo", signal="buy", strength=0.7))

        result = mgr.generate_combined_signal({"prices": []})
        assert result.signal == CombinedSignalType.BUY

    def test_two_buy_two_sell_no_majority(self) -> None:
        """2 buy, 2 sell → 과반 미달 HOLD"""
        mgr = StrategyManager(voting_method=VotingMethod.MAJORITY)
        mgr.register(DummyStrategy("A", signal="buy", strength=0.8))
        mgr.register(DummyStrategy("B", signal="buy", strength=0.6))
        mgr.register(DummyStrategy("C", signal="sell", strength=0.7))
        mgr.register(DummyStrategy("D", signal="sell", strength=0.9))

        result = mgr.generate_combined_signal({"prices": []})
        assert result.signal == CombinedSignalType.HOLD


# ─────────────────────────────────────────────
# 가중 투표 (WEIGHTED)
# ─────────────────────────────────────────────

class TestWeightedVoting:
    """가중 투표 방식 테스트"""

    def test_weighted_buy_wins(self) -> None:
        """가중치 높은 buy가 이기는 경우"""
        mgr = StrategyManager(voting_method=VotingMethod.WEIGHTED)
        mgr.register(DummyStrategy("A", signal="buy", strength=0.8), weight=3.0)
        mgr.register(DummyStrategy("B", signal="sell", strength=0.5), weight=1.0)

        result = mgr.generate_combined_signal({"prices": []})
        assert result.signal == CombinedSignalType.BUY
        assert result.confidence > 0

    def test_weighted_sell_wins(self) -> None:
        """가중치 높은 sell이 이기는 경우"""
        mgr = StrategyManager(voting_method=VotingMethod.WEIGHTED)
        mgr.register(DummyStrategy("A", signal="buy", strength=0.3), weight=1.0)
        mgr.register(DummyStrategy("B", signal="sell", strength=0.9), weight=5.0)

        result = mgr.generate_combined_signal({"prices": []})
        assert result.signal == CombinedSignalType.SELL

    def test_weighted_all_hold(self) -> None:
        """모두 hold → score 0 → HOLD"""
        mgr = StrategyManager(voting_method=VotingMethod.WEIGHTED)
        mgr.register(DummyStrategy("A", signal="hold", strength=0.0))
        mgr.register(DummyStrategy("B", signal="hold", strength=0.0))

        result = mgr.generate_combined_signal({"prices": []})
        assert result.signal == CombinedSignalType.HOLD

    def test_weighted_min_confidence_filter(self) -> None:
        """가중 투표에서 확신도 미달 → HOLD 전환"""
        mgr = StrategyManager(
            voting_method=VotingMethod.WEIGHTED,
            min_confidence=0.8,
        )
        mgr.register(DummyStrategy("A", signal="buy", strength=0.2), weight=1.0)
        mgr.register(DummyStrategy("B", signal="sell", strength=0.1), weight=1.0)

        result = mgr.generate_combined_signal({"prices": []})
        # buy score = (1*0.2)/2 = 0.1, sell score = (1*0.1)/2 = 0.05 → buy wins but 0.1 < 0.8
        assert result.signal == CombinedSignalType.HOLD

    def test_weighted_override_method(self) -> None:
        """호출 시 voting_method 오버라이드"""
        mgr = StrategyManager(voting_method=VotingMethod.MAJORITY)
        mgr.register(DummyStrategy("A", signal="buy", strength=0.9), weight=5.0)
        mgr.register(DummyStrategy("B", signal="sell", strength=0.1), weight=1.0)

        # WEIGHTED로 오버라이드
        result = mgr.generate_combined_signal(
            {"prices": []},
            voting_method=VotingMethod.WEIGHTED,
        )
        assert result.voting_method == VotingMethod.WEIGHTED
        assert result.signal == CombinedSignalType.BUY


# ─────────────────────────────────────────────
# 만장일치 투표 (UNANIMOUS)
# ─────────────────────────────────────────────

class TestUnanimousVoting:
    """만장일치 투표 방식 테스트"""

    def test_unanimous_buy(self) -> None:
        """모두 buy → BUY"""
        mgr = StrategyManager(voting_method=VotingMethod.UNANIMOUS)
        mgr.register(DummyStrategy("A", signal="buy", strength=0.8))
        mgr.register(DummyStrategy("B", signal="buy", strength=0.6))

        result = mgr.generate_combined_signal({"prices": []})
        assert result.signal == CombinedSignalType.BUY
        assert result.confidence > 0

    def test_unanimous_sell(self) -> None:
        """모두 sell → SELL"""
        mgr = StrategyManager(voting_method=VotingMethod.UNANIMOUS)
        mgr.register(DummyStrategy("A", signal="sell", strength=0.7))
        mgr.register(DummyStrategy("B", signal="sell", strength=0.9))

        result = mgr.generate_combined_signal({"prices": []})
        assert result.signal == CombinedSignalType.SELL

    def test_unanimous_disagreement_hold(self) -> None:
        """buy + sell 혼재 → 만장일치 실패 → HOLD"""
        mgr = StrategyManager(voting_method=VotingMethod.UNANIMOUS)
        mgr.register(DummyStrategy("A", signal="buy", strength=0.8))
        mgr.register(DummyStrategy("B", signal="sell", strength=0.8))

        result = mgr.generate_combined_signal({"prices": []})
        assert result.signal == CombinedSignalType.HOLD
        assert "만장일치 실패" in result.reason

    def test_unanimous_all_hold(self) -> None:
        """모두 hold → HOLD"""
        mgr = StrategyManager(voting_method=VotingMethod.UNANIMOUS)
        mgr.register(DummyStrategy("A", signal="hold"))
        mgr.register(DummyStrategy("B", signal="hold"))

        result = mgr.generate_combined_signal({"prices": []})
        assert result.signal == CombinedSignalType.HOLD
        assert "모든 전략이 HOLD" in result.reason

    def test_unanimous_min_confidence(self) -> None:
        """만장일치 달성했으나 확신도 미달 → HOLD"""
        mgr = StrategyManager(
            voting_method=VotingMethod.UNANIMOUS,
            min_confidence=0.8,
        )
        mgr.register(DummyStrategy("A", signal="buy", strength=0.3))
        mgr.register(DummyStrategy("B", signal="buy", strength=0.2))

        result = mgr.generate_combined_signal({"prices": []})
        # confidence = avg(0.3, 0.2) = 0.25 < 0.8
        assert result.signal == CombinedSignalType.HOLD


# ─────────────────────────────────────────────
# 에러 핸들링
# ─────────────────────────────────────────────

class TestErrorHandling:
    """전략 에러 발생 시 graceful 처리"""

    def test_error_strategy_becomes_hold(self) -> None:
        """예외 발생 전략은 hold로 처리"""
        mgr = StrategyManager(voting_method=VotingMethod.MAJORITY)
        mgr.register(DummyStrategy("A", signal="buy", strength=0.8))
        mgr.register(DummyStrategy("B", signal="buy", strength=0.6))
        mgr.register(ErrorStrategy("Broken"))

        result = mgr.generate_combined_signal({"prices": []})
        # A=buy, B=buy, Broken=hold(error) → 2/3 buy → BUY
        assert result.signal == CombinedSignalType.BUY

        # 에러 전략의 신호에 error 플래그 존재
        error_signals = [
            s for s in result.individual_signals if s.get("error")
        ]
        assert len(error_signals) == 1

    def test_all_error_strategies_hold(self) -> None:
        """모든 전략이 에러 → HOLD"""
        mgr = StrategyManager(voting_method=VotingMethod.MAJORITY)
        mgr.register(ErrorStrategy("Broken1"))
        mgr.register(ErrorStrategy("Broken2"))

        result = mgr.generate_combined_signal({"prices": []})
        assert result.signal == CombinedSignalType.HOLD


# ─────────────────────────────────────────────
# 백테스트 비교
# ─────────────────────────────────────────────

class TestBacktestComparison:
    """compare_backtest 메서드 테스트"""

    def _make_data(self, n: int = 50) -> list[dict[str, Any]]:
        """더미 히스토리컬 데이터 생성"""
        return [
            {"date": f"2025-01-{i+1:02d}", "close": 50000 + i * 100}
            for i in range(n)
        ]

    def test_compare_ranking(self) -> None:
        """수익률 순으로 랭킹 정렬"""
        mgr = StrategyManager()
        mgr.register(DummyStrategy("Low", backtest_return=5.0))
        mgr.register(DummyStrategy("High", backtest_return=15.0))
        mgr.register(DummyStrategy("Mid", backtest_return=10.0))

        result = mgr.compare_backtest(self._make_data(), 10_000_000)

        assert result["best_strategy"] == "High"
        ranking = result["ranking"]
        assert len(ranking) == 3
        assert ranking[0]["strategy_name"] == "High"
        assert ranking[0]["rank"] == 1
        assert ranking[1]["strategy_name"] == "Mid"
        assert ranking[2]["strategy_name"] == "Low"

    def test_compare_summary(self) -> None:
        """요약 통계 확인"""
        mgr = StrategyManager()
        mgr.register(DummyStrategy("A", backtest_return=20.0))
        mgr.register(DummyStrategy("B", backtest_return=-5.0))

        result = mgr.compare_backtest(self._make_data(), 10_000_000)
        summary = result["summary"]

        assert summary["total_strategies"] == 2
        assert summary["best_return"] == 20.0
        assert summary["worst_return"] == -5.0
        assert summary["average_return"] == 7.5
        assert summary["initial_capital"] == 10_000_000

    def test_compare_empty_strategies(self) -> None:
        """전략 없으면 빈 결과"""
        mgr = StrategyManager()
        result = mgr.compare_backtest(self._make_data(), 10_000_000)

        assert result["results"] == []
        assert result["ranking"] == []
        assert result["best_strategy"] is None

    def test_compare_with_error_strategy(self) -> None:
        """에러 전략은 수익률 0으로 처리"""
        mgr = StrategyManager()
        mgr.register(DummyStrategy("Good", backtest_return=12.0))
        mgr.register(ErrorStrategy("Broken"))

        result = mgr.compare_backtest(self._make_data(), 10_000_000)

        assert result["best_strategy"] == "Good"
        assert len(result["ranking"]) == 2
        # 에러 전략은 수익률 0
        broken_rank = next(
            r for r in result["ranking"] if r["strategy_name"] == "Broken"
        )
        assert broken_rank["total_return"] == 0.0

    def test_compare_disabled_excluded(self) -> None:
        """비활성 전략은 백테스트에서 제외"""
        mgr = StrategyManager()
        mgr.register(DummyStrategy("Active", backtest_return=10.0))
        mgr.register(
            DummyStrategy("Disabled", backtest_return=50.0),
            enabled=False,
        )

        result = mgr.compare_backtest(self._make_data(), 10_000_000)
        assert len(result["results"]) == 1
        assert result["best_strategy"] == "Active"


# ─────────────────────────────────────────────
# CombinedSignal 직렬화
# ─────────────────────────────────────────────

class TestCombinedSignalSerialization:
    """CombinedSignal.to_dict 테스트"""

    def test_to_dict_fields(self) -> None:
        cs = CombinedSignal(
            signal=CombinedSignalType.BUY,
            confidence=0.75,
            voting_method=VotingMethod.MAJORITY,
            individual_signals=[{"signal": "buy"}],
            vote_summary={"counts": {"buy": 2}},
            reason="test",
            timestamp="2026-01-01T00:00:00Z",
        )
        d = cs.to_dict()
        assert d["signal"] == "buy"
        assert d["confidence"] == 0.75
        assert d["voting_method"] == "majority"
        assert d["reason"] == "test"
        assert len(d["individual_signals"]) == 1

    def test_to_dict_confidence_rounding(self) -> None:
        cs = CombinedSignal(
            signal=CombinedSignalType.SELL,
            confidence=0.123456789,
            voting_method=VotingMethod.WEIGHTED,
        )
        d = cs.to_dict()
        assert d["confidence"] == 0.1235  # 소수점 4자리

    def test_disabled_strategy_not_in_signal(self) -> None:
        """비활성 전략은 신호 생성에 참여하지 않음"""
        mgr = StrategyManager(voting_method=VotingMethod.MAJORITY)
        mgr.register(DummyStrategy("A", signal="buy", strength=0.8))
        mgr.register(DummyStrategy("B", signal="sell", strength=0.8))
        mgr.register(
            DummyStrategy("C", signal="buy", strength=0.8),
            enabled=False,
        )

        result = mgr.generate_combined_signal({"prices": []})
        # A=buy, B=sell, C=disabled → 1 buy, 1 sell → no majority → HOLD
        assert result.signal == CombinedSignalType.HOLD
        assert len(result.individual_signals) == 2  # C 제외

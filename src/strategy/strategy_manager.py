"""
복합 전략 매니저 (StrategyManager)

여러 전략의 신호를 종합하여 최종 매매 결정을 내리는 매니저 클래스입니다.

투표 방식:
- majority: 다수결 (과반수가 같은 방향이면 신호)
- weighted: 가중 투표 (전략별 가중치 × 신호 강도)
- unanimous: 만장일치 (모든 전략이 같은 방향이어야 신호)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from src.strategy.base import BaseStrategy
from src.utils.logger import get_logger

logger = get_logger(__name__)


class VotingMethod(str, Enum):
    """투표 방식"""

    MAJORITY = "majority"      # 다수결
    WEIGHTED = "weighted"      # 가중 투표
    UNANIMOUS = "unanimous"    # 만장일치


class CombinedSignalType(str, Enum):
    """종합 매매 신호"""

    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class StrategyEntry:
    """등록된 전략 정보"""

    strategy: BaseStrategy
    weight: float = 1.0        # 가중치 (weighted 모드에서 사용)
    enabled: bool = True       # 활성화 여부

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.strategy.name,
            "weight": self.weight,
            "enabled": self.enabled,
            "type": type(self.strategy).__name__,
        }


@dataclass
class CombinedSignal:
    """종합 신호 결과"""

    signal: CombinedSignalType
    confidence: float          # 종합 확신도 (0.0 ~ 1.0)
    voting_method: VotingMethod
    individual_signals: list[dict[str, Any]] = field(default_factory=list)
    vote_summary: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal": self.signal.value,
            "confidence": round(self.confidence, 4),
            "voting_method": self.voting_method.value,
            "individual_signals": self.individual_signals,
            "vote_summary": self.vote_summary,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }


class StrategyManager:
    """
    복합 전략 매니저

    여러 전략을 등록하고, 각 전략의 신호를 종합하여
    최종 매매 결정을 내립니다.
    """

    def __init__(
        self,
        voting_method: VotingMethod = VotingMethod.MAJORITY,
        min_confidence: float = 0.0,
    ) -> None:
        """
        Args:
            voting_method: 신호 종합 방식
            min_confidence: 최소 확신도 (이하면 HOLD)
        """
        self._strategies: dict[str, StrategyEntry] = {}
        self.voting_method = voting_method
        self.min_confidence = min_confidence
        logger.info(
            "StrategyManager 초기화: 투표=%s, 최소확신도=%.2f",
            voting_method.value, min_confidence,
        )

    @property
    def strategies(self) -> dict[str, StrategyEntry]:
        """등록된 전략 목록"""
        return dict(self._strategies)

    @property
    def active_strategies(self) -> dict[str, StrategyEntry]:
        """활성 전략만"""
        return {k: v for k, v in self._strategies.items() if v.enabled}

    def register(
        self,
        strategy: BaseStrategy,
        weight: float = 1.0,
        enabled: bool = True,
    ) -> None:
        """
        전략 등록

        Args:
            strategy: BaseStrategy 인스턴스
            weight: 가중치 (0.0 초과)
            enabled: 활성화 여부
        """
        if weight <= 0:
            msg = f"가중치는 0보다 커야 합니다: {weight}"
            raise ValueError(msg)
        if strategy.name in self._strategies:
            logger.warning("전략 '%s' 이미 등록됨 — 덮어씁니다", strategy.name)

        self._strategies[strategy.name] = StrategyEntry(
            strategy=strategy,
            weight=weight,
            enabled=enabled,
        )
        logger.info(
            "전략 등록: %s (가중치=%.2f, 활성=%s)",
            strategy.name, weight, enabled,
        )

    def unregister(self, name: str) -> bool:
        """전략 제거. 성공 시 True."""
        if name in self._strategies:
            del self._strategies[name]
            logger.info("전략 제거: %s", name)
            return True
        logger.warning("전략 '%s'을(를) 찾을 수 없습니다", name)
        return False

    def set_enabled(self, name: str, enabled: bool) -> bool:
        """전략 활성/비활성 전환. 성공 시 True."""
        if name in self._strategies:
            self._strategies[name].enabled = enabled
            logger.info("전략 '%s' %s", name, "활성화" if enabled else "비활성화")
            return True
        return False

    def set_weight(self, name: str, weight: float) -> bool:
        """전략 가중치 변경. 성공 시 True."""
        if weight <= 0:
            msg = f"가중치는 0보다 커야 합니다: {weight}"
            raise ValueError(msg)
        if name in self._strategies:
            self._strategies[name].weight = weight
            logger.info("전략 '%s' 가중치 → %.2f", name, weight)
            return True
        return False

    def list_strategies(self) -> list[dict[str, Any]]:
        """등록된 전략 목록 반환"""
        return [entry.to_dict() for entry in self._strategies.values()]

    def generate_combined_signal(
        self,
        market_data: dict[str, Any],
        voting_method: VotingMethod | None = None,
    ) -> CombinedSignal:
        """
        모든 활성 전략의 신호를 수집하고 종합

        Args:
            market_data: 시장 데이터 (analyze()에 전달)
            voting_method: 투표 방식 (None이면 기본값 사용)

        Returns:
            CombinedSignal — 종합 매매 신호
        """
        method = voting_method or self.voting_method
        active = self.active_strategies

        if not active:
            logger.warning("활성 전략이 없습니다")
            return CombinedSignal(
                signal=CombinedSignalType.HOLD,
                confidence=0.0,
                voting_method=method,
                reason="활성 전략 없음",
                timestamp=datetime.now(UTC).isoformat(),
            )

        # 1) 각 전략에서 신호 수집
        individual_signals: list[dict[str, Any]] = []
        for name, entry in active.items():
            try:
                analysis = entry.strategy.analyze(market_data)
                signal = entry.strategy.generate_signal(analysis)
                signal["weight"] = entry.weight
                individual_signals.append(signal)
                logger.info(
                    "[%s] 신호: %s (강도=%.2f)",
                    name, signal.get("signal", "?"), signal.get("strength", 0),
                )
            except Exception:
                logger.exception("전략 '%s' 신호 생성 실패", name)
                individual_signals.append({
                    "signal": "hold",
                    "strength": 0.0,
                    "reason": f"전략 '{name}' 오류 발생",
                    "strategy_name": name,
                    "weight": entry.weight,
                    "error": True,
                })

        # 2) 투표
        if method == VotingMethod.MAJORITY:
            return self._vote_majority(individual_signals, method)
        if method == VotingMethod.WEIGHTED:
            return self._vote_weighted(individual_signals, method)
        return self._vote_unanimous(individual_signals, method)

    def _vote_majority(
        self,
        signals: list[dict[str, Any]],
        method: VotingMethod,
    ) -> CombinedSignal:
        """다수결 투표"""
        counts: dict[str, int] = {"buy": 0, "sell": 0, "hold": 0}
        strengths: dict[str, list[float]] = {"buy": [], "sell": [], "hold": []}

        for sig in signals:
            direction = sig.get("signal", "hold")
            if direction not in counts:
                direction = "hold"
            counts[direction] += 1
            strengths[direction].append(sig.get("strength", 0.0))

        total = len(signals)
        # 과반수 판단 (hold 제외)
        best_direction = "hold"
        best_count = 0
        for direction in ("buy", "sell"):
            if counts[direction] > total / 2:
                best_direction = direction
                best_count = counts[direction]

        # hold가 과반이거나 buy/sell 둘 다 과반 못 넘기면 hold
        if best_direction == "hold":
            confidence = 0.0
            reason = (
                f"다수결: buy={counts['buy']}, sell={counts['sell']}, "
                f"hold={counts['hold']} — 과반수 미달"
            )
        else:
            avg_strength = (
                sum(strengths[best_direction]) / len(strengths[best_direction])
                if strengths[best_direction] else 0.0
            )
            confidence = (best_count / total) * avg_strength
            reason = (
                f"다수결 {best_direction.upper()}: "
                f"{best_count}/{total} 전략 동의 "
                f"(평균 강도 {avg_strength:.2f})"
            )

        # min_confidence 체크
        final_signal = CombinedSignalType(best_direction)
        if confidence < self.min_confidence and final_signal != CombinedSignalType.HOLD:
            reason += f" → 확신도({confidence:.2f}) < 최소({self.min_confidence:.2f}), HOLD 전환"
            final_signal = CombinedSignalType.HOLD

        return CombinedSignal(
            signal=final_signal,
            confidence=confidence,
            voting_method=method,
            individual_signals=signals,
            vote_summary={"counts": counts, "total": total},
            reason=reason,
            timestamp=datetime.now(UTC).isoformat(),
        )

    def _vote_weighted(
        self,
        signals: list[dict[str, Any]],
        method: VotingMethod,
    ) -> CombinedSignal:
        """가중 투표: 각 전략의 (가중치 × 신호 강도)를 합산"""
        scores: dict[str, float] = {"buy": 0.0, "sell": 0.0, "hold": 0.0}
        total_weight = 0.0

        for sig in signals:
            direction = sig.get("signal", "hold")
            if direction not in scores:
                direction = "hold"
            weight = sig.get("weight", 1.0)
            strength = sig.get("strength", 0.0)
            scores[direction] += weight * strength
            total_weight += weight

        # 정규화
        if total_weight > 0:
            for k in scores:
                scores[k] /= total_weight

        # 최고 점수 방향 (hold 제외 — hold는 기본값)
        best_direction = "hold"
        best_score = 0.0
        for direction in ("buy", "sell"):
            if scores[direction] > best_score:
                best_direction = direction
                best_score = scores[direction]

        confidence = best_score
        reason = (
            f"가중투표: buy={scores['buy']:.3f}, sell={scores['sell']:.3f}, "
            f"hold={scores['hold']:.3f} → {best_direction.upper()} "
            f"(확신도 {confidence:.3f})"
        )

        final_signal = CombinedSignalType(best_direction)
        if confidence < self.min_confidence and final_signal != CombinedSignalType.HOLD:
            reason += " → 확신도 미달, HOLD 전환"
            final_signal = CombinedSignalType.HOLD

        return CombinedSignal(
            signal=final_signal,
            confidence=confidence,
            voting_method=method,
            individual_signals=signals,
            vote_summary={
                "scores": {k: round(v, 4) for k, v in scores.items()},
                "total_weight": round(total_weight, 4),
            },
            reason=reason,
            timestamp=datetime.now(UTC).isoformat(),
        )

    def _vote_unanimous(
        self,
        signals: list[dict[str, Any]],
        method: VotingMethod,
    ) -> CombinedSignal:
        """만장일치: 모든 전략이 같은 방향이어야 신호"""
        directions = [
            sig.get("signal", "hold")
            for sig in signals
            if sig.get("signal", "hold") != "hold"
        ]

        if not directions:
            return CombinedSignal(
                signal=CombinedSignalType.HOLD,
                confidence=0.0,
                voting_method=method,
                individual_signals=signals,
                vote_summary={"unanimous": False, "directions": []},
                reason="모든 전략이 HOLD",
                timestamp=datetime.now(UTC).isoformat(),
            )

        unique_directions = set(directions)
        if len(unique_directions) == 1:
            direction = directions[0]
            avg_strength = sum(
                sig.get("strength", 0.0)
                for sig in signals
                if sig.get("signal", "hold") == direction
            ) / len(directions)
            confidence = avg_strength  # 만장일치이므로 강도 평균이 확신도

            final_signal = CombinedSignalType(direction)
            reason = (
                f"만장일치 {direction.upper()}: "
                f"{len(directions)}개 전략 합의 "
                f"(평균 강도 {avg_strength:.2f})"
            )

            if confidence < self.min_confidence and final_signal != CombinedSignalType.HOLD:
                reason += " → 확신도 미달, HOLD 전환"
                final_signal = CombinedSignalType.HOLD

            return CombinedSignal(
                signal=final_signal,
                confidence=confidence,
                voting_method=method,
                individual_signals=signals,
                vote_summary={
                    "unanimous": True,
                    "direction": direction,
                    "count": len(directions),
                },
                reason=reason,
                timestamp=datetime.now(UTC).isoformat(),
            )

        # 방향 불일치
        return CombinedSignal(
            signal=CombinedSignalType.HOLD,
            confidence=0.0,
            voting_method=method,
            individual_signals=signals,
            vote_summary={
                "unanimous": False,
                "directions": list(unique_directions),
            },
            reason=f"만장일치 실패: {unique_directions} — HOLD",
            timestamp=datetime.now(UTC).isoformat(),
        )

    def compare_backtest(
        self,
        historical_data: list[dict[str, Any]],
        initial_capital: float,
    ) -> dict[str, Any]:
        """
        모든 활성 전략의 백테스트 성과를 비교

        Args:
            historical_data: 과거 시장 데이터
            initial_capital: 초기 자본금

        Returns:
            {
                "results": [...],     # 전략별 백테스트 결과
                "ranking": [...],     # 수익률 순 랭킹
                "best_strategy": str, # 최고 수익률 전략
                "summary": {...},     # 전체 요약
            }
        """
        active = self.active_strategies
        if not active:
            return {
                "results": [],
                "ranking": [],
                "best_strategy": None,
                "summary": {"message": "활성 전략 없음"},
            }

        results: list[dict[str, Any]] = []
        for name, entry in active.items():
            try:
                bt_result = entry.strategy.backtest(historical_data, initial_capital)
                bt_result["weight"] = entry.weight
                results.append(bt_result)
                logger.info(
                    "[%s] 백테스트: 수익률=%.2f%%, 승률=%.1f%%, MDD=%.2f%%",
                    name,
                    bt_result.get("total_return", 0),
                    bt_result.get("win_rate", 0),
                    bt_result.get("max_drawdown", 0),
                )
            except Exception:
                logger.exception("전략 '%s' 백테스트 실패", name)
                results.append({
                    "strategy_name": name,
                    "error": "백테스트 실패",
                    "total_return": 0.0,
                    "weight": entry.weight,
                })

        # 수익률 순 랭킹
        ranking = sorted(
            results,
            key=lambda r: r.get("total_return", 0.0),
            reverse=True,
        )
        ranking_summary = [
            {
                "rank": i + 1,
                "strategy_name": r.get("strategy_name", "?"),
                "total_return": round(r.get("total_return", 0.0), 2),
                "win_rate": round(r.get("win_rate", 0.0), 2),
                "max_drawdown": round(r.get("max_drawdown", 0.0), 2),
                "sharpe_ratio": round(r.get("sharpe_ratio", 0.0), 4),
                "total_trades": r.get("total_trades", 0),
            }
            for i, r in enumerate(ranking)
        ]

        best = ranking[0] if ranking else {}
        avg_return = (
            sum(r.get("total_return", 0.0) for r in results) / len(results)
            if results else 0.0
        )

        return {
            "results": results,
            "ranking": ranking_summary,
            "best_strategy": best.get("strategy_name"),
            "summary": {
                "total_strategies": len(results),
                "best_return": round(best.get("total_return", 0.0), 2),
                "worst_return": round(
                    ranking[-1].get("total_return", 0.0), 2,
                ) if ranking else 0.0,
                "average_return": round(avg_return, 2),
                "initial_capital": initial_capital,
            },
        }

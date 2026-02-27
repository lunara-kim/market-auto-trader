"""
레짐 엔진 — Fear & Greed 지수 기반 시장 레짐 분류

시장을 Risk-Off / Neutral / Risk-On으로 분류하고,
각 레짐에서 허용되는 전략을 결정합니다.
"""

from __future__ import annotations

from enum import Enum

from src.utils.logger import get_logger

logger = get_logger(__name__)


class MarketRegime(Enum):
    """시장 레짐"""

    RISK_OFF = "risk_off"  # 공포 구간 (F&G < 25)
    NEUTRAL = "neutral"  # 중립 (25 <= F&G < 75)
    RISK_ON = "risk_on"  # 탐욕 구간 (F&G >= 75)


class RegimeEngine:
    """Fear & Greed 지수 기반 레짐 분류 엔진"""

    # 레짐별 허용 전략
    _ALLOWED_STRATEGIES: dict[MarketRegime, list[str]] = {
        MarketRegime.RISK_OFF: ["mean_reversion"],
        MarketRegime.NEUTRAL: ["mean_reversion", "trend_following"],
        MarketRegime.RISK_ON: ["trend_following"],
    }

    def classify(self, fear_greed_score: int) -> MarketRegime:
        """Fear & Greed 점수 → 레짐 분류"""
        if fear_greed_score < 25:
            regime = MarketRegime.RISK_OFF
        elif fear_greed_score >= 75:
            regime = MarketRegime.RISK_ON
        else:
            regime = MarketRegime.NEUTRAL

        logger.info(
            "레짐 분류: F&G=%d → %s",
            fear_greed_score,
            regime.value,
        )
        return regime

    def get_allowed_strategies(self, regime: MarketRegime) -> list[str]:
        """레짐에서 허용되는 전략 목록"""
        return self._ALLOWED_STRATEGIES[regime]

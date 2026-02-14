"""
복합 전략 매니저 API 라우터

등록된 전략 목록 조회, 복합 신호 생성, 전략별 성과 비교 엔드포인트를 제공합니다.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.strategy.bollinger_bands import BollingerBandStrategy, BollingerConfig
from src.strategy.moving_average import MAConfig, MAType, MovingAverageCrossover
from src.strategy.rsi import RSIConfig, RSIStrategy
from src.strategy.strategy_manager import (
    StrategyManager,
    VotingMethod,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/strategies", tags=["Strategies"])


# ─────────────────────────────────────────────
# Pydantic 스키마
# ─────────────────────────────────────────────

class VotingMethodEnum(str, Enum):
    """투표 방식"""

    MAJORITY = "majority"
    WEIGHTED = "weighted"
    UNANIMOUS = "unanimous"


class StrategyConfigRequest(BaseModel):
    """개별 전략 설정"""

    name: str = Field(description="전략 종류: ma, rsi, bollinger")
    weight: float = Field(default=1.0, gt=0, description="가중치")
    enabled: bool = Field(default=True, description="활성화 여부")
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="전략별 파라미터 (예: {short_window: 5, long_window: 20})",
    )


class CombinedSignalRequest(BaseModel):
    """복합 신호 생성 요청"""

    prices: list[float] = Field(
        min_length=2,
        description="종가 리스트 (오래된 순)",
    )
    dates: list[str] = Field(
        default_factory=list,
        description="날짜 리스트 (선택)",
    )
    stock_code: str = Field(default="000000", description="종목 코드")
    strategies: list[StrategyConfigRequest] = Field(
        min_length=1,
        description="사용할 전략 목록",
    )
    voting_method: VotingMethodEnum = Field(
        default=VotingMethodEnum.MAJORITY,
        description="투표 방식",
    )
    min_confidence: float = Field(
        default=0.0,
        ge=0,
        le=1,
        description="최소 확신도 (이하면 HOLD)",
    )


class IndividualSignalResponse(BaseModel):
    """개별 전략 신호"""

    signal: str
    strength: float
    reason: str | None = None
    strategy_name: str | None = None
    weight: float = 1.0
    error: bool = False


class CombinedSignalResponse(BaseModel):
    """복합 신호 응답"""

    signal: str = Field(description="buy / sell / hold")
    confidence: float = Field(description="종합 확신도 (0.0 ~ 1.0)")
    voting_method: str
    individual_signals: list[IndividualSignalResponse]
    vote_summary: dict[str, Any] = Field(default_factory=dict)
    reason: str
    timestamp: str


class BacktestCompareRequest(BaseModel):
    """전략 성과 비교 요청"""

    historical_data: list[dict[str, Any]] = Field(
        min_length=10,
        description="과거 시장 데이터 [{date, close, ...}, ...] (오래된 순)",
    )
    initial_capital: float = Field(
        default=10_000_000,
        gt=0,
        description="초기 자본금 (원)",
    )
    strategies: list[StrategyConfigRequest] = Field(
        min_length=1,
        description="비교할 전략 목록",
    )


class RankingItem(BaseModel):
    """랭킹 항목"""

    rank: int
    strategy_name: str
    total_return: float = Field(description="총 수익률 (%)")
    win_rate: float = Field(description="승률 (%)")
    max_drawdown: float = Field(description="최대 낙폭 (%)")
    sharpe_ratio: float = Field(description="샤프 비율")
    total_trades: int


class CompareSummary(BaseModel):
    """비교 요약"""

    total_strategies: int
    best_return: float
    worst_return: float
    average_return: float
    initial_capital: float


class BacktestCompareResponse(BaseModel):
    """전략 성과 비교 응답"""

    ranking: list[RankingItem]
    best_strategy: str | None
    summary: CompareSummary


# ─────────────────────────────────────────────
# 헬퍼: 전략 팩토리
# ─────────────────────────────────────────────

def _build_strategy(config: StrategyConfigRequest) -> Any:
    """
    StrategyConfigRequest로부터 BaseStrategy 인스턴스 생성

    지원 전략:
    - ma: MovingAverageCrossover (params: short_window, long_window, ma_type)
    - rsi: RSIStrategy (params: period, overbought, oversold)
    - bollinger: BollingerBandStrategy (params: period, num_std)
    """
    name = config.name.lower()
    params = config.params

    if name == "ma":
        ma_type_str = params.get("ma_type", "sma")
        ma_type = MAType.EMA if ma_type_str.lower() == "ema" else MAType.SMA
        ma_config = MAConfig(
            short_window=params.get("short_window", 5),
            long_window=params.get("long_window", 20),
            ma_type=ma_type,
        )
        return MovingAverageCrossover(ma_config)

    if name == "rsi":
        rsi_config = RSIConfig(
            period=params.get("period", 14),
            overbought=params.get("overbought", 70.0),
            oversold=params.get("oversold", 30.0),
            signal_threshold=params.get("signal_threshold", 0.0),
        )
        return RSIStrategy(rsi_config)

    if name == "bollinger":
        bb_config = BollingerConfig(
            period=params.get("period", 20),
            num_std=params.get("num_std", 2.0),
            signal_threshold=params.get("signal_threshold", 0.0),
        )
        return BollingerBandStrategy(bb_config)

    msg = f"지원하지 않는 전략: '{config.name}'. 사용 가능: ma, rsi, bollinger"
    raise ValueError(msg)


def _build_manager(
    strategies: list[StrategyConfigRequest],
    voting_method: VotingMethodEnum = VotingMethodEnum.MAJORITY,
    min_confidence: float = 0.0,
) -> StrategyManager:
    """요청에서 StrategyManager 인스턴스 구성"""
    mgr = StrategyManager(
        voting_method=VotingMethod(voting_method.value),
        min_confidence=min_confidence,
    )
    for s_config in strategies:
        strategy = _build_strategy(s_config)
        mgr.register(strategy, weight=s_config.weight, enabled=s_config.enabled)
    return mgr


# ─────────────────────────────────────────────
# 엔드포인트
# ─────────────────────────────────────────────

@router.get(
    "/available",
    summary="사용 가능한 전략 목록",
    description="현재 지원하는 매매 전략 종류와 설정 가능한 파라미터를 조회합니다.",
)
async def list_available_strategies() -> list[dict[str, Any]]:
    """사용 가능한 전략 목록 반환"""
    return [
        {
            "name": "ma",
            "display_name": "이동평균 교차 (Moving Average Crossover)",
            "params": {
                "short_window": {"type": "int", "default": 5, "description": "단기 기간"},
                "long_window": {"type": "int", "default": 20, "description": "장기 기간"},
                "ma_type": {"type": "str", "default": "sma", "options": ["sma", "ema"]},
            },
        },
        {
            "name": "rsi",
            "display_name": "RSI (Relative Strength Index)",
            "params": {
                "period": {"type": "int", "default": 14, "description": "RSI 계산 기간"},
                "overbought": {"type": "float", "default": 70.0, "description": "과매수 기준"},
                "oversold": {"type": "float", "default": 30.0, "description": "과매도 기준"},
                "signal_threshold": {"type": "float", "default": 0.0},
            },
        },
        {
            "name": "bollinger",
            "display_name": "볼린저 밴드 (Bollinger Bands)",
            "params": {
                "period": {"type": "int", "default": 20, "description": "이동평균 기간"},
                "num_std": {"type": "float", "default": 2.0, "description": "표준편차 배수"},
                "signal_threshold": {"type": "float", "default": 0.0},
            },
        },
    ]


@router.post(
    "/signal",
    response_model=CombinedSignalResponse,
    summary="복합 전략 신호 생성",
    description=(
        "여러 전략을 동시에 실행하고, 투표 방식(다수결/가중/만장일치)으로 "
        "종합 매매 신호를 생성합니다."
    ),
)
async def generate_combined_signal(
    req: CombinedSignalRequest,
) -> CombinedSignalResponse:
    """복합 전략 신호 생성 엔드포인트"""
    logger.info(
        "복합 신호 요청: 전략 %d개, 투표=%s, 최소확신도=%.2f",
        len(req.strategies),
        req.voting_method.value,
        req.min_confidence,
    )

    try:
        mgr = _build_manager(
            req.strategies,
            voting_method=req.voting_method,
            min_confidence=req.min_confidence,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    market_data = {
        "prices": req.prices,
        "dates": req.dates,
        "stock_code": req.stock_code,
    }

    combined = mgr.generate_combined_signal(market_data)
    result_dict = combined.to_dict()

    individual = [
        IndividualSignalResponse(
            signal=s.get("signal", "hold"),
            strength=s.get("strength", 0.0),
            reason=s.get("reason"),
            strategy_name=s.get("strategy_name"),
            weight=s.get("weight", 1.0),
            error=s.get("error", False),
        )
        for s in result_dict["individual_signals"]
    ]

    logger.info(
        "복합 신호 결과: %s (확신도=%.4f)",
        combined.signal.value,
        combined.confidence,
    )

    return CombinedSignalResponse(
        signal=result_dict["signal"],
        confidence=result_dict["confidence"],
        voting_method=result_dict["voting_method"],
        individual_signals=individual,
        vote_summary=result_dict["vote_summary"],
        reason=result_dict["reason"],
        timestamp=result_dict["timestamp"],
    )


@router.post(
    "/compare",
    response_model=BacktestCompareResponse,
    summary="전략별 성과 비교",
    description=(
        "여러 전략을 동일한 과거 데이터로 백테스팅하고, "
        "수익률·승률·MDD·샤프 비율을 비교합니다."
    ),
)
async def compare_strategies(
    req: BacktestCompareRequest,
) -> BacktestCompareResponse:
    """전략별 성과 비교 엔드포인트"""
    logger.info(
        "전략 비교 요청: %d개 전략, 자본금=%.0f, 데이터=%d일",
        len(req.strategies),
        req.initial_capital,
        len(req.historical_data),
    )

    try:
        mgr = _build_manager(req.strategies)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    result = mgr.compare_backtest(req.historical_data, req.initial_capital)

    ranking = [RankingItem(**r) for r in result["ranking"]]
    summary = CompareSummary(**result["summary"])

    logger.info(
        "전략 비교 완료: 최고 %s (%.2f%%), 최저 %.2f%%",
        result["best_strategy"],
        summary.best_return,
        summary.worst_return,
    )

    return BacktestCompareResponse(
        ranking=ranking,
        best_strategy=result["best_strategy"],
        summary=summary,
    )

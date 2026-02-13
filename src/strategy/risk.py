"""리스크 관리 유틸리티

단일 종목 포지션 크기 산출 및 일간 손실 제한 여부 판단을 담당한다.

이 모듈은 전략/서비스 레이어에서 공통으로 사용할 수 있는
순수 계산 로직만 포함하며, 외부 API 호출이나 DB I/O는 수행하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import floor

from src.exceptions import StrategyError, ValidationError
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class PositionRiskConfig:
    """포지션 단위 리스크 설정값

    Attributes:
        max_risk_per_trade_pct: 한 번의 트레이드에서 계좌 전체 대비 허용하는 최대 손실 비율(%)
        max_position_size_pct: 한 종목에 투입 가능한 최대 자본 비율(%)
    """

    max_risk_per_trade_pct: float = 1.0
    max_position_size_pct: float = 20.0

    def __post_init__(self) -> None:
        if self.max_risk_per_trade_pct <= 0:
            raise ValidationError(
                "max_risk_per_trade_pct는 0보다 커야 합니다.",
                detail={"max_risk_per_trade_pct": self.max_risk_per_trade_pct},
            )
        if self.max_position_size_pct <= 0:
            raise ValidationError(
                "max_position_size_pct는 0보다 커야 합니다.",
                detail={"max_position_size_pct": self.max_position_size_pct},
            )


def calculate_position_size(
    equity: float,
    entry_price: float,
    stop_loss_price: float,
    config: PositionRiskConfig | None = None,
) -> int:
    """손절 가격을 기준으로 허용 가능한 최대 포지션 수량을 계산한다.

    단순화된 롱 포지션 기준 규칙:

    - 손절가는 진입가보다 낮아야 한다.
    - 1트레이드당 최대 손실액 = ``equity * max_risk_per_trade_pct / 100``
    - 종목당 최대 배분 자본 = ``equity * max_position_size_pct / 100``
    - 수량은 두 제약(손실 한도, 포지션 크기 한도)을 모두 만족하는 정수로 내림한다.

    Args:
        equity: 현재 계좌 평가액
        entry_price: 진입 예정 가격
        stop_loss_price: 손절 가격
        config: 포지션 리스크 설정 (미지정 시 기본 값 사용)

    Returns:
        허용 가능한 최대 주문 수량 (정수)

    Raises:
        ValidationError: 입력값이 잘못되었거나 수량이 1 미만인 경우
    """

    if config is None:
        config = PositionRiskConfig()

    if equity <= 0:
        raise ValidationError(
            "계좌 평가액(equity)은 0보다 커야 합니다.",
            detail={"equity": equity},
        )

    if entry_price <= 0 or stop_loss_price <= 0:
        raise ValidationError(
            "진입가와 손절가는 0보다 커야 합니다.",
            detail={
                "entry_price": entry_price,
                "stop_loss_price": stop_loss_price,
            },
        )

    if stop_loss_price >= entry_price:
        raise ValidationError(
            "손절가는 진입가보다 낮아야 합니다.",
            detail={
                "entry_price": entry_price,
                "stop_loss_price": stop_loss_price,
            },
        )

    risk_per_share = entry_price - stop_loss_price
    max_risk_amount = equity * (config.max_risk_per_trade_pct / 100)
    max_position_capital = equity * (config.max_position_size_pct / 100)

    # 손실 한도 기준 수량
    qty_by_risk = floor(max_risk_amount / risk_per_share)

    # 포지션 크기 한도 기준 수량
    qty_by_position_size = floor(max_position_capital / entry_price)

    quantity = min(qty_by_risk, qty_by_position_size)

    if quantity < 1:
        raise ValidationError(
            "리스크 설정을 만족하는 최소 1주의 포지션을 만들 수 없습니다.",
            detail={
                "equity": equity,
                "entry_price": entry_price,
                "stop_loss_price": stop_loss_price,
                "max_risk_per_trade_pct": config.max_risk_per_trade_pct,
                "max_position_size_pct": config.max_position_size_pct,
                "risk_per_share": risk_per_share,
                "max_risk_amount": max_risk_amount,
                "max_position_capital": max_position_capital,
            },
        )

    logger.info(
        "포지션 크기 계산: equity=%.2f, entry=%.2f, stop=%.2f, risk_per_trade=%.2f%%, "
        "position_size=%.2f%%, quantity=%d",
        equity,
        entry_price,
        stop_loss_price,
        config.max_risk_per_trade_pct,
        config.max_position_size_pct,
        quantity,
    )

    return quantity


def check_daily_loss_limit(
    peak_equity: float,
    current_equity: float,
    max_daily_loss_pct: float,
) -> bool:
    """일 단위 최대 손실 한도를 초과했는지 여부를 판단한다.

    단순 규칙:

    - ``drawdown_pct = (peak_equity - current_equity) / peak_equity * 100``
    - ``drawdown_pct``가 ``max_daily_loss_pct``를 초과하면 거래를 중단해야 한다.

    Args:
        peak_equity: 해당 일자의 최고 계좌 평가액
        current_equity: 현재 계좌 평가액
        max_daily_loss_pct: 일 단위 허용 손실 한도(%)

    Returns:
        거래 계속 가능 여부 (True=계속, False=중단)

    Raises:
        ValidationError: 입력값이 잘못된 경우
        StrategyError: 손실 한도를 초과한 경우 (거래 중단 신호)
    """

    if peak_equity <= 0 or current_equity <= 0:
        raise ValidationError(
            "계좌 평가액은 0보다 커야 합니다.",
            detail={
                "peak_equity": peak_equity,
                "current_equity": current_equity,
            },
        )

    if max_daily_loss_pct <= 0:
        raise ValidationError(
            "max_daily_loss_pct는 0보다 커야 합니다.",
            detail={"max_daily_loss_pct": max_daily_loss_pct},
        )

    if current_equity > peak_equity:
        # 새로운 고점 갱신 → 손실 한도와 무관하게 거래 계속 가능
        logger.info(
            "계좌 고점 갱신: peak=%.2f → current=%.2f (손실 한도 미적용)",
            peak_equity,
            current_equity,
        )
        return True

    drawdown_pct = (peak_equity - current_equity) / peak_equity * 100

    logger.info(
        "일간 손실 체크: peak=%.2f, current=%.2f, drawdown=%.2f%%, limit=%.2f%%",
        peak_equity,
        current_equity,
        drawdown_pct,
        max_daily_loss_pct,
    )

    if drawdown_pct > max_daily_loss_pct:
        raise StrategyError(
            "일간 손실 한도를 초과했습니다. 오늘 거래를 중단해야 합니다.",
            detail={
                "peak_equity": peak_equity,
                "current_equity": current_equity,
                "drawdown_pct": drawdown_pct,
                "max_daily_loss_pct": max_daily_loss_pct,
            },
        )

    return True

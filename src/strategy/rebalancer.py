"""리밸런싱 엔진

포트폴리오 목표 비중에 맞춰 매수/매도 주문을 생성하는 순수 계산 로직.

이 모듈은 외부 API 호출 없이 현재 보유 종목과 목표 비중을 비교하여
리밸런싱 계획을 생성한다. 실제 주문 실행은 별도 서비스 레이어에서 처리한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import floor

from config.portfolio import PortfolioSettings
from src.exceptions import ValidationError
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class RebalanceOrder:
    """리밸런싱으로 생성된 개별 주문

    Attributes:
        stock_code: 종목코드
        side: 매수("buy") 또는 매도("sell")
        quantity: 주문 수량
        current_price: 현재가
        target_value_krw: 목표 포지션 금액 (원)
        reason: 주문 생성 사유
    """

    stock_code: str
    side: str  # "buy" or "sell"
    quantity: int
    current_price: float
    target_value_krw: float
    reason: str


@dataclass(slots=True)
class RebalancePlan:
    """리밸런싱 계획 전체

    Attributes:
        orders: 생성된 주문 목록 (매도 → 매수 순서)
        current_allocations: 현재 포트폴리오 비중(%)
        target_allocations: 목표 포트폴리오 비중(%)
        total_equity: 총 평가액 (원)
        cash_before: 리밸런싱 전 현금 (원)
        cash_after_sells: 매도 후 현금 (원)
        estimated_cash_after: 리밸런싱 후 예상 현금 (원)
        skipped_stocks: 임계값 미달로 스킵된 종목 목록
    """

    orders: list[RebalanceOrder] = field(default_factory=list)
    current_allocations: dict[str, float] = field(default_factory=dict)
    target_allocations: dict[str, float] = field(default_factory=dict)
    total_equity: float = 0.0
    cash_before: float = 0.0
    cash_after_sells: float = 0.0
    estimated_cash_after: float = 0.0
    skipped_stocks: list[str] = field(default_factory=list)

    @property
    def total_orders(self) -> int:
        """총 주문 개수"""
        return len(self.orders)

    @property
    def buy_orders(self) -> list[RebalanceOrder]:
        """매수 주문 목록"""
        return [o for o in self.orders if o.side == "buy"]

    @property
    def sell_orders(self) -> list[RebalanceOrder]:
        """매도 주문 목록"""
        return [o for o in self.orders if o.side == "sell"]

    @property
    def summary(self) -> dict[str, object]:
        """리밸런싱 요약 통계"""
        return {
            "total_orders": self.total_orders,
            "buy_orders": len(self.buy_orders),
            "sell_orders": len(self.sell_orders),
            "total_equity_krw": self.total_equity,
            "cash_before_krw": self.cash_before,
            "estimated_cash_after_krw": self.estimated_cash_after,
            "skipped_stocks": self.skipped_stocks,
        }


def calculate_current_allocations(
    holdings: list[dict],
    total_equity: float,
) -> dict[str, float]:
    """현재 포트폴리오 비중 계산

    Args:
        holdings: 보유 종목 목록 [{"stock_code": str, "quantity": int, "current_price": float}, ...]
        total_equity: 총 평가액 (원)

    Returns:
        종목코드별 현재 비중(%) dict

    Raises:
        ValidationError: 입력값이 잘못된 경우
    """
    if total_equity <= 0:
        raise ValidationError(
            "총 평가액(total_equity)은 0보다 커야 합니다.",
            detail={"total_equity": total_equity},
        )

    current_allocations: dict[str, float] = {}

    for holding in holdings:
        stock_code = holding.get("stock_code")
        quantity = holding.get("quantity", 0)
        current_price = holding.get("current_price", 0.0)

        if not stock_code:
            raise ValidationError(
                "보유 종목에 stock_code가 없습니다.",
                detail={"holding": holding},
            )

        if quantity <= 0 or current_price <= 0:
            logger.warning(
                "보유 종목 %s의 수량(%d) 또는 현재가(%.2f)가 유효하지 않아 스킵합니다.",
                stock_code,
                quantity,
                current_price,
            )
            continue

        position_value = quantity * current_price
        allocation_pct = (position_value / total_equity) * 100
        current_allocations[stock_code] = allocation_pct

    logger.info(
        "현재 포트폴리오 비중 계산 완료: %s (총 평가액: %.2f원)",
        current_allocations,
        total_equity,
    )

    return current_allocations


def generate_rebalance_plan(
    holdings: list[dict],
    cash: float,
    total_equity: float,
    config: PortfolioSettings,
) -> RebalancePlan:
    """목표 비중과 현재 비중을 비교하여 리밸런싱 계획 생성

    Args:
        holdings: 보유 종목 목록 [{"stock_code": str, "quantity": int, "current_price": float}, ...]
        cash: 현재 현금 (원)
        total_equity: 총 평가액 (원)
        config: 포트폴리오 설정

    Returns:
        리밸런싱 계획

    Raises:
        ValidationError: 입력값이 잘못된 경우
        StrategyError: 리밸런싱 실행 중 오류
    """
    if total_equity <= 0:
        raise ValidationError(
            "총 평가액(total_equity)은 0보다 커야 합니다.",
            detail={"total_equity": total_equity},
        )

    if cash < 0:
        raise ValidationError(
            "현금(cash)은 0 이상이어야 합니다.",
            detail={"cash": cash},
        )

    # 현재 비중 계산
    current_allocations = calculate_current_allocations(holdings, total_equity)

    # 목표 비중 복사 (config는 immutable)
    target_allocations = dict(config.target_allocations)

    plan = RebalancePlan(
        current_allocations=current_allocations,
        target_allocations=target_allocations,
        total_equity=total_equity,
        cash_before=cash,
    )

    # 보유 종목 맵 (빠른 조회용)
    holdings_map: dict[str, dict] = {
        h["stock_code"]: h for h in holdings if h.get("stock_code")
    }

    # ─── 1단계: 매도 주문 생성 (현금 확보) ───
    sell_orders: list[RebalanceOrder] = []
    cash_after_sells = cash

    for stock_code, current_pct in current_allocations.items():
        target_pct = target_allocations.get(stock_code, 0.0)
        diff_pct = current_pct - target_pct

        # threshold 모드: 임계값 미달 시 스킵
        if config.rebalance_mode == "threshold" and abs(diff_pct) < config.rebalance_threshold_pct:
            plan.skipped_stocks.append(stock_code)
            logger.debug(
                "종목 %s: 비중 차이(%.2f%%)가 임계값(%.2f%%) 미달로 스킵",
                stock_code,
                abs(diff_pct),
                config.rebalance_threshold_pct,
            )
            continue

        if diff_pct > 0:  # 현재 > 목표 → 매도
            holding = holdings_map.get(stock_code)
            if not holding:
                logger.warning("종목 %s는 현재 비중에 있으나 holdings에 없습니다.", stock_code)
                continue

            current_price = holding["current_price"]
            quantity = holding["quantity"]
            current_value = quantity * current_price
            target_value = total_equity * (target_pct / 100)
            value_to_sell = current_value - target_value

            # 최소 거래금액 필터
            if value_to_sell < config.min_trade_amount_krw:
                logger.debug(
                    "종목 %s: 매도 금액(%.2f원)이 최소 거래금액(%.2f원) 미달로 스킵",
                    stock_code,
                    value_to_sell,
                    config.min_trade_amount_krw,
                )
                continue

            # 최대 단일 주문 비율 제한
            max_order_value = total_equity * (config.max_single_order_pct / 100)
            if value_to_sell > max_order_value:
                logger.info(
                    "종목 %s: 매도 금액(%.2f원)이 최대 주문 비율(%.2f%%) 초과, %.2f원으로 제한",
                    stock_code,
                    value_to_sell,
                    config.max_single_order_pct,
                    max_order_value,
                )
                value_to_sell = max_order_value

            sell_qty = floor(value_to_sell / current_price)
            if sell_qty <= 0:
                continue

            order = RebalanceOrder(
                stock_code=stock_code,
                side="sell",
                quantity=sell_qty,
                current_price=current_price,
                target_value_krw=target_value,
                reason=f"현재 비중({current_pct:.2f}%) > 목표 비중({target_pct:.2f}%)",
            )
            sell_orders.append(order)
            cash_after_sells += sell_qty * current_price

            logger.info(
                "매도 주문 생성: %s %d주 @ %.2f원 (목표: %.2f%%, 현재: %.2f%%)",
                stock_code,
                sell_qty,
                current_price,
                target_pct,
                current_pct,
            )

    plan.cash_after_sells = cash_after_sells

    # ─── 2단계: 매수 주문 생성 (목표 비중 달성) ───
    buy_orders: list[RebalanceOrder] = []
    available_cash = cash_after_sells

    for stock_code, target_pct in target_allocations.items():
        current_pct = current_allocations.get(stock_code, 0.0)
        diff_pct = target_pct - current_pct

        # threshold 모드: 임계값 미달 시 스킵
        if config.rebalance_mode == "threshold" and abs(diff_pct) < config.rebalance_threshold_pct:
            if stock_code not in plan.skipped_stocks:
                plan.skipped_stocks.append(stock_code)
            logger.debug(
                "종목 %s: 비중 차이(%.2f%%)가 임계값(%.2f%%) 미달로 스킵",
                stock_code,
                abs(diff_pct),
                config.rebalance_threshold_pct,
            )
            continue

        if diff_pct > 0:  # 목표 > 현재 → 매수
            holding = holdings_map.get(stock_code)
            if holding:
                current_price = holding["current_price"]
            else:
                # 신규 종목: 현재가 정보 없음 → 스킵 (실제로는 외부에서 가격 조회 필요)
                logger.warning(
                    "종목 %s는 신규 종목이나 현재가 정보가 없어 스킵합니다.",
                    stock_code,
                )
                continue

            current_value = current_allocations.get(stock_code, 0.0) * total_equity / 100
            target_value = total_equity * (target_pct / 100)
            value_to_buy = target_value - current_value

            # 최소 거래금액 필터
            if value_to_buy < config.min_trade_amount_krw:
                logger.debug(
                    "종목 %s: 매수 금액(%.2f원)이 최소 거래금액(%.2f원) 미달로 스킵",
                    stock_code,
                    value_to_buy,
                    config.min_trade_amount_krw,
                )
                continue

            # 최대 단일 주문 비율 제한
            max_order_value = total_equity * (config.max_single_order_pct / 100)
            if value_to_buy > max_order_value:
                logger.info(
                    "종목 %s: 매수 금액(%.2f원)이 최대 주문 비율(%.2f%%) 초과, %.2f원으로 제한",
                    stock_code,
                    value_to_buy,
                    config.max_single_order_pct,
                    max_order_value,
                )
                value_to_buy = max_order_value

            # 현금 부족 체크
            if value_to_buy > available_cash:
                logger.warning(
                    "종목 %s: 매수 금액(%.2f원) > 가용 현금(%.2f원), 가용 현금으로 제한",
                    stock_code,
                    value_to_buy,
                    available_cash,
                )
                value_to_buy = available_cash

            buy_qty = floor(value_to_buy / current_price)
            if buy_qty <= 0:
                continue

            order = RebalanceOrder(
                stock_code=stock_code,
                side="buy",
                quantity=buy_qty,
                current_price=current_price,
                target_value_krw=target_value,
                reason=f"목표 비중({target_pct:.2f}%) > 현재 비중({current_pct:.2f}%)",
            )
            buy_orders.append(order)
            available_cash -= buy_qty * current_price

            logger.info(
                "매수 주문 생성: %s %d주 @ %.2f원 (목표: %.2f%%, 현재: %.2f%%)",
                stock_code,
                buy_qty,
                current_price,
                target_pct,
                current_pct,
            )

    plan.estimated_cash_after = available_cash

    # ─── 3단계: 주문 병합 (매도 → 매수 순서) ───
    plan.orders = sell_orders + buy_orders

    logger.info(
        "리밸런싱 계획 생성 완료: 매도 %d건, 매수 %d건, 스킵 %d종목",
        len(sell_orders),
        len(buy_orders),
        len(plan.skipped_stocks),
    )

    return plan

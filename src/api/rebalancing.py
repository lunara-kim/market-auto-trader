"""
리밸런싱 API 라우터

수동/자동 리밸런싱 실행, 내역 조회, 스케줄 관리 엔드포인트를 제공합니다.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config.portfolio import PortfolioSettings, portfolio_settings
from src.api.dependencies import get_db as _app_get_db
from src.api.schemas import (
    RebalanceDetailResponse,
    RebalanceExecuteRequest,
    RebalanceExecuteResponse,
    RebalanceHistoryItem,
    RebalanceHistoryResponse,
    RebalanceOrderDetailItem,
    RebalanceScheduleResponse,
    RebalanceToggleRequest,
)
from src.exceptions import NotFoundError
from src.models.schema import RebalanceHistory, RebalanceOrderDetail
from src.strategy.rebalance_scheduler import RebalanceScheduler
from src.strategy.rebalancer import generate_rebalance_plan
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/rebalancing", tags=["Rebalancing"])

# 모듈 수준 스케줄러 인스턴스
_scheduler = RebalanceScheduler(portfolio_settings)


def _get_scheduler() -> RebalanceScheduler:
    """스케줄러 인스턴스 반환 (테스트에서 오버라이드 가능)"""
    return _scheduler


def _get_portfolio_settings() -> PortfolioSettings:
    """포트폴리오 설정 반환 (테스트에서 오버라이드 가능)"""
    return portfolio_settings


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """DB 세션 의존성 (래퍼, 테스트에서 오버라이드 가능)"""
    async for session in _app_get_db():
        yield session


@router.post(
    "/execute",
    response_model=RebalanceExecuteResponse,
    summary="수동 리밸런싱 실행",
    description=(
        "현재 포트폴리오를 기반으로 리밸런싱 계획을 생성합니다. "
        "dry_run=true(기본)이면 계획만 생성하고, false이면 DB에 기록합니다."
    ),
)
async def execute_rebalance(
    req: RebalanceExecuteRequest,
    db: AsyncSession = Depends(get_db),
    config: PortfolioSettings = Depends(_get_portfolio_settings),
) -> RebalanceExecuteResponse:
    """수동 리밸런싱 실행 엔드포인트"""
    logger.info("리밸런싱 실행 요청: dry_run=%s", req.dry_run)

    # 데모용 보유종목/현금 (실제로는 브로커 API에서 조회)
    holdings: list[dict] = []
    cash = 0.0
    total_equity = 0.0

    plan = generate_rebalance_plan(
        holdings=holdings,
        cash=cash,
        total_equity=max(total_equity, 1.0),  # 0 방지
        config=config,
    )

    order_details = [
        RebalanceOrderDetailItem(
            stock_code=o.stock_code,
            side=o.side,
            quantity=o.quantity,
            current_price=o.current_price,
            target_value_krw=o.target_value_krw,
            reason=o.reason,
            status="planned",
        )
        for o in plan.orders
    ]

    rebalance_id: int | None = None
    status = "planned"

    if not req.dry_run:
        # DB에 기록
        history = RebalanceHistory(
            trigger_type="manual",
            schedule_type=None,
            total_equity=plan.total_equity,
            cash_before=plan.cash_before,
            cash_after=plan.estimated_cash_after,
            total_orders=plan.total_orders,
            buy_orders_count=len(plan.buy_orders),
            sell_orders_count=len(plan.sell_orders),
            skipped_stocks=json.dumps(plan.skipped_stocks) if plan.skipped_stocks else None,
            status="completed",
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        db.add(history)
        await db.flush()

        for o in plan.orders:
            detail = RebalanceOrderDetail(
                rebalance_id=history.id,
                stock_code=o.stock_code,
                side=o.side,
                quantity=o.quantity,
                current_price=o.current_price,
                target_value_krw=o.target_value_krw,
                reason=o.reason,
                status="planned",
            )
            db.add(detail)

        rebalance_id = history.id
        status = "completed"

        logger.info("리밸런싱 내역 DB 기록 완료: id=%d", history.id)

    return RebalanceExecuteResponse(
        rebalance_id=rebalance_id,
        trigger_type="manual",
        dry_run=req.dry_run,
        total_equity=plan.total_equity,
        cash_before=plan.cash_before,
        cash_after=plan.estimated_cash_after,
        total_orders=plan.total_orders,
        buy_orders_count=len(plan.buy_orders),
        sell_orders_count=len(plan.sell_orders),
        skipped_stocks=plan.skipped_stocks,
        status=status,
        order_details=order_details,
    )


@router.get(
    "/history",
    response_model=RebalanceHistoryResponse,
    summary="리밸런싱 내역 조회",
    description="페이지네이션된 리밸런싱 내역을 조회합니다.",
)
async def get_rebalance_history(
    page: int = Query(default=1, ge=1, description="페이지 번호"),
    size: int = Query(default=20, ge=1, le=100, description="페이지 크기"),
    status: str | None = Query(
        default=None,
        description="상태 필터 (planned/executing/completed/failed)",
    ),
    db: AsyncSession = Depends(get_db),
) -> RebalanceHistoryResponse:
    """리밸런싱 내역 조회 엔드포인트"""
    logger.info("리밸런싱 내역 조회: page=%d, size=%d, status=%s", page, size, status)

    stmt = select(RebalanceHistory)
    count_stmt = select(func.count(RebalanceHistory.id))

    if status:
        stmt = stmt.where(RebalanceHistory.status == status)
        count_stmt = count_stmt.where(RebalanceHistory.status == status)

    offset = (page - 1) * size
    stmt = stmt.order_by(RebalanceHistory.created_at.desc()).offset(offset).limit(size)

    result = await db.execute(stmt)
    histories = result.scalars().all()

    count_result = await db.execute(count_stmt)
    total = count_result.scalar() or 0

    items = [
        RebalanceHistoryItem(
            id=h.id,
            trigger_type=h.trigger_type,
            schedule_type=h.schedule_type,
            total_equity=h.total_equity,
            cash_before=h.cash_before,
            cash_after=h.cash_after,
            total_orders=h.total_orders,
            buy_orders_count=h.buy_orders_count,
            sell_orders_count=h.sell_orders_count,
            status=h.status,
            started_at=h.started_at,
            completed_at=h.completed_at,
            created_at=h.created_at,
        )
        for h in histories
    ]

    return RebalanceHistoryResponse(
        items=items,
        total=total,
        page=page,
        size=size,
    )


@router.get(
    "/history/{history_id}",
    response_model=RebalanceDetailResponse,
    summary="리밸런싱 상세 조회",
    description="특정 리밸런싱 내역과 주문 상세를 조회합니다.",
)
async def get_rebalance_detail(
    history_id: int,
    db: AsyncSession = Depends(get_db),
) -> RebalanceDetailResponse:
    """리밸런싱 상세 조회 엔드포인트"""
    logger.info("리밸런싱 상세 조회: id=%d", history_id)

    stmt = (
        select(RebalanceHistory)
        .where(RebalanceHistory.id == history_id)
        .options(selectinload(RebalanceHistory.order_details))
    )
    result = await db.execute(stmt)
    history = result.scalar_one_or_none()

    if history is None:
        raise NotFoundError(
            f"리밸런싱 내역을 찾을 수 없습니다: id={history_id}",
        )

    skipped = []
    if history.skipped_stocks:
        try:
            skipped = json.loads(history.skipped_stocks)
        except (json.JSONDecodeError, TypeError):
            skipped = []

    order_details = [
        RebalanceOrderDetailItem(
            id=d.id,
            stock_code=d.stock_code,
            side=d.side,
            quantity=d.quantity,
            current_price=d.current_price,
            target_value_krw=d.target_value_krw,
            reason=d.reason,
            status=d.status,
            created_at=d.created_at,
        )
        for d in history.order_details
    ]

    return RebalanceDetailResponse(
        id=history.id,
        trigger_type=history.trigger_type,
        schedule_type=history.schedule_type,
        total_equity=history.total_equity,
        cash_before=history.cash_before,
        cash_after=history.cash_after,
        total_orders=history.total_orders,
        buy_orders_count=history.buy_orders_count,
        sell_orders_count=history.sell_orders_count,
        skipped_stocks=skipped,
        status=history.status,
        error_message=history.error_message,
        started_at=history.started_at,
        completed_at=history.completed_at,
        created_at=history.created_at,
        order_details=order_details,
    )


@router.get(
    "/schedule",
    response_model=RebalanceScheduleResponse,
    summary="스케줄 설정 조회",
    description="현재 리밸런싱 스케줄 설정과 다음 실행 예정 시각을 조회합니다.",
)
async def get_rebalance_schedule(
    scheduler: RebalanceScheduler = Depends(_get_scheduler),
    config: PortfolioSettings = Depends(_get_portfolio_settings),
) -> RebalanceScheduleResponse:
    """스케줄 설정 조회 엔드포인트"""
    now = datetime.now(UTC)

    next_run_at: str | None = None
    if config.rebalance_enabled:
        next_run = scheduler.next_run_time(now)
        next_run_at = next_run.isoformat()

    return RebalanceScheduleResponse(
        enabled=config.rebalance_enabled,
        schedule=config.rebalance_schedule,
        day_of_week=config.rebalance_day_of_week,
        day_of_month=config.rebalance_day_of_month,
        hour=config.rebalance_hour,
        next_run_at=next_run_at,
    )


@router.post(
    "/schedule/toggle",
    response_model=RebalanceScheduleResponse,
    summary="자동 리밸런싱 토글",
    description="자동 리밸런싱을 활성화 또는 비활성화합니다.",
)
async def toggle_rebalance_schedule(
    req: RebalanceToggleRequest,
    scheduler: RebalanceScheduler = Depends(_get_scheduler),
    config: PortfolioSettings = Depends(_get_portfolio_settings),
) -> RebalanceScheduleResponse:
    """자동 리밸런싱 토글 엔드포인트"""
    logger.info("자동 리밸런싱 토글: enabled=%s", req.enabled)

    # 런타임에 설정 변경 (프로세스 내 메모리 반영)
    config.rebalance_enabled = req.enabled
    scheduler.config = config

    now = datetime.now(UTC)
    next_run_at: str | None = None
    if req.enabled:
        next_run = scheduler.next_run_time(now)
        next_run_at = next_run.isoformat()

    return RebalanceScheduleResponse(
        enabled=req.enabled,
        schedule=config.rebalance_schedule,
        day_of_week=config.rebalance_day_of_week,
        day_of_month=config.rebalance_day_of_month,
        hour=config.rebalance_hour,
        next_run_at=next_run_at,
    )

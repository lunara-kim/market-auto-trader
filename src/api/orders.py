"""
주문 API 라우터

한투 OpenAPI를 통해 주식 주문을 실행하고,
DB에서 주문 내역을 조회합니다.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, get_kis_client
from src.api.schemas import (
    OrderHistoryItem,
    OrderHistoryResponse,
    OrderRequest,
    OrderResponse,
)
from src.broker.kis_client import KISClient
from src.exceptions import OrderError
from src.models.schema import Order
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Orders"])


@router.post(
    "/orders",
    response_model=OrderResponse,
    summary="매매 주문 실행",
    description=(
        "한투 OpenAPI를 통해 매수/매도 주문을 실행합니다. "
        "price를 생략하면 시장가 주문입니다."
    ),
)
async def place_order(
    req: OrderRequest,
    client: KISClient = Depends(get_kis_client),
    db: AsyncSession = Depends(get_db),
) -> OrderResponse:
    """
    주문 실행 엔드포인트

    1. KISClient로 한투 API에 주문 요청
    2. 주문 결과를 DB에 기록
    3. 주문번호/상태 응답
    """
    logger.info(
        "주문 요청: %s %s %d주 (가격: %s)",
        req.order_type.value,
        req.stock_code,
        req.quantity,
        str(req.price) if req.price else "시장가",
    )

    # 1) 한투 API 주문 실행
    try:
        result = client.place_order(
            stock_code=req.stock_code,
            order_type=req.order_type.value,
            quantity=req.quantity,
            price=req.price,
        )
    except OrderError:
        logger.exception("주문 실패: %s %s", req.order_type.value, req.stock_code)
        raise

    order_no = result.get("ODNO", "unknown")
    order_time = result.get("ORD_TMD", "")

    # 2) DB에 주문 기록
    order = Order(
        stock_code=req.stock_code,
        order_type=req.order_type.value,
        order_price=float(req.price) if req.price else None,
        quantity=req.quantity,
        status="executed",
    )
    db.add(order)

    logger.info("주문 완료: %s 주문번호=%s", req.order_type.value, order_no)

    return OrderResponse(
        order_id=order_no,
        stock_code=req.stock_code,
        order_type=req.order_type.value,
        quantity=req.quantity,
        price=str(req.price) if req.price else "시장가",
        status="executed",
        ordered_at=order_time or datetime.now(UTC).isoformat(),
    )


@router.get(
    "/orders",
    response_model=OrderHistoryResponse,
    summary="주문 내역 조회",
    description="DB에 저장된 주문 내역을 페이지네이션으로 조회합니다.",
)
async def get_orders(
    stock_code: str | None = Query(
        default=None,
        min_length=6,
        max_length=6,
        description="종목 코드 필터",
    ),
    order_type: str | None = Query(
        default=None,
        description="주문 유형 필터 (buy/sell)",
    ),
    status: str | None = Query(
        default=None,
        description="상태 필터 (pending/executed/cancelled/failed)",
    ),
    page: int = Query(default=1, ge=1, description="페이지 번호"),
    size: int = Query(default=20, ge=1, le=100, description="페이지 크기"),
    db: AsyncSession = Depends(get_db),
) -> OrderHistoryResponse:
    """
    주문 내역 조회 엔드포인트

    필터링: 종목코드, 주문유형, 상태
    정렬: 최신 주문 먼저
    페이지네이션: page, size
    """
    logger.info(
        "주문 내역 조회: stock_code=%s, type=%s, status=%s, page=%d",
        stock_code,
        order_type,
        status,
        page,
    )

    # 쿼리 조건 빌드
    stmt = select(Order)
    count_stmt = select(func.count(Order.id))

    if stock_code:
        stmt = stmt.where(Order.stock_code == stock_code)
        count_stmt = count_stmt.where(Order.stock_code == stock_code)
    if order_type:
        stmt = stmt.where(Order.order_type == order_type)
        count_stmt = count_stmt.where(Order.order_type == order_type)
    if status:
        stmt = stmt.where(Order.status == status)
        count_stmt = count_stmt.where(Order.status == status)

    # 정렬 + 페이지네이션
    offset = (page - 1) * size
    stmt = stmt.order_by(Order.created_at.desc()).offset(offset).limit(size)

    # 실행
    result = await db.execute(stmt)
    orders = result.scalars().all()

    count_result = await db.execute(count_stmt)
    total = count_result.scalar() or 0

    items = [
        OrderHistoryItem(
            id=o.id,
            stock_code=o.stock_code,
            stock_name=o.stock_name,
            order_type=o.order_type,
            order_price=o.order_price,
            quantity=o.quantity,
            status=o.status,
            executed_price=o.executed_price,
            executed_at=o.executed_at,
            created_at=o.created_at,
        )
        for o in orders
    ]

    logger.info("주문 내역 조회 완료: %d건 (전체 %d건)", len(items), total)

    return OrderHistoryResponse(
        orders=items,
        total=total,
        page=page,
        size=size,
    )

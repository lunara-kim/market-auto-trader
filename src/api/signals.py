"""
매매 신호 API 라우터

이동평균 교차 전략을 실행하여 매매 신호를 생성하고,
DB에서 신호 내역을 조회합니다.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db, get_kis_client
from src.api.schemas import (
    SignalHistoryItem,
    SignalHistoryResponse,
    SignalMetrics,
    SignalRequest,
    SignalResponse,
)
from src.broker.kis_client import KISClient
from src.data.collector import MarketDataCollector
from src.exceptions import DataCollectionError, ValidationError
from src.models.schema import Signal
from src.strategy.moving_average import MAConfig, MAType, MovingAverageCrossover
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Signals"])


@router.post(
    "/signals",
    response_model=SignalResponse,
    summary="매매 신호 생성",
    description=(
        "지정된 종목에 대해 이동평균 교차 전략을 실행하여 "
        "매수/매도/관망 신호를 생성합니다. "
        "한투 API에서 최근 시세 데이터를 조회한 뒤 분석합니다."
    ),
)
async def create_signal(
    req: SignalRequest,
    client: KISClient = Depends(get_kis_client),
    db: AsyncSession = Depends(get_db),
) -> SignalResponse:
    """
    매매 신호 생성 엔드포인트

    1. 한투 API에서 일봉 데이터 조회 (최근 N일)
    2. 이동평균 교차 전략 분석
    3. 매매 신호 생성
    4. DB에 기록
    5. 응답
    """
    logger.info(
        "매매 신호 생성 요청: %s (MA %s %d/%d)",
        req.stock_code,
        req.ma_type.value,
        req.short_window,
        req.long_window,
    )

    if req.short_window >= req.long_window:
        raise ValidationError(
            "단기 기간은 장기 기간보다 작아야 합니다.",
            detail={
                "short_window": req.short_window,
                "long_window": req.long_window,
            },
        )

    # 1) 시세 데이터 수집
    collector = MarketDataCollector(client)

    # 장기 MA 계산에 필요한 충분한 데이터 (long_window * 2 + 여유분)
    from datetime import datetime, timedelta

    end_date = datetime.now().strftime("%Y%m%d")
    # 영업일 기준으로 충분한 과거 데이터 확보 (캘린더일 * 1.5)
    calendar_days = int(req.long_window * 2 * 1.5)
    start_date = (datetime.now() - timedelta(days=calendar_days)).strftime("%Y%m%d")

    try:
        raw_data = collector.fetch_daily_prices(
            stock_code=req.stock_code,
            start_date=start_date,
            end_date=end_date,
        )
    except DataCollectionError:
        logger.exception("시세 데이터 수집 실패: %s", req.stock_code)
        raise

    if not raw_data:
        raise ValidationError(
            "시세 데이터가 없습니다. 종목 코드를 확인하세요.",
            detail={"stock_code": req.stock_code},
        )

    # 가격 리스트 추출 (오래된 순서로)
    # 한투 API는 최신 먼저 → 역순
    prices: list[float] = []
    dates: list[str] = []
    for record in reversed(raw_data):
        close = record.get("stck_clpr")
        if close:
            try:
                prices.append(float(close))
                date_str = record.get("stck_bsop_date", "")
                if len(date_str) == 8:
                    dates.append(
                        f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
                    )
                else:
                    dates.append(date_str)
            except (ValueError, TypeError):
                continue

    # 2) 전략 설정 + 분석
    ma_type = MAType.EMA if req.ma_type.value == "ema" else MAType.SMA
    config = MAConfig(
        short_window=req.short_window,
        long_window=req.long_window,
        ma_type=ma_type,
    )
    strategy = MovingAverageCrossover(config)

    analysis = strategy.analyze({
        "prices": prices,
        "dates": dates,
        "stock_code": req.stock_code,
    })

    # 3) 신호 생성
    signal = strategy.generate_signal(analysis)

    # 4) DB에 기록
    db_signal = Signal(
        stock_code=req.stock_code,
        signal_type=signal["signal"],
        strength=signal["strength"],
        strategy_name=signal["strategy_name"],
        reason=signal["reason"],
        is_executed=False,
    )
    db.add(db_signal)

    logger.info(
        "매매 신호 생성 완료: %s → %s (강도=%.2f)",
        req.stock_code,
        signal["signal"],
        signal["strength"],
    )

    # 5) 응답
    metrics = signal.get("metrics", {})
    return SignalResponse(
        stock_code=req.stock_code,
        signal=signal["signal"],
        strength=signal["strength"],
        reason=signal["reason"],
        strategy_name=signal["strategy_name"],
        metrics=SignalMetrics(
            current_short_ma=metrics.get("current_short_ma", 0.0),
            current_long_ma=metrics.get("current_long_ma", 0.0),
            ma_spread=metrics.get("ma_spread", 0.0),
            trend=metrics.get("trend", "neutral"),
            current_price=metrics.get("current_price", 0.0),
        ),
        timestamp=signal["timestamp"],
    )


@router.get(
    "/signals",
    response_model=SignalHistoryResponse,
    summary="매매 신호 내역 조회",
    description="DB에 저장된 매매 신호 내역을 조회합니다.",
)
async def get_signals(
    stock_code: str | None = Query(
        default=None,
        min_length=6,
        max_length=6,
        description="종목 코드 필터",
    ),
    signal_type: str | None = Query(
        default=None,
        description="신호 유형 필터 (buy/sell/hold)",
    ),
    limit: int = Query(default=50, ge=1, le=200, description="최대 조회 건수"),
    db: AsyncSession = Depends(get_db),
) -> SignalHistoryResponse:
    """매매 신호 내역 조회"""
    logger.info(
        "신호 내역 조회: stock_code=%s, type=%s, limit=%d",
        stock_code,
        signal_type,
        limit,
    )

    stmt = select(Signal)
    count_stmt = select(func.count(Signal.id))

    if stock_code:
        stmt = stmt.where(Signal.stock_code == stock_code)
        count_stmt = count_stmt.where(Signal.stock_code == stock_code)
    if signal_type:
        stmt = stmt.where(Signal.signal_type == signal_type)
        count_stmt = count_stmt.where(Signal.signal_type == signal_type)

    stmt = stmt.order_by(Signal.created_at.desc()).limit(limit)

    result = await db.execute(stmt)
    signals = result.scalars().all()

    count_result = await db.execute(count_stmt)
    total = count_result.scalar() or 0

    items = [
        SignalHistoryItem(
            id=s.id,
            stock_code=s.stock_code,
            signal_type=s.signal_type,
            strength=s.strength,
            target_price=s.target_price,
            stop_loss=s.stop_loss,
            strategy_name=s.strategy_name,
            reason=s.reason,
            is_executed=s.is_executed,
            created_at=s.created_at,
        )
        for s in signals
    ]

    logger.info("신호 내역 조회 완료: %d건 (전체 %d건)", len(items), total)

    return SignalHistoryResponse(signals=items, total=total)

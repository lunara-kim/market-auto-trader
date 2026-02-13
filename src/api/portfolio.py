"""
포트폴리오 API 라우터

한투 OpenAPI를 통해 실시간 포트폴리오(보유종목 + 계좌요약)를 조회합니다.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends

from src.api.dependencies import get_kis_client
from src.api.schemas import (
    HoldingItem,
    PortfolioResponse,
    PortfolioSummary,
)
from src.broker.kis_client import KISClient
from src.exceptions import BrokerError
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Portfolio"])


def _safe_float(value: str | None, default: float = 0.0) -> float:
    """문자열을 안전하게 float로 변환"""
    if not value:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _safe_int(value: str | None, default: int = 0) -> int:
    """문자열을 안전하게 int로 변환"""
    if not value:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


@router.get(
    "/portfolio",
    response_model=PortfolioResponse,
    summary="포트폴리오 조회",
    description="한투 OpenAPI를 통해 보유종목과 계좌 요약 정보를 실시간 조회합니다.",
)
async def get_portfolio(
    client: KISClient = Depends(get_kis_client),
) -> PortfolioResponse:
    """
    포트폴리오 조회 엔드포인트

    - 보유종목: 종목코드, 종목명, 수량, 매입평균가, 현재가, 평가손익
    - 계좌요약: 예수금, 총 평가금액, 순자산
    """
    logger.info("포트폴리오 조회 요청")

    try:
        balance = client.get_balance()
    except BrokerError:
        logger.exception("포트폴리오 조회 실패")
        raise

    # 보유종목 변환
    holdings: list[HoldingItem] = []
    for h in balance.get("holdings", []):
        # 보유수량이 0이면 스킵
        qty = _safe_int(h.get("hldg_qty"))
        if qty <= 0:
            continue

        holdings.append(
            HoldingItem(
                stock_code=h.get("pdno", ""),
                stock_name=h.get("prdt_name", ""),
                quantity=qty,
                avg_price=_safe_float(h.get("pchs_avg_pric")),
                current_price=_safe_float(h.get("prpr")),
                eval_amount=_safe_float(h.get("evlu_amt")),
                profit_loss=_safe_float(h.get("evlu_pfls_amt")),
                profit_loss_rate=_safe_float(h.get("evlu_pfls_rt")),
            )
        )

    # 계좌 요약 변환
    raw_summary = balance.get("summary", {})
    summary = PortfolioSummary(
        cash=_safe_float(raw_summary.get("dnca_tot_amt")),
        total_eval=_safe_float(raw_summary.get("tot_evlu_amt")),
        total_purchase=_safe_float(raw_summary.get("pchs_amt_smtl_amt")),
        total_profit_loss=_safe_float(raw_summary.get("evlu_pfls_smtl_amt")),
        net_asset=_safe_float(raw_summary.get("nass_amt")),
    )

    logger.info(
        "포트폴리오 조회 완료: 보유종목 %d건, 순자산 %.0f원",
        len(holdings),
        summary.net_asset,
    )

    return PortfolioResponse(
        holdings=holdings,
        summary=summary,
        updated_at=datetime.now(UTC).isoformat(),
    )


@router.get(
    "/portfolio/summary",
    response_model=PortfolioSummary,
    summary="계좌 요약 조회",
    description="예수금, 총 평가금액, 순자산 등 계좌 요약만 조회합니다.",
)
async def get_portfolio_summary(
    client: KISClient = Depends(get_kis_client),
) -> PortfolioSummary:
    """계좌 요약만 간단히 조회"""
    logger.info("계좌 요약 조회 요청")

    try:
        balance = client.get_balance()
    except BrokerError:
        logger.exception("계좌 요약 조회 실패")
        raise

    raw = balance.get("summary", {})
    return PortfolioSummary(
        cash=_safe_float(raw.get("dnca_tot_amt")),
        total_eval=_safe_float(raw.get("tot_evlu_amt")),
        total_purchase=_safe_float(raw.get("pchs_amt_smtl_amt")),
        total_profit_loss=_safe_float(raw.get("evlu_pfls_smtl_amt")),
        net_asset=_safe_float(raw.get("nass_amt")),
    )

"""
알림 API 라우터

알림 규칙 생성/조회/삭제 및 수동 알림 체크 기능을 제공합니다.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db
from src.api.schemas import (
    AlertCheckRequest,
    AlertCheckResponse,
    AlertCreateRequest,
    AlertRuleResponse,
    AlertToggleResponse,
)
from src.exceptions import NotFoundError
from src.models.schema import AlertRule as DBAlertRule
from src.notification.alert_manager import AlertCondition, AlertManager, AlertRule
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/alerts", tags=["Alerts"])


# AlertManager 싱글톤 (실제로는 DI로 주입하는 것이 좋음)
_alert_manager = AlertManager()


@router.post(
    "",
    response_model=AlertRuleResponse,
    summary="알림 규칙 생성",
    description="새로운 알림 규칙을 생성합니다.",
)
async def create_alert(
    req: AlertCreateRequest,
    db: AsyncSession = Depends(get_db),
) -> AlertRuleResponse:
    """알림 규칙 생성"""
    # DB에 저장
    db_rule = DBAlertRule(
        stock_code=req.stock_code,
        stock_name=req.stock_name,
        condition=req.condition.value,
        threshold=req.threshold,
        is_active=True,
        cooldown_minutes=req.cooldown_minutes,
        created_at=datetime.now(UTC),
    )
    db.add(db_rule)
    await db.flush()
    await db.refresh(db_rule)

    # AlertManager에도 추가
    alert_rule = AlertRule(
        id=db_rule.id,
        stock_code=db_rule.stock_code,
        stock_name=db_rule.stock_name,
        condition=AlertCondition(db_rule.condition),
        threshold=db_rule.threshold,
        is_active=db_rule.is_active,
        cooldown_minutes=db_rule.cooldown_minutes,
        created_at=db_rule.created_at,
    )
    _alert_manager.add_rule(alert_rule)

    logger.info("알림 규칙 생성: ID=%s, 종목=%s", db_rule.id, db_rule.stock_code)

    return AlertRuleResponse(
        id=db_rule.id,
        stock_code=db_rule.stock_code,
        stock_name=db_rule.stock_name,
        condition=AlertCondition(db_rule.condition),
        threshold=db_rule.threshold,
        is_active=db_rule.is_active,
        cooldown_minutes=db_rule.cooldown_minutes,
        created_at=db_rule.created_at,
        last_triggered_at=db_rule.last_triggered_at,
    )


@router.get(
    "",
    response_model=list[AlertRuleResponse],
    summary="알림 규칙 목록 조회",
    description="모든 알림 규칙을 조회합니다.",
)
async def list_alerts(
    db: AsyncSession = Depends(get_db),
) -> list[AlertRuleResponse]:
    """알림 규칙 목록 조회"""
    result = await db.execute(select(DBAlertRule).order_by(DBAlertRule.created_at.desc()))
    db_rules = result.scalars().all()

    return [
        AlertRuleResponse(
            id=rule.id,
            stock_code=rule.stock_code,
            stock_name=rule.stock_name,
            condition=AlertCondition(rule.condition),
            threshold=rule.threshold,
            is_active=rule.is_active,
            cooldown_minutes=rule.cooldown_minutes,
            created_at=rule.created_at,
            last_triggered_at=rule.last_triggered_at,
        )
        for rule in db_rules
    ]


@router.get(
    "/{alert_id}",
    response_model=AlertRuleResponse,
    summary="알림 규칙 단일 조회",
    description="특정 ID의 알림 규칙을 조회합니다.",
)
async def get_alert(
    alert_id: int,
    db: AsyncSession = Depends(get_db),
) -> AlertRuleResponse:
    """알림 규칙 단일 조회"""
    result = await db.execute(
        select(DBAlertRule).where(DBAlertRule.id == alert_id)
    )
    db_rule = result.scalar_one_or_none()

    if not db_rule:
        raise NotFoundError(f"알림 규칙 ID {alert_id}를 찾을 수 없습니다.")

    return AlertRuleResponse(
        id=db_rule.id,
        stock_code=db_rule.stock_code,
        stock_name=db_rule.stock_name,
        condition=AlertCondition(db_rule.condition),
        threshold=db_rule.threshold,
        is_active=db_rule.is_active,
        cooldown_minutes=db_rule.cooldown_minutes,
        created_at=db_rule.created_at,
        last_triggered_at=db_rule.last_triggered_at,
    )


@router.delete(
    "/{alert_id}",
    summary="알림 규칙 삭제",
    description="특정 ID의 알림 규칙을 삭제합니다.",
)
async def delete_alert(
    alert_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """알림 규칙 삭제"""
    result = await db.execute(
        select(DBAlertRule).where(DBAlertRule.id == alert_id)
    )
    db_rule = result.scalar_one_or_none()

    if not db_rule:
        raise NotFoundError(f"알림 규칙 ID {alert_id}를 찾을 수 없습니다.")

    await db.delete(db_rule)
    _alert_manager.remove_rule(alert_id)

    logger.info("알림 규칙 삭제: ID=%s", alert_id)
    return {"message": f"알림 규칙 ID {alert_id}가 삭제되었습니다."}


@router.put(
    "/{alert_id}/toggle",
    response_model=AlertToggleResponse,
    summary="알림 규칙 활성/비활성 토글",
    description="알림 규칙의 활성 상태를 토글합니다.",
)
async def toggle_alert(
    alert_id: int,
    db: AsyncSession = Depends(get_db),
) -> AlertToggleResponse:
    """알림 규칙 활성/비활성 토글"""
    result = await db.execute(
        select(DBAlertRule).where(DBAlertRule.id == alert_id)
    )
    db_rule = result.scalar_one_or_none()

    if not db_rule:
        raise NotFoundError(f"알림 규칙 ID {alert_id}를 찾을 수 없습니다.")

    db_rule.is_active = not db_rule.is_active
    await db.flush()

    # AlertManager 업데이트
    rules = _alert_manager.get_rules()
    for rule in rules:
        if rule.id == alert_id:
            rule.is_active = db_rule.is_active
            break

    logger.info("알림 규칙 토글: ID=%s, 활성=%s", alert_id, db_rule.is_active)

    return AlertToggleResponse(
        id=db_rule.id,
        is_active=db_rule.is_active,
        message=f"알림 규칙이 {'활성화' if db_rule.is_active else '비활성화'}되었습니다.",
    )


@router.post(
    "/check",
    response_model=AlertCheckResponse,
    summary="수동 알림 체크",
    description="특정 종목의 현재가에 대해 알림 조건을 수동으로 체크합니다.",
)
async def check_alert(
    req: AlertCheckRequest,
    db: AsyncSession = Depends(get_db),
) -> AlertCheckResponse:
    """수동 알림 체크"""
    # DB에서 활성화된 규칙 조회
    result = await db.execute(
        select(DBAlertRule)
        .where(DBAlertRule.stock_code == req.stock_code)
        .where(DBAlertRule.is_active == True)  # noqa: E712
    )
    db_rules = result.scalars().all()

    if not db_rules:
        return AlertCheckResponse(
            stock_code=req.stock_code,
            current_price=req.current_price,
            triggered_count=0,
            triggered_alerts=[],
            message="활성화된 알림 규칙이 없습니다.",
        )

    # AlertManager에 규칙 동기화
    for db_rule in db_rules:
        alert_rule = AlertRule(
            id=db_rule.id,
            stock_code=db_rule.stock_code,
            stock_name=db_rule.stock_name,
            condition=AlertCondition(db_rule.condition),
            threshold=db_rule.threshold,
            is_active=db_rule.is_active,
            cooldown_minutes=db_rule.cooldown_minutes,
            created_at=db_rule.created_at,
            last_triggered_at=db_rule.last_triggered_at,
        )
        # 기존 규칙이 있으면 업데이트, 없으면 추가
        existing = [r for r in _alert_manager.get_rules() if r.id == db_rule.id]
        if not existing:
            _alert_manager.add_rule(alert_rule)

    # 알림 체크
    triggered = _alert_manager.check_alerts(
        stock_code=req.stock_code,
        current_price=req.current_price,
        volume=req.volume,
        previous_close=req.previous_close,
    )

    # DB 업데이트 (last_triggered_at)
    for rule in triggered:
        await db.execute(
            update(DBAlertRule)
            .where(DBAlertRule.id == rule.id)
            .values(last_triggered_at=rule.last_triggered_at)
        )

    return AlertCheckResponse(
        stock_code=req.stock_code,
        current_price=req.current_price,
        triggered_count=len(triggered),
        triggered_alerts=[
            AlertRuleResponse(
                id=rule.id,
                stock_code=rule.stock_code,
                stock_name=rule.stock_name,
                condition=rule.condition,
                threshold=rule.threshold,
                is_active=rule.is_active,
                cooldown_minutes=rule.cooldown_minutes,
                created_at=rule.created_at,
                last_triggered_at=rule.last_triggered_at,
            )
            for rule in triggered
        ],
        message=f"{len(triggered)}개의 알림이 트리거되었습니다." if triggered else "알림이 트리거되지 않았습니다.",
    )

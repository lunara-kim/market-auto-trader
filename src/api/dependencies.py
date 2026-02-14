"""
FastAPI 의존성 주입

KISClient와 DB 세션을 API 핸들러에 주입합니다.
설정값이 없으면 BrokerError를 발생시킵니다.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Generator

from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from src.broker.kis_client import KISClient
from src.db import async_session_factory
from src.exceptions import ValidationError
from src.utils.logger import get_logger

logger = get_logger(__name__)


def get_kis_client() -> Generator[KISClient, None, None]:
    """
    KISClient 의존성.

    settings에서 API 키/시크릿/계좌번호를 읽어 KISClient를 생성합니다.
    설정이 없으면 ValidationError를 발생시킵니다.

    Usage::

        @router.get("/portfolio")
        async def get_portfolio(client: KISClient = Depends(get_kis_client)):
            return client.get_balance()
    """
    if not settings.kis_app_key or not settings.kis_app_secret:
        raise ValidationError(
            "한투 API 인증 정보가 설정되지 않았습니다. "
            ".env 파일에 KIS_APP_KEY, KIS_APP_SECRET을 설정하세요.",
            detail={"hint": "KIS_APP_KEY, KIS_APP_SECRET, KIS_ACCOUNT_NO 필요"},
        )
    if not settings.kis_account_no or "-" not in settings.kis_account_no:
        raise ValidationError(
            "계좌번호가 설정되지 않았습니다. "
            ".env 파일에 KIS_ACCOUNT_NO를 'XXXXXXXX-XX' 형식으로 설정하세요.",
            detail={"hint": "KIS_ACCOUNT_NO=12345678-01"},
        )

    client = KISClient(
        app_key=settings.kis_app_key,
        app_secret=settings.kis_app_secret,
        account_no=settings.kis_account_no,
        mock=settings.kis_mock,
    )
    try:
        yield client
    finally:
        client.close()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    DB 세션 의존성.

    비동기 세션을 생성하고, 정상 완료 시 커밋, 예외 시 롤백합니다.
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("DB 세션 롤백 발생")
            raise

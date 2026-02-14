"""
시장 데이터 캐싱 레이어

DB를 캐시로 활용하여 중복 API 호출을 방지합니다.

Usage::

    cache = MarketDataCache(session_factory)

    # 캐시된 데이터 조회
    data = cache.get_cached("005930", date(2026, 1, 1), date(2026, 2, 14))

    # 캐시 여부 확인
    if cache.is_cached("005930", date(2026, 2, 14)):
        ...

    # 누락된 날짜 조회
    missing = cache.get_missing_dates("005930", date(2026, 1, 1), date(2026, 2, 14))

    # 캐시 무효화
    cache.invalidate("005930")
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta

from sqlalchemy import and_, delete, func, select
from sqlalchemy.orm import Session

from src.models.schema import MarketData
from src.utils.logger import get_logger

logger = get_logger(__name__)


class MarketDataCache:
    """시장 데이터 캐시 (DB 기반)

    DB를 캐시로 활용하여 이미 수집한 데이터는
    재수집하지 않습니다.
    """

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        """
        Args:
            session_factory: DB 세션 팩토리
        """
        self._session_factory = session_factory
        logger.info("MarketDataCache 초기화")

    def get_cached(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
    ) -> list[MarketData] | None:
        """캐시된 시세 데이터 조회

        Args:
            stock_code: 종목 코드
            start_date: 시작일
            end_date: 종료일

        Returns:
            MarketData 리스트 (없으면 None)
        """
        with self._session_factory() as session:
            stmt = (
                select(MarketData)
                .where(
                    and_(
                        MarketData.stock_code == stock_code,
                        MarketData.date >= datetime.combine(
                            start_date,
                            datetime.min.time(),
                        ),
                        MarketData.date <= datetime.combine(
                            end_date,
                            datetime.min.time(),
                        ),
                    ),
                )
                .order_by(MarketData.date)
            )

            result = session.execute(stmt).scalars().all()

            if not result:
                logger.debug(
                    "캐시 미스: %s (%s ~ %s)",
                    stock_code,
                    start_date,
                    end_date,
                )
                return None

            logger.debug(
                "캐시 히트: %s (%d건, %s ~ %s)",
                stock_code,
                len(result),
                start_date,
                end_date,
            )
            return list(result)

    def is_cached(self, stock_code: str, target_date: date) -> bool:
        """특정 날짜의 데이터가 캐시되어 있는지 확인

        Args:
            stock_code: 종목 코드
            target_date: 확인할 날짜

        Returns:
            캐시 여부
        """
        with self._session_factory() as session:
            stmt = select(MarketData).where(
                and_(
                    MarketData.stock_code == stock_code,
                    MarketData.date
                    == datetime.combine(target_date, datetime.min.time()),
                ),
            )
            result = session.execute(stmt).scalar_one_or_none()
            return result is not None

    def get_missing_dates(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
    ) -> list[date]:
        """DB에 없는 날짜 리스트 반환 (주말 제외)

        Args:
            stock_code: 종목 코드
            start_date: 시작일
            end_date: 종료일

        Returns:
            DB에 없는 영업일 리스트
        """
        # 모든 날짜 생성 (주말 제외)
        all_dates = self._generate_business_dates(start_date, end_date)

        # DB에 있는 날짜 조회
        with self._session_factory() as session:
            stmt = (
                select(MarketData.date)
                .where(
                    and_(
                        MarketData.stock_code == stock_code,
                        MarketData.date >= datetime.combine(
                            start_date,
                            datetime.min.time(),
                        ),
                        MarketData.date <= datetime.combine(
                            end_date,
                            datetime.min.time(),
                        ),
                    ),
                )
                .order_by(MarketData.date)
            )

            cached_dates = {
                result.date() for result in session.execute(stmt).scalars().all()
            }

        # 차집합
        missing = [d for d in all_dates if d not in cached_dates]

        logger.debug(
            "누락 날짜 분석: %s (%d일 누락, 총 %d일)",
            stock_code,
            len(missing),
            len(all_dates),
        )
        return missing

    def invalidate(
        self,
        stock_code: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> int:
        """캐시 무효화 (DB에서 삭제)

        Args:
            stock_code: 종목 코드
            start_date: 시작일 (None이면 전체)
            end_date: 종료일 (None이면 전체)

        Returns:
            삭제된 레코드 수
        """
        with self._session_factory() as session:
            stmt = delete(MarketData).where(MarketData.stock_code == stock_code)

            if start_date:
                stmt = stmt.where(
                    MarketData.date
                    >= datetime.combine(start_date, datetime.min.time()),
                )

            if end_date:
                stmt = stmt.where(
                    MarketData.date <= datetime.combine(end_date, datetime.min.time()),
                )

            result = session.execute(stmt)
            session.commit()

            deleted = result.rowcount or 0
            logger.info(
                "캐시 무효화: %s (%d건 삭제, %s ~ %s)",
                stock_code,
                deleted,
                start_date or "전체",
                end_date or "전체",
            )
            return deleted

    def get_cache_stats(self) -> dict[str, int | dict[str, int]]:
        """캐시 통계 반환

        Returns:
            통계 딕셔너리:
                - total_records: 총 레코드 수
                - stock_count: 종목 수
                - by_stock: 종목별 레코드 수
        """
        with self._session_factory() as session:
            # 총 레코드 수
            total_stmt = select(func.count(MarketData.id))
            total = session.execute(total_stmt).scalar() or 0

            # 종목별 레코드 수
            stock_stmt = (
                select(MarketData.stock_code, func.count(MarketData.id))
                .group_by(MarketData.stock_code)
                .order_by(func.count(MarketData.id).desc())
            )
            by_stock = {
                row[0]: row[1] for row in session.execute(stock_stmt).all()
            }

            stats = {
                "total_records": total,
                "stock_count": len(by_stock),
                "by_stock": by_stock,
            }

            logger.debug("캐시 통계: %d개 종목, 총 %d건", len(by_stock), total)
            return stats

    @staticmethod
    def _generate_business_dates(start_date: date, end_date: date) -> list[date]:
        """영업일 리스트 생성 (주말 제외, 공휴일은 포함)

        Args:
            start_date: 시작일
            end_date: 종료일

        Returns:
            영업일 리스트 (월~금)
        """
        dates: list[date] = []
        current = start_date

        while current <= end_date:
            # 주말 제외 (월~금: 0~4)
            if current.weekday() < 5:
                dates.append(current)
            current += timedelta(days=1)

        return dates

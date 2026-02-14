"""
데이터 파이프라인 — 일봉 자동 수집 + DB 저장

MarketDataCollector로 시세를 수집하고,
중복 체크 후 DB에 저장합니다.

Usage::

    collector = MarketDataCollector(kis_client)
    pipeline = DailyDataPipeline(collector, session_factory)

    # 특정 종목 + 기간 수집
    result = pipeline.collect_and_store(
        ["005930", "000660"],
        date(2026, 1, 1),
        date(2026, 2, 14),
    )

    # 오늘 일봉 수집
    result = pipeline.run_daily_collection(["005930", "000660"])
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.data.collector import MarketDataCollector
from src.exceptions import DataPipelineError
from src.models.schema import MarketData
from src.utils.logger import get_logger
from src.utils.retry import retry

logger = get_logger(__name__)


@dataclass
class CollectionResult:
    """데이터 수집 결과"""

    success_count: int = 0
    fail_count: int = 0
    skipped_count: int = 0
    errors: list[dict[str, str]] = field(default_factory=list)

    def add_success(self) -> None:
        """성공 건수 증가"""
        self.success_count += 1

    def add_fail(self, stock_code: str, error: str) -> None:
        """실패 건수 증가"""
        self.fail_count += 1
        self.errors.append({"stock_code": stock_code, "error": error})

    def add_skip(self) -> None:
        """스킵 건수 증가"""
        self.skipped_count += 1


class DailyDataPipeline:
    """일봉 데이터 파이프라인

    MarketDataCollector로 시세를 수집하고,
    DB에 저장합니다. 이미 존재하는 데이터는 스킵합니다.
    """

    def __init__(
        self,
        collector: MarketDataCollector,
        session_factory: Callable[[], Session],
    ) -> None:
        """
        Args:
            collector: 시세 수집기
            session_factory: DB 세션 팩토리
        """
        self._collector = collector
        self._session_factory = session_factory
        logger.info("DailyDataPipeline 초기화")

    def collect_and_store(
        self,
        stock_codes: list[str],
        start_date: date,
        end_date: date,
    ) -> CollectionResult:
        """종목 리스트의 일봉 데이터를 수집하고 DB에 저장

        Args:
            stock_codes: 종목 코드 리스트
            start_date: 시작일
            end_date: 종료일

        Returns:
            수집 결과 (성공/실패/스킵 건수, 에러 내역)
        """
        logger.info(
            "데이터 수집 시작: %d개 종목 (%s ~ %s)",
            len(stock_codes),
            start_date,
            end_date,
        )

        result = CollectionResult()

        for stock_code in stock_codes:
            try:
                data_list = self.collect_single_stock(stock_code, start_date, end_date)
                if not data_list:
                    logger.info("종목 %s: 수집된 데이터 없음", stock_code)
                    continue

                # DB 저장
                with self._session_factory() as session:
                    for market_data in data_list:
                        # 중복 체크
                        existing = session.execute(
                            select(MarketData).where(
                                MarketData.stock_code == market_data.stock_code,
                                MarketData.date == market_data.date,
                            ),
                        ).scalar_one_or_none()

                        if existing:
                            result.add_skip()
                        else:
                            session.add(market_data)
                            result.add_success()

                    session.commit()

                logger.info(
                    "종목 %s 완료: %d건 저장, %d건 스킵",
                    stock_code,
                    len([d for d in data_list if d]),
                    result.skipped_count,
                )

            except Exception as e:
                logger.error("종목 %s 수집 실패: %s", stock_code, e)
                result.add_fail(stock_code, str(e))

        logger.info(
            "데이터 수집 완료: 성공 %d, 실패 %d, 스킵 %d",
            result.success_count,
            result.fail_count,
            result.skipped_count,
        )
        return result

    @retry(max_retries=3, base_delay=1.0, retryable=(DataPipelineError,))
    def collect_single_stock(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
    ) -> list[MarketData]:
        """단일 종목의 일봉 데이터 수집

        Args:
            stock_code: 종목 코드
            start_date: 시작일
            end_date: 종료일

        Returns:
            MarketData 리스트
        """
        logger.debug("종목 %s 수집 중 (%s ~ %s)", stock_code, start_date, end_date)

        try:
            raw_data = self._collector.fetch_stock_price(
                stock_code,
                datetime.combine(start_date, datetime.min.time()),
                datetime.combine(end_date, datetime.min.time()),
            )
        except Exception as e:
            raise DataPipelineError(
                f"종목 {stock_code} 시세 수집 실패",
                detail={"stock_code": stock_code, "error": str(e)},
            ) from e

        # MarketData 객체로 변환
        market_data_list: list[MarketData] = []
        for record in raw_data:
            try:
                market_data = MarketData(
                    stock_code=stock_code,
                    date=datetime.strptime(record["date"], "%Y-%m-%d"),
                    open_price=float(record["open"]) if record["open"] else None,
                    high_price=float(record["high"]) if record["high"] else None,
                    low_price=float(record["low"]) if record["low"] else None,
                    close_price=float(record["close"]) if record["close"] else None,
                    volume=int(record["volume"]) if record["volume"] else None,
                )
                market_data_list.append(market_data)
            except (ValueError, KeyError) as e:
                logger.warning(
                    "종목 %s 레코드 파싱 실패 (%s): %s",
                    stock_code,
                    record.get("date"),
                    e,
                )

        return market_data_list

    def run_daily_collection(self, watchlist: list[str]) -> CollectionResult:
        """오늘 일봉 수집 (watchlist 기준)

        Args:
            watchlist: 감시 종목 리스트

        Returns:
            수집 결과
        """
        today = date.today()
        logger.info("일일 수집 실행: %s (%d개 종목)", today, len(watchlist))

        return self.collect_and_store(watchlist, today, today)

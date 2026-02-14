"""리밸런싱 스케줄러

순수 Python으로 구현한 리밸런싱 스케줄 관리 모듈.
APScheduler 등 외부 의존성 없이 다음 실행 시점 계산 로직만 제공한다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from config.portfolio import PortfolioSettings
from src.utils.logger import get_logger

logger = get_logger(__name__)

# KST 타임존 (UTC+9)
KST = timezone(timedelta(hours=9))


class RebalanceScheduler:
    """리밸런싱 스케줄 판단 클래스

    주어진 설정에 따라 리밸런싱 실행 여부와 다음 실행 시점을 계산한다.

    Args:
        config: 포트폴리오 설정 (스케줄 관련 필드 포함)
    """

    def __init__(self, config: PortfolioSettings) -> None:
        self.config = config
        self._last_run_time: datetime | None = None

    @property
    def last_run_time(self) -> datetime | None:
        """마지막 실행 시각"""
        return self._last_run_time

    @last_run_time.setter
    def last_run_time(self, value: datetime | None) -> None:
        self._last_run_time = value

    def next_run_time(self, now: datetime) -> datetime:
        """다음 리밸런싱 실행 예정 시각을 계산한다.

        Args:
            now: 현재 시각 (timezone-aware 권장)

        Returns:
            다음 실행 예정 시각 (KST 기준)
        """
        kst_now = now.astimezone(KST)
        schedule = self.config.rebalance_schedule
        hour = self.config.rebalance_hour

        if schedule == "daily":
            return self._next_daily(kst_now, hour)
        if schedule == "weekly":
            return self._next_weekly(
                kst_now, hour, self.config.rebalance_day_of_week,
            )
        if schedule == "monthly":
            return self._next_monthly(
                kst_now, hour, self.config.rebalance_day_of_month,
            )

        # 기본값 (weekly)
        return self._next_weekly(kst_now, hour, self.config.rebalance_day_of_week)

    def should_run(self, now: datetime) -> bool:
        """지금 리밸런싱을 실행해야 하는지 판단한다.

        조건:
        1. 자동 리밸런싱이 활성화되어 있어야 함
        2. 현재 시각이 예정 실행 시각의 1시간 이내여야 함
        3. 마지막 실행 이후 충분한 시간이 경과해야 함

        Args:
            now: 현재 시각 (timezone-aware 권장)

        Returns:
            실행 여부
        """
        if not self.config.rebalance_enabled:
            return False

        kst_now = now.astimezone(KST)
        next_run = self.next_run_time(now)

        # 다음 실행 시점을 기준으로 현재 실행 윈도우 계산
        # 실행 시각의 해당일 시작 시각
        run_window_start = next_run - self._schedule_interval()
        run_window_end = run_window_start + timedelta(hours=1)

        # 현재 시각이 실행 윈도우 내에 있는지 확인
        in_window = run_window_start <= kst_now < run_window_end

        if not in_window:
            return False

        # 마지막 실행 후 중복 실행 방지
        if self._last_run_time is not None:
            last_kst = self._last_run_time.astimezone(KST)
            if last_kst >= run_window_start:
                logger.debug(
                    "이번 주기에 이미 실행됨 (last_run: %s)",
                    last_kst.isoformat(),
                )
                return False

        logger.info(
            "리밸런싱 실행 조건 충족: schedule=%s, window=[%s ~ %s], now=%s",
            self.config.rebalance_schedule,
            run_window_start.isoformat(),
            run_window_end.isoformat(),
            kst_now.isoformat(),
        )
        return True

    def _schedule_interval(self) -> timedelta:
        """스케줄 주기에 해당하는 timedelta를 반환한다."""
        schedule = self.config.rebalance_schedule
        if schedule == "daily":
            return timedelta(days=1)
        if schedule == "weekly":
            return timedelta(weeks=1)
        if schedule == "monthly":
            return timedelta(days=28)  # 근사치
        return timedelta(weeks=1)

    @staticmethod
    def _next_daily(kst_now: datetime, hour: int) -> datetime:
        """다음 일별 실행 시각 계산"""
        today_run = kst_now.replace(
            hour=hour, minute=0, second=0, microsecond=0,
        )
        if kst_now >= today_run:
            return today_run + timedelta(days=1)
        return today_run

    @staticmethod
    def _next_weekly(
        kst_now: datetime, hour: int, day_of_week: int,
    ) -> datetime:
        """다음 주별 실행 시각 계산

        Args:
            kst_now: 현재 KST 시각
            hour: 실행 시간
            day_of_week: 0=월요일 ~ 6=일요일
        """
        current_weekday = kst_now.weekday()
        days_ahead = day_of_week - current_weekday
        if days_ahead < 0:
            days_ahead += 7

        next_run = kst_now.replace(
            hour=hour, minute=0, second=0, microsecond=0,
        ) + timedelta(days=days_ahead)

        # 오늘이 실행일이지만 이미 시간이 지난 경우
        if days_ahead == 0 and kst_now >= next_run:
            next_run += timedelta(weeks=1)

        return next_run

    @staticmethod
    def _next_monthly(
        kst_now: datetime, hour: int, day_of_month: int,
    ) -> datetime:
        """다음 월별 실행 시각 계산

        Args:
            kst_now: 현재 KST 시각
            hour: 실행 시간
            day_of_month: 1~28
        """
        this_month_run = kst_now.replace(
            day=day_of_month, hour=hour, minute=0, second=0, microsecond=0,
        )

        if kst_now >= this_month_run:
            # 다음 달로 이동
            if kst_now.month == 12:
                next_month_run = this_month_run.replace(
                    year=kst_now.year + 1, month=1,
                )
            else:
                next_month_run = this_month_run.replace(
                    month=kst_now.month + 1,
                )
            return next_month_run

        return this_month_run

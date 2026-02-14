"""
리밸런싱 스케줄러 테스트

src/strategy/rebalance_scheduler.py의 should_run, next_run_time 로직을 검증합니다.
"""

from __future__ import annotations

from datetime import datetime, timezone

from config.portfolio import PortfolioSettings
from src.strategy.rebalance_scheduler import KST, RebalanceScheduler


# ───────────────── 헬퍼 ─────────────────


def _kst(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    """KST 시각 헬퍼"""
    return datetime(year, month, day, hour, minute, tzinfo=KST)


def _make_config(**kwargs: object) -> PortfolioSettings:
    """테스트용 PortfolioSettings 생성"""
    defaults: dict[str, object] = {
        "rebalance_enabled": True,
        "rebalance_schedule": "weekly",
        "rebalance_day_of_week": 0,
        "rebalance_day_of_month": 1,
        "rebalance_hour": 9,
    }
    defaults.update(kwargs)
    return PortfolioSettings(**defaults)  # type: ignore[arg-type]


# ───────────────── next_run_time 테스트 ─────────────────


class TestNextRunTimeDaily:
    """일별 스케줄 next_run_time 테스트"""

    def test_before_run_time_returns_today(self) -> None:
        """실행 시간 전이면 오늘 반환"""
        config = _make_config(rebalance_schedule="daily", rebalance_hour=9)
        scheduler = RebalanceScheduler(config)

        now = _kst(2026, 2, 14, 8, 0)  # 토요일 08:00 KST
        result = scheduler.next_run_time(now)

        assert result.hour == 9
        assert result.day == 14

    def test_after_run_time_returns_tomorrow(self) -> None:
        """실행 시간 후면 내일 반환"""
        config = _make_config(rebalance_schedule="daily", rebalance_hour=9)
        scheduler = RebalanceScheduler(config)

        now = _kst(2026, 2, 14, 10, 0)  # 토요일 10:00 KST
        result = scheduler.next_run_time(now)

        assert result.hour == 9
        assert result.day == 15

    def test_exact_run_time_returns_tomorrow(self) -> None:
        """정확히 실행 시간이면 내일 반환"""
        config = _make_config(rebalance_schedule="daily", rebalance_hour=9)
        scheduler = RebalanceScheduler(config)

        now = _kst(2026, 2, 14, 9, 0)
        result = scheduler.next_run_time(now)

        assert result.day == 15


class TestNextRunTimeWeekly:
    """주별 스케줄 next_run_time 테스트"""

    def test_before_target_day(self) -> None:
        """목표 요일 전이면 이번 주 반환"""
        # 2026-02-11은 수요일(2), 목표 금요일(4)
        config = _make_config(
            rebalance_schedule="weekly",
            rebalance_day_of_week=4,
            rebalance_hour=9,
        )
        scheduler = RebalanceScheduler(config)

        now = _kst(2026, 2, 11, 8, 0)  # 수요일
        result = scheduler.next_run_time(now)

        assert result.weekday() == 4  # 금요일
        assert result.day == 13

    def test_after_target_day(self) -> None:
        """목표 요일이 지났으면 다음 주 반환"""
        # 2026-02-14은 토요일(5), 목표 월요일(0)
        config = _make_config(
            rebalance_schedule="weekly",
            rebalance_day_of_week=0,
            rebalance_hour=9,
        )
        scheduler = RebalanceScheduler(config)

        now = _kst(2026, 2, 14, 10, 0)  # 토요일
        result = scheduler.next_run_time(now)

        assert result.weekday() == 0  # 월요일
        assert result.day == 16

    def test_on_target_day_before_time(self) -> None:
        """목표 요일이지만 실행 시간 전이면 오늘 반환"""
        # 2026-02-09은 월요일(0)
        config = _make_config(
            rebalance_schedule="weekly",
            rebalance_day_of_week=0,
            rebalance_hour=9,
        )
        scheduler = RebalanceScheduler(config)

        now = _kst(2026, 2, 9, 8, 0)  # 월요일 08:00
        result = scheduler.next_run_time(now)

        assert result.weekday() == 0
        assert result.day == 9
        assert result.hour == 9

    def test_on_target_day_after_time(self) -> None:
        """목표 요일이지만 실행 시간 후면 다음 주 반환"""
        # 2026-02-09은 월요일(0)
        config = _make_config(
            rebalance_schedule="weekly",
            rebalance_day_of_week=0,
            rebalance_hour=9,
        )
        scheduler = RebalanceScheduler(config)

        now = _kst(2026, 2, 9, 10, 0)  # 월요일 10:00
        result = scheduler.next_run_time(now)

        assert result.weekday() == 0
        assert result.day == 16  # 다음 주 월요일


class TestNextRunTimeMonthly:
    """월별 스케줄 next_run_time 테스트"""

    def test_before_target_day(self) -> None:
        """목표일 전이면 이번 달 반환"""
        config = _make_config(
            rebalance_schedule="monthly",
            rebalance_day_of_month=15,
            rebalance_hour=9,
        )
        scheduler = RebalanceScheduler(config)

        now = _kst(2026, 2, 10, 8, 0)
        result = scheduler.next_run_time(now)

        assert result.month == 2
        assert result.day == 15
        assert result.hour == 9

    def test_after_target_day(self) -> None:
        """목표일이 지났으면 다음 달 반환"""
        config = _make_config(
            rebalance_schedule="monthly",
            rebalance_day_of_month=10,
            rebalance_hour=9,
        )
        scheduler = RebalanceScheduler(config)

        now = _kst(2026, 2, 14, 10, 0)
        result = scheduler.next_run_time(now)

        assert result.month == 3
        assert result.day == 10

    def test_december_to_january(self) -> None:
        """12월 → 1월 연도 전환"""
        config = _make_config(
            rebalance_schedule="monthly",
            rebalance_day_of_month=5,
            rebalance_hour=9,
        )
        scheduler = RebalanceScheduler(config)

        now = _kst(2026, 12, 10, 10, 0)
        result = scheduler.next_run_time(now)

        assert result.year == 2027
        assert result.month == 1
        assert result.day == 5

    def test_on_target_day_before_time(self) -> None:
        """목표일이지만 실행 시간 전이면 오늘 반환"""
        config = _make_config(
            rebalance_schedule="monthly",
            rebalance_day_of_month=14,
            rebalance_hour=9,
        )
        scheduler = RebalanceScheduler(config)

        now = _kst(2026, 2, 14, 8, 0)
        result = scheduler.next_run_time(now)

        assert result.month == 2
        assert result.day == 14
        assert result.hour == 9


# ───────────────── should_run 테스트 ─────────────────


class TestShouldRun:
    """should_run 판단 로직 테스트"""

    def test_disabled_returns_false(self) -> None:
        """비활성화 상태이면 항상 False"""
        config = _make_config(rebalance_enabled=False)
        scheduler = RebalanceScheduler(config)

        now = _kst(2026, 2, 9, 9, 0)  # 월요일 09:00 (실행 시간)
        assert scheduler.should_run(now) is False

    def test_enabled_in_window_returns_true(self) -> None:
        """활성화 + 실행 윈도우 내이면 True"""
        config = _make_config(
            rebalance_enabled=True,
            rebalance_schedule="weekly",
            rebalance_day_of_week=0,
            rebalance_hour=9,
        )
        scheduler = RebalanceScheduler(config)

        # 2026-02-09은 월요일(0), 09:30 KST → 실행 윈도우 내
        now = _kst(2026, 2, 9, 9, 30)
        assert scheduler.should_run(now) is True

    def test_outside_window_returns_false(self) -> None:
        """실행 윈도우 밖이면 False"""
        config = _make_config(
            rebalance_enabled=True,
            rebalance_schedule="weekly",
            rebalance_day_of_week=0,
            rebalance_hour=9,
        )
        scheduler = RebalanceScheduler(config)

        # 2026-02-09은 월요일(0), 11:00 KST → 실행 윈도우 밖 (09:00~10:00)
        now = _kst(2026, 2, 9, 11, 0)
        assert scheduler.should_run(now) is False

    def test_duplicate_run_prevention(self) -> None:
        """이미 실행한 경우 중복 실행 방지"""
        config = _make_config(
            rebalance_enabled=True,
            rebalance_schedule="daily",
            rebalance_hour=9,
        )
        scheduler = RebalanceScheduler(config)

        now = _kst(2026, 2, 14, 9, 30)

        # 첫 번째 실행은 True
        assert scheduler.should_run(now) is True

        # 실행 기록 설정
        scheduler.last_run_time = _kst(2026, 2, 14, 9, 5)

        # 같은 윈도우에서 두 번째 호출은 False
        assert scheduler.should_run(now) is False

    def test_daily_should_run(self) -> None:
        """일별 스케줄 should_run"""
        config = _make_config(
            rebalance_enabled=True,
            rebalance_schedule="daily",
            rebalance_hour=9,
        )
        scheduler = RebalanceScheduler(config)

        # 09:00 ~ 10:00 사이 → True
        assert scheduler.should_run(_kst(2026, 2, 14, 9, 0)) is True
        assert scheduler.should_run(_kst(2026, 2, 14, 9, 59)) is True

        # 10:00 이후 → False
        assert scheduler.should_run(_kst(2026, 2, 14, 10, 0)) is False

    def test_wrong_day_of_week(self) -> None:
        """주별 스케줄에서 다른 요일이면 False"""
        config = _make_config(
            rebalance_enabled=True,
            rebalance_schedule="weekly",
            rebalance_day_of_week=0,  # 월요일
            rebalance_hour=9,
        )
        scheduler = RebalanceScheduler(config)

        # 2026-02-14은 토요일(5)
        now = _kst(2026, 2, 14, 9, 30)
        assert scheduler.should_run(now) is False


# ───────────────── last_run_time 속성 테스트 ─────────────────


class TestLastRunTime:
    """last_run_time 속성 테스트"""

    def test_default_is_none(self) -> None:
        """초기값은 None"""
        scheduler = RebalanceScheduler(_make_config())
        assert scheduler.last_run_time is None

    def test_setter(self) -> None:
        """setter로 값 설정"""
        scheduler = RebalanceScheduler(_make_config())
        now = _kst(2026, 2, 14, 9, 0)
        scheduler.last_run_time = now
        assert scheduler.last_run_time == now

    def test_reset_to_none(self) -> None:
        """None으로 리셋"""
        scheduler = RebalanceScheduler(_make_config())
        scheduler.last_run_time = _kst(2026, 2, 14, 9, 0)
        scheduler.last_run_time = None
        assert scheduler.last_run_time is None


# ───────────────── UTC 입력 테스트 ─────────────────


class TestUTCInput:
    """UTC 시각 입력 시 KST 변환 검증"""

    def test_utc_to_kst_conversion(self) -> None:
        """UTC 시각이 KST로 올바르게 변환되는지 확인"""
        config = _make_config(
            rebalance_schedule="daily",
            rebalance_hour=9,
        )
        scheduler = RebalanceScheduler(config)

        # UTC 00:00 = KST 09:00
        utc_now = datetime(2026, 2, 14, 0, 0, tzinfo=timezone.utc)
        result = scheduler.next_run_time(utc_now)

        # KST 09:00에 해당하는 다음 실행 시각
        assert result.hour == 9
        assert result.tzinfo == KST

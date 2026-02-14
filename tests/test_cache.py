"""
MarketDataCache 테스트

DB 기반 캐싱 레이어를 테스트합니다.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.data.cache import MarketDataCache
from src.models.schema import Base, MarketData


# ───────────────────── Fixtures ─────────────────────


@pytest.fixture
def test_engine():
    """인메모리 SQLite DB 엔진"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def session_factory(test_engine):
    """테스트용 세션 팩토리"""
    return sessionmaker(bind=test_engine)


@pytest.fixture
def cache(session_factory):
    """MarketDataCache 인스턴스"""
    return MarketDataCache(session_factory)


@pytest.fixture
def sample_data(session_factory):
    """샘플 시세 데이터 (DB에 미리 저장)"""
    with session_factory() as session:
        data_list = [
            MarketData(
                stock_code="005930",
                date=datetime(2026, 2, 17),
                open_price=71000.0,
                high_price=71800.0,
                low_price=70800.0,
                close_price=71500.0,
                volume=10234567,
            ),
            MarketData(
                stock_code="005930",
                date=datetime(2026, 2, 18),
                open_price=71500.0,
                high_price=72200.0,
                low_price=71300.0,
                close_price=72000.0,
                volume=11234567,
            ),
            MarketData(
                stock_code="005930",
                date=datetime(2026, 2, 19),
                open_price=72000.0,
                high_price=72500.0,
                low_price=71800.0,
                close_price=72300.0,
                volume=12345678,
            ),
            MarketData(
                stock_code="000660",
                date=datetime(2026, 2, 17),
                open_price=50000.0,
                high_price=51000.0,
                low_price=49800.0,
                close_price=50500.0,
                volume=5000000,
            ),
        ]
        for data in data_list:
            session.add(data)
        session.commit()


# ───────────────────── Tests: get_cached ─────────────────────


def test_get_cached_hit(cache, sample_data):
    """캐시 히트 (데이터 있음)"""
    result = cache.get_cached("005930", date(2026, 2, 17), date(2026, 2, 19))

    assert result is not None
    assert len(result) == 3
    assert result[0].close_price == 71500.0
    assert result[1].close_price == 72000.0
    assert result[2].close_price == 72300.0


def test_get_cached_miss(cache, sample_data):
    """캐시 미스 (데이터 없음)"""
    result = cache.get_cached("999999", date(2026, 2, 17), date(2026, 2, 19))

    assert result is None


def test_get_cached_partial_range(cache, sample_data):
    """일부 날짜만 조회"""
    result = cache.get_cached("005930", date(2026, 2, 18), date(2026, 2, 18))

    assert result is not None
    assert len(result) == 1
    assert result[0].close_price == 72000.0


def test_get_cached_empty_range(cache, sample_data):
    """범위 밖 데이터"""
    result = cache.get_cached("005930", date(2026, 3, 1), date(2026, 3, 10))

    assert result is None


# ───────────────────── Tests: is_cached ─────────────────────


def test_is_cached_true(cache, sample_data):
    """캐시 존재"""
    assert cache.is_cached("005930", date(2026, 2, 17)) is True


def test_is_cached_false(cache, sample_data):
    """캐시 없음"""
    assert cache.is_cached("005930", date(2026, 2, 20)) is False
    assert cache.is_cached("999999", date(2026, 2, 17)) is False


# ───────────────────── Tests: get_missing_dates ─────────────────────


def test_get_missing_dates_none(cache, sample_data):
    """누락 없음 (모든 영업일 존재)"""
    missing = cache.get_missing_dates("005930", date(2026, 2, 17), date(2026, 2, 19))

    # 2026-02-17 (월), 18 (화), 19 (수) 모두 존재
    assert len(missing) == 0


def test_get_missing_dates_some(cache, sample_data):
    """일부 날짜 누락"""
    # 2026-02-17~2026-02-21 범위에서 영업일은 17, 18, 19, 20 (4일)
    # DB에는 17~19만 있으므로 20만 누락
    missing = cache.get_missing_dates("005930", date(2026, 2, 17), date(2026, 2, 21))

    assert len(missing) == 1
    assert date(2026, 2, 20) in missing


def test_get_missing_dates_all(cache, sample_data):
    """모든 날짜 누락 (새 종목)"""
    # 999999 종목은 DB에 없음
    missing = cache.get_missing_dates("999999", date(2026, 2, 17), date(2026, 2, 21))

    # 주말 제외: 17 (월), 18 (화), 19 (수), 20 (목)
    assert len(missing) == 4


def test_get_missing_dates_exclude_weekends(cache, sample_data):
    """주말은 누락으로 간주하지 않음"""
    # 2026-02-13 (금) ~ 2026-02-21 (토)
    missing = cache.get_missing_dates("005930", date(2026, 2, 13), date(2026, 2, 21))

    # 영업일: 13 (금), 16 (월), 17 (화), 18 (수), 19 (목), 20 (금)
    # DB에는 17~19만 있으므로 13, 16, 20이 누락
    assert len(missing) == 3
    assert date(2026, 2, 13) in missing
    assert date(2026, 2, 16) in missing
    assert date(2026, 2, 20) in missing
    # 주말은 포함되지 않음
    assert date(2026, 2, 14) not in missing  # 토
    assert date(2026, 2, 15) not in missing  # 일


# ───────────────────── Tests: invalidate ─────────────────────


def test_invalidate_all(cache, sample_data):
    """전체 캐시 무효화"""
    deleted = cache.invalidate("005930")

    assert deleted == 3

    # DB 확인
    result = cache.get_cached("005930", date(2026, 2, 17), date(2026, 2, 19))
    assert result is None


def test_invalidate_range(cache, sample_data):
    """특정 기간만 무효화"""
    deleted = cache.invalidate(
        "005930",
        start_date=date(2026, 2, 18),
        end_date=date(2026, 2, 18),
    )

    assert deleted == 1

    # 2026-02-18만 삭제됨
    assert cache.is_cached("005930", date(2026, 2, 17)) is True
    assert cache.is_cached("005930", date(2026, 2, 18)) is False
    assert cache.is_cached("005930", date(2026, 2, 19)) is True


def test_invalidate_no_match(cache, sample_data):
    """존재하지 않는 종목 무효화"""
    deleted = cache.invalidate("999999")

    assert deleted == 0


# ───────────────────── Tests: get_cache_stats ─────────────────────


def test_get_cache_stats(cache, sample_data):
    """캐시 통계 조회"""
    stats = cache.get_cache_stats()

    assert stats["total_records"] == 4
    assert stats["stock_count"] == 2
    assert stats["by_stock"]["005930"] == 3
    assert stats["by_stock"]["000660"] == 1


def test_get_cache_stats_empty(cache):
    """빈 캐시 통계"""
    stats = cache.get_cache_stats()

    assert stats["total_records"] == 0
    assert stats["stock_count"] == 0
    assert stats["by_stock"] == {}


# ───────────────────── Tests: _generate_business_dates ─────────────────────


def test_generate_business_dates_weekdays_only():
    """영업일 생성 (주말 제외)"""
    dates = MarketDataCache._generate_business_dates(
        date(2026, 2, 9),  # 월
        date(2026, 2, 15),  # 일
    )

    # 2026-02-09 (월) ~ 2026-02-13 (금), 주말 제외
    assert len(dates) == 5
    assert date(2026, 2, 9) in dates
    assert date(2026, 2, 10) in dates
    assert date(2026, 2, 11) in dates
    assert date(2026, 2, 12) in dates
    assert date(2026, 2, 13) in dates
    assert date(2026, 2, 14) not in dates  # 토
    assert date(2026, 2, 15) not in dates  # 일


def test_generate_business_dates_single_day():
    """단일 날짜"""
    dates = MarketDataCache._generate_business_dates(
        date(2026, 2, 17),
        date(2026, 2, 17),
    )

    assert len(dates) == 1
    assert date(2026, 2, 17) in dates

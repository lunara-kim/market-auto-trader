"""
DailyDataPipeline 테스트

MarketDataCollector를 모킹하여 외부 API 의존성 없이 테스트합니다.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.data.collector import MarketDataCollector
from src.data.pipeline import CollectionResult, DailyDataPipeline
from src.models.schema import Base, MarketData
from src.utils.retry import RetryExhaustedError


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
def mock_collector():
    """MarketDataCollector 모킹"""
    return Mock(spec=MarketDataCollector)


@pytest.fixture
def pipeline(mock_collector, session_factory):
    """DailyDataPipeline 인스턴스"""
    return DailyDataPipeline(mock_collector, session_factory)


@pytest.fixture
def sample_raw_data():
    """샘플 시세 데이터 (MarketDataCollector 반환 형식)"""
    return [
        {
            "date": "2026-02-17",
            "open": 71000,
            "high": 71800,
            "low": 70800,
            "close": 71500,
            "volume": 10234567,
        },
        {
            "date": "2026-02-18",
            "open": 71500,
            "high": 72200,
            "low": 71300,
            "close": 72000,
            "volume": 11234567,
        },
        {
            "date": "2026-02-19",
            "open": 72000,
            "high": 72500,
            "low": 71800,
            "close": 72300,
            "volume": 12345678,
        },
    ]


# ───────────────────── Tests: collect_single_stock ─────────────────────


def test_collect_single_stock_success(pipeline, mock_collector, sample_raw_data):
    """단일 종목 수집 성공"""
    mock_collector.fetch_stock_price.return_value = sample_raw_data

    result = pipeline.collect_single_stock(
        "005930",
        date(2026, 2, 17),
        date(2026, 2, 19),
    )

    assert len(result) == 3
    assert result[0].stock_code == "005930"
    assert result[0].close_price == 71500
    assert result[1].close_price == 72000
    assert result[2].close_price == 72300


def test_collect_single_stock_empty(pipeline, mock_collector):
    """수집 결과 없음"""
    mock_collector.fetch_stock_price.return_value = []

    result = pipeline.collect_single_stock(
        "005930",
        date(2026, 2, 17),
        date(2026, 2, 19),
    )

    assert len(result) == 0


def test_collect_single_stock_error(pipeline, mock_collector):
    """수집 실패 시 재시도 후 RetryExhaustedError 발생"""
    mock_collector.fetch_stock_price.side_effect = Exception("API 오류")

    with pytest.raises(RetryExhaustedError):
        pipeline.collect_single_stock(
            "005930",
            date(2026, 2, 17),
            date(2026, 2, 19),
        )


def test_collect_single_stock_partial_parsing_error(pipeline, mock_collector):
    """일부 레코드 파싱 실패 시 스킵"""
    invalid_data = [
        {
            "date": "2026-02-17",
            "open": 71000,
            "high": 71800,
            "low": 70800,
            "close": 71500,
            "volume": 10234567,
        },
        {
            "date": "invalid-date",  # 잘못된 날짜
            "open": None,
            "high": None,
            "low": None,
            "close": None,
            "volume": None,
        },
        {
            "date": "2026-02-19",
            "open": 72000,
            "high": 72500,
            "low": 71800,
            "close": 72300,
            "volume": 12345678,
        },
    ]
    mock_collector.fetch_stock_price.return_value = invalid_data

    result = pipeline.collect_single_stock(
        "005930",
        date(2026, 2, 17),
        date(2026, 2, 19),
    )

    # 유효한 레코드만 반환
    assert len(result) == 2


# ───────────────────── Tests: collect_and_store ─────────────────────


def test_collect_and_store_success(pipeline, mock_collector, sample_raw_data, session_factory):
    """여러 종목 수집 및 DB 저장 성공"""
    mock_collector.fetch_stock_price.return_value = sample_raw_data

    result = pipeline.collect_and_store(
        ["005930", "000660"],
        date(2026, 2, 17),
        date(2026, 2, 19),
    )

    # 2개 종목 × 3일 = 6건 성공
    assert result.success_count == 6
    assert result.fail_count == 0
    assert result.skipped_count == 0

    # DB 확인
    with session_factory() as session:
        stmt = select(MarketData).where(MarketData.stock_code == "005930")
        data_list = session.execute(stmt).scalars().all()
        assert len(data_list) == 3


def test_collect_and_store_skip_duplicates(pipeline, mock_collector, sample_raw_data, session_factory):
    """중복 데이터는 스킵"""
    mock_collector.fetch_stock_price.return_value = sample_raw_data

    # 첫 번째 수집
    result1 = pipeline.collect_and_store(
        ["005930"],
        date(2026, 2, 17),
        date(2026, 2, 19),
    )
    assert result1.success_count == 3
    assert result1.skipped_count == 0

    # 두 번째 수집 (동일 데이터)
    result2 = pipeline.collect_and_store(
        ["005930"],
        date(2026, 2, 17),
        date(2026, 2, 19),
    )
    assert result2.success_count == 0
    assert result2.skipped_count == 3


def test_collect_and_store_partial_failure(pipeline, mock_collector, sample_raw_data):
    """일부 종목 실패"""
    def side_effect(stock_code, start, end):
        if stock_code == "005930":
            return sample_raw_data
        else:
            raise Exception("API 오류")

    mock_collector.fetch_stock_price.side_effect = side_effect

    result = pipeline.collect_and_store(
        ["005930", "000660"],
        date(2026, 2, 17),
        date(2026, 2, 19),
    )

    assert result.success_count == 3
    assert result.fail_count == 1
    assert len(result.errors) == 1
    assert result.errors[0]["stock_code"] == "000660"


def test_collect_and_store_empty_list(pipeline):
    """빈 종목 리스트"""
    result = pipeline.collect_and_store(
        [],
        date(2026, 2, 17),
        date(2026, 2, 19),
    )

    assert result.success_count == 0
    assert result.fail_count == 0
    assert result.skipped_count == 0


# ───────────────────── Tests: run_daily_collection ─────────────────────


def test_run_daily_collection(pipeline, mock_collector, sample_raw_data):
    """일일 수집 실행"""
    # 오늘 날짜 1건만 반환하도록 모킹
    today_data = [sample_raw_data[0]]
    mock_collector.fetch_stock_price.return_value = today_data

    result = pipeline.run_daily_collection(["005930", "000660"])

    # 2개 종목
    assert result.success_count == 2


# ───────────────────── Tests: CollectionResult ─────────────────────


def test_collection_result_add_methods():
    """CollectionResult 메서드 테스트"""
    result = CollectionResult()

    result.add_success()
    result.add_success()
    result.add_fail("005930", "API 오류")
    result.add_skip()

    assert result.success_count == 2
    assert result.fail_count == 1
    assert result.skipped_count == 1
    assert len(result.errors) == 1
    assert result.errors[0]["stock_code"] == "005930"

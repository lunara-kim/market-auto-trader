"""
DataQualityValidator 테스트

시세 데이터 품질 검증을 테스트합니다.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from src.data.quality import DataQualityValidator, IssueSeverity
from src.models.schema import MarketData


# ───────────────────── Fixtures ─────────────────────


@pytest.fixture
def validator():
    """DataQualityValidator 인스턴스"""
    return DataQualityValidator()


@pytest.fixture
def valid_data():
    """유효한 OHLCV 데이터"""
    return MarketData(
        stock_code="005930",
        date=datetime(2026, 2, 17),
        open_price=71000.0,
        high_price=71800.0,
        low_price=70800.0,
        close_price=71500.0,
        volume=10234567,
    )


# ───────────────────── Tests: validate_ohlcv ─────────────────────


def test_validate_ohlcv_valid(validator, valid_data):
    """유효한 데이터는 이슈 없음"""
    issues = validator.validate_ohlcv(valid_data)

    assert len(issues) == 0


def test_validate_ohlcv_high_low_invalid(validator):
    """high < low 오류 (종가도 범위 밖이므로 여러 이슈 발생)"""
    invalid_data = MarketData(
        stock_code="005930",
        date=datetime(2026, 2, 17),
        open_price=71000.0,
        high_price=70000.0,  # 고가가 저가보다 낮음
        low_price=71000.0,
        close_price=70500.0,
        volume=10234567,
    )

    issues = validator.validate_ohlcv(invalid_data)

    assert len(issues) >= 1
    assert any(issue.issue_type == "invalid_high_low" for issue in issues)
    assert any(issue.severity == IssueSeverity.CRITICAL for issue in issues)


def test_validate_ohlcv_close_above_high(validator):
    """종가 > 고가 오류"""
    invalid_data = MarketData(
        stock_code="005930",
        date=datetime(2026, 2, 17),
        open_price=71000.0,
        high_price=71800.0,
        low_price=70800.0,
        close_price=72000.0,  # 종가가 고가보다 높음
        volume=10234567,
    )

    issues = validator.validate_ohlcv(invalid_data)

    assert len(issues) == 1
    assert issues[0].issue_type == "invalid_close"
    assert issues[0].severity == IssueSeverity.HIGH


def test_validate_ohlcv_close_below_low(validator):
    """종가 < 저가 오류"""
    invalid_data = MarketData(
        stock_code="005930",
        date=datetime(2026, 2, 17),
        open_price=71000.0,
        high_price=71800.0,
        low_price=70800.0,
        close_price=70500.0,  # 종가가 저가보다 낮음
        volume=10234567,
    )

    issues = validator.validate_ohlcv(invalid_data)

    assert len(issues) == 1
    assert issues[0].issue_type == "invalid_close"
    assert issues[0].severity == IssueSeverity.HIGH


def test_validate_ohlcv_negative_price(validator):
    """음수 가격 오류"""
    invalid_data = MarketData(
        stock_code="005930",
        date=datetime(2026, 2, 17),
        open_price=-100.0,  # 음수
        high_price=71800.0,
        low_price=70800.0,
        close_price=71500.0,
        volume=10234567,
    )

    issues = validator.validate_ohlcv(invalid_data)

    assert len(issues) >= 1
    assert any(issue.issue_type == "negative_price" for issue in issues)


def test_validate_ohlcv_zero_price(validator):
    """0 이하 가격 오류"""
    invalid_data = MarketData(
        stock_code="005930",
        date=datetime(2026, 2, 17),
        open_price=0.0,  # 0
        high_price=71800.0,
        low_price=70800.0,
        close_price=71500.0,
        volume=10234567,
    )

    issues = validator.validate_ohlcv(invalid_data)

    assert len(issues) >= 1
    assert any(issue.issue_type == "negative_price" for issue in issues)


def test_validate_ohlcv_negative_volume(validator):
    """음수 거래량 오류"""
    invalid_data = MarketData(
        stock_code="005930",
        date=datetime(2026, 2, 17),
        open_price=71000.0,
        high_price=71800.0,
        low_price=70800.0,
        close_price=71500.0,
        volume=-100,  # 음수
    )

    issues = validator.validate_ohlcv(invalid_data)

    assert len(issues) == 1
    assert issues[0].issue_type == "negative_volume"
    assert issues[0].severity == IssueSeverity.HIGH


def test_validate_ohlcv_missing_price(validator):
    """가격 누락 오류"""
    invalid_data = MarketData(
        stock_code="005930",
        date=datetime(2026, 2, 17),
        open_price=None,
        high_price=None,  # 누락
        low_price=None,  # 누락
        close_price=71500.0,
        volume=10234567,
    )

    issues = validator.validate_ohlcv(invalid_data)

    assert len(issues) >= 1
    assert any(issue.issue_type == "missing_price" for issue in issues)


# ───────────────────── Tests: detect_outliers ─────────────────────


def test_detect_outliers_normal_data(validator):
    """정상 데이터는 이상치 없음"""
    data_list = [
        MarketData(
            stock_code="005930",
            date=datetime(2026, 2, 17),
            open_price=71000.0,
            high_price=71800.0,
            low_price=70800.0,
            close_price=71500.0,
            volume=10000000,
        ),
        MarketData(
            stock_code="005930",
            date=datetime(2026, 2, 18),
            open_price=71500.0,
            high_price=72200.0,
            low_price=71300.0,
            close_price=72000.0,
            volume=11000000,
        ),
        MarketData(
            stock_code="005930",
            date=datetime(2026, 2, 19),
            open_price=72000.0,
            high_price=72500.0,
            low_price=71800.0,
            close_price=72300.0,
            volume=12000000,
        ),
    ]

    issues = validator.detect_outliers(data_list, z_threshold=3.0)

    assert len(issues) == 0


def test_detect_outliers_price_spike(validator):
    """급격한 가격 변동 감지"""
    # 완만한 변동을 가진 정상 구간 7일 + 마지막 날 약 30% 급등
    data_list = []
    base_prices = [
        71000.0,
        71200.0,
        71350.0,
        71400.0,
        71500.0,
        71600.0,
        71700.0,
    ]
    for i, close_price in enumerate(base_prices, start=17):
        data_list.append(
            MarketData(
                stock_code="005930",
                date=datetime(2026, 2, i),
                open_price=close_price - 100.0,
                high_price=close_price + 100.0,
                low_price=close_price - 200.0,
                close_price=close_price,
                volume=10000000 + i * 1000,
            ),
        )

    # 마지막 날 급등 (약 +30%)
    data_list.append(
        MarketData(
            stock_code="005930",
            date=datetime(2026, 2, 24),
            open_price=72000.0,
            high_price=95000.0,
            low_price=71800.0,
            close_price=93000.0,
            volume=13000000,
        ),
    )

    issues = validator.detect_outliers(data_list, z_threshold=2.0)

    assert len(issues) >= 1
    assert any(issue.issue_type == "price_outlier" for issue in issues)


def test_detect_outliers_volume_spike(validator):
    """비정상적인 거래량 감지"""
    data_list = []
    # 정상 구간: 거래량 9~11M 수준에서 작은 변동
    for i in range(7):
        close_price = 71500.0 + i * 100
        data_list.append(
            MarketData(
                stock_code="005930",
                date=datetime(2026, 2, 17 + i),
                open_price=close_price - 100.0,
                high_price=close_price + 100.0,
                low_price=close_price - 200.0,
                close_price=close_price,
                volume=9_000_000 + i * 100_000,
            ),
        )

    # 마지막 날 거래량 급증 (약 10배)
    data_list.append(
        MarketData(
            stock_code="005930",
            date=datetime(2026, 2, 24),
            open_price=72000.0,
            high_price=72500.0,
            low_price=71800.0,
            close_price=72300.0,
            volume=100_000_000,
        ),
    )

    issues = validator.detect_outliers(data_list, z_threshold=2.0)

    assert len(issues) >= 1
    assert any(issue.issue_type == "volume_outlier" for issue in issues)


def test_detect_outliers_insufficient_data(validator):
    """데이터 부족 시 이상치 검증 불가"""
    data_list = [
        MarketData(
            stock_code="005930",
            date=datetime(2026, 2, 17),
            open_price=71000.0,
            high_price=71800.0,
            low_price=70800.0,
            close_price=71500.0,
            volume=10000000,
        ),
    ]

    issues = validator.detect_outliers(data_list, z_threshold=3.0)

    assert len(issues) == 0


# ───────────────────── Tests: detect_missing_dates ─────────────────────


def test_detect_missing_dates_none(validator):
    """누락 없음"""
    existing_dates = [
        date(2026, 2, 17),  # 월
        date(2026, 2, 18),  # 화
        date(2026, 2, 19),  # 수
    ]

    missing = validator.detect_missing_dates(
        "005930",
        date(2026, 2, 17),
        date(2026, 2, 19),
        existing_dates,
    )

    assert len(missing) == 0


def test_detect_missing_dates_some(validator):
    """일부 날짜 누락"""
    existing_dates = [
        date(2026, 2, 17),  # 월
        # 2026-02-18 (화) 누락
        date(2026, 2, 19),  # 수
    ]

    missing = validator.detect_missing_dates(
        "005930",
        date(2026, 2, 17),
        date(2026, 2, 19),
        existing_dates,
    )

    assert len(missing) == 1
    assert date(2026, 2, 18) in missing


def test_detect_missing_dates_all(validator):
    """모든 날짜 누락"""
    existing_dates: list[date] = []

    missing = validator.detect_missing_dates(
        "005930",
        date(2026, 2, 17),  # 월
        date(2026, 2, 21),  # 토
        existing_dates,
    )

    # 월~금 (주말 제외): 17, 18, 19, 20
    assert len(missing) == 4


def test_detect_missing_dates_exclude_weekends(validator):
    """주말은 누락으로 간주하지 않음"""
    existing_dates = [
        date(2026, 2, 17),  # 화
        date(2026, 2, 18),  # 수
        date(2026, 2, 19),  # 목
    ]

    missing = validator.detect_missing_dates(
        "005930",
        date(2026, 2, 13),  # 금
        date(2026, 2, 21),  # 토
        existing_dates,
    )

    # 영업일: 13 (금), 16 (월), 17 (화), 18 (수), 19 (목), 20 (금)
    # existing_dates 에 17~19만 있으므로 13, 16, 20만 누락
    assert len(missing) == 3
    assert date(2026, 2, 13) in missing
    assert date(2026, 2, 16) in missing
    assert date(2026, 2, 20) in missing
    # 주말은 포함되지 않음
    assert date(2026, 2, 14) not in missing  # 토
    assert date(2026, 2, 15) not in missing  # 일


# ───────────────────── Tests: _generate_business_dates ─────────────────────


def test_generate_business_dates_weekdays_only(validator):
    """영업일 생성 (주말 제외)"""
    dates = validator._generate_business_dates(
        date(2026, 2, 9),  # 월
        date(2026, 2, 15),  # 일
    )

    # 월~금만: 9, 10, 11, 12, 13
    assert len(dates) == 5
    assert date(2026, 2, 9) in dates
    assert date(2026, 2, 10) in dates
    assert date(2026, 2, 11) in dates
    assert date(2026, 2, 12) in dates
    assert date(2026, 2, 13) in dates
    assert date(2026, 2, 14) not in dates  # 토
    assert date(2026, 2, 15) not in dates  # 일

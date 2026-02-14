"""
데이터 품질 검증

시세 데이터의 무결성 및 이상치를 검증합니다.

Usage::

    validator = DataQualityValidator()

    # OHLCV 검증
    issues = validator.validate_ohlcv(market_data)

    # 이상치 탐지
    data_list = [...]
    outliers = validator.detect_outliers(data_list, z_threshold=3.0)

    # 누락 날짜 탐지
    missing = validator.detect_missing_dates(
        "005930",
        date(2026, 1, 1),
        date(2026, 2, 14),
        [date(2026, 1, 2), date(2026, 1, 3), ...],
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum

from src.models.schema import MarketData
from src.utils.logger import get_logger

logger = get_logger(__name__)


class IssueSeverity(str, Enum):
    """이슈 심각도"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class QualityIssue:
    """데이터 품질 이슈"""

    stock_code: str
    date: date | None
    issue_type: str
    description: str
    severity: IssueSeverity


class DataQualityValidator:
    """데이터 품질 검증기

    OHLCV 데이터의 무결성, 이상치, 누락을 검증합니다.
    """

    def __init__(self) -> None:
        logger.info("DataQualityValidator 초기화")

    def validate_ohlcv(self, data: MarketData) -> list[QualityIssue]:
        """OHLCV 데이터 검증

        검증 항목:
        - high >= low
        - close between high and low
        - volume >= 0
        - 가격 > 0

        Args:
            data: MarketData 인스턴스

        Returns:
            발견된 이슈 리스트
        """
        issues: list[QualityIssue] = []

        # None 체크
        if data.high_price is None or data.low_price is None:
            issues.append(
                QualityIssue(
                    stock_code=data.stock_code,
                    date=data.date.date() if data.date else None,
                    issue_type="missing_price",
                    description="고가 또는 저가가 없습니다.",
                    severity=IssueSeverity.CRITICAL,
                ),
            )
            return issues

        # high >= low
        if data.high_price < data.low_price:
            issues.append(
                QualityIssue(
                    stock_code=data.stock_code,
                    date=data.date.date() if data.date else None,
                    issue_type="invalid_high_low",
                    description=f"고가({data.high_price}) < 저가({data.low_price})",
                    severity=IssueSeverity.CRITICAL,
                ),
            )

        # close between high and low
        if data.close_price is not None:
            if data.close_price > data.high_price:
                issues.append(
                    QualityIssue(
                        stock_code=data.stock_code,
                        date=data.date.date() if data.date else None,
                        issue_type="invalid_close",
                        description=f"종가({data.close_price}) > 고가({data.high_price})",
                        severity=IssueSeverity.HIGH,
                    ),
                )
            if data.close_price < data.low_price:
                issues.append(
                    QualityIssue(
                        stock_code=data.stock_code,
                        date=data.date.date() if data.date else None,
                        issue_type="invalid_close",
                        description=f"종가({data.close_price}) < 저가({data.low_price})",
                        severity=IssueSeverity.HIGH,
                    ),
                )

        # 가격 > 0
        for field_name, value in [
            ("시가", data.open_price),
            ("고가", data.high_price),
            ("저가", data.low_price),
            ("종가", data.close_price),
        ]:
            if value is not None and value <= 0:
                issues.append(
                    QualityIssue(
                        stock_code=data.stock_code,
                        date=data.date.date() if data.date else None,
                        issue_type="negative_price",
                        description=f"{field_name}가 0 이하입니다: {value}",
                        severity=IssueSeverity.CRITICAL,
                    ),
                )

        # volume >= 0
        if data.volume is not None and data.volume < 0:
            issues.append(
                QualityIssue(
                    stock_code=data.stock_code,
                    date=data.date.date() if data.date else None,
                    issue_type="negative_volume",
                    description=f"거래량이 음수입니다: {data.volume}",
                    severity=IssueSeverity.HIGH,
                ),
            )

        if issues:
            logger.warning(
                "OHLCV 검증 실패: %s (%s) — %d개 이슈",
                data.stock_code,
                data.date.date() if data.date else None,
                len(issues),
            )

        return issues

    def detect_outliers(
        self,
        data_list: list[MarketData],
        z_threshold: float = 3.0,
    ) -> list[QualityIssue]:
        """이상치 탐지 (Z-score 기반)

        Args:
            data_list: MarketData 리스트 (시간순 정렬 필요)
            z_threshold: Z-score 임계값 (기본 3.0)

        Returns:
            이상치 이슈 리스트
        """
        if len(data_list) < 3:
            return []

        issues: list[QualityIssue] = []

        # 가격 변동률 계산
        price_changes: list[float] = []
        volume_list: list[int] = []

        for i in range(1, len(data_list)):
            prev = data_list[i - 1]
            curr = data_list[i]

            if prev.close_price and curr.close_price:
                change_rate = (
                    (curr.close_price - prev.close_price) / prev.close_price * 100
                )
                price_changes.append(change_rate)

            if curr.volume is not None:
                volume_list.append(curr.volume)

        # 가격 변동 이상치
        if len(price_changes) >= 3:
            mean_change = sum(price_changes) / len(price_changes)
            std_change = (
                sum((x - mean_change) ** 2 for x in price_changes) / len(price_changes)
            ) ** 0.5

            if std_change > 0:
                for i, change in enumerate(price_changes):
                    z_score = abs((change - mean_change) / std_change)
                    if z_score > z_threshold:
                        data = data_list[i + 1]
                        issues.append(
                            QualityIssue(
                                stock_code=data.stock_code,
                                date=data.date.date() if data.date else None,
                                issue_type="price_outlier",
                                description=(
                                    f"급격한 가격 변동: {change:.2f}% "
                                    f"(Z-score: {z_score:.2f})"
                                ),
                                severity=(
                                    IssueSeverity.HIGH
                                    if z_score > z_threshold * 1.5
                                    else IssueSeverity.MEDIUM
                                ),
                            ),
                        )

        # 거래량 이상치
        if len(volume_list) >= 3:
            mean_volume = sum(volume_list) / len(volume_list)
            std_volume = (
                sum((x - mean_volume) ** 2 for x in volume_list) / len(volume_list)
            ) ** 0.5

            if std_volume > 0:
                for i, volume in enumerate(volume_list):
                    z_score = abs((volume - mean_volume) / std_volume)
                    if z_score > z_threshold:
                        data = data_list[i]
                        issues.append(
                            QualityIssue(
                                stock_code=data.stock_code,
                                date=data.date.date() if data.date else None,
                                issue_type="volume_outlier",
                                description=(
                                    f"비정상적인 거래량: {volume:,} "
                                    f"(평균: {mean_volume:,.0f}, Z-score: {z_score:.2f})"
                                ),
                                severity=(
                                    IssueSeverity.MEDIUM
                                    if z_score > z_threshold * 1.5
                                    else IssueSeverity.LOW
                                ),
                            ),
                        )

        if issues:
            logger.info(
                "이상치 탐지: %s — %d개 이슈 (총 %d건 중)",
                data_list[0].stock_code if data_list else "N/A",
                len(issues),
                len(data_list),
            )

        return issues

    def detect_missing_dates(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
        existing_dates: list[date],
    ) -> list[date]:
        """영업일 기준 누락 날짜 탐지 (주말 제외)

        Args:
            stock_code: 종목 코드
            start_date: 시작일
            end_date: 종료일
            existing_dates: 기존 데이터가 있는 날짜 리스트

        Returns:
            누락된 영업일 리스트
        """
        # 모든 영업일 생성 (주말 제외)
        all_business_dates = self._generate_business_dates(start_date, end_date)

        # 차집합
        existing_set = set(existing_dates)
        missing = [d for d in all_business_dates if d not in existing_set]

        if missing:
            logger.warning(
                "누락 날짜 탐지: %s — %d일 누락 (총 %d일 중)",
                stock_code,
                len(missing),
                len(all_business_dates),
            )

        return missing

    @staticmethod
    def _generate_business_dates(start_date: date, end_date: date) -> list[date]:
        """영업일 리스트 생성 (주말 제외)

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

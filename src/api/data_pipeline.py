"""
데이터 파이프라인 API 엔드포인트

데이터 수집, 캐시 관리, 품질 검증 엔드포인트를 제공합니다.

Endpoints:
    - POST /api/v1/data/collect — 수동 데이터 수집
    - GET /api/v1/data/cache/stats — 캐시 통계
    - GET /api/v1/data/quality/{stock_code} — 데이터 품질 리포트
    - DELETE /api/v1/data/cache/{stock_code} — 캐시 무효화
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from src.api.dependencies import get_kis_client
from src.data.cache import MarketDataCache
from src.data.collector import MarketDataCollector
from src.data.pipeline import CollectionResult, DailyDataPipeline
from src.data.quality import DataQualityValidator, QualityIssue
from src.db import get_session_factory
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/data", tags=["DataPipeline"])


# ───────────────────── Request/Response Models ─────────────────────


class CollectRequest(BaseModel):
    """데이터 수집 요청"""

    stock_codes: list[str] = Field(..., description="종목 코드 리스트", min_length=1)
    start_date: date = Field(..., description="시작일 (YYYY-MM-DD)")
    end_date: date = Field(..., description="종료일 (YYYY-MM-DD)")


class CollectResponse(BaseModel):
    """데이터 수집 응답"""

    success_count: int = Field(..., description="성공 건수")
    fail_count: int = Field(..., description="실패 건수")
    skipped_count: int = Field(..., description="스킵 건수")
    errors: list[dict[str, str]] = Field(..., description="에러 내역")


class CacheStatsResponse(BaseModel):
    """캐시 통계 응답"""

    total_records: int = Field(..., description="총 레코드 수")
    stock_count: int = Field(..., description="종목 수")
    by_stock: dict[str, int] = Field(..., description="종목별 레코드 수")


class QualityIssueResponse(BaseModel):
    """품질 이슈 응답"""

    stock_code: str
    date: date | None
    issue_type: str
    description: str
    severity: str


class QualityReportResponse(BaseModel):
    """데이터 품질 리포트 응답"""

    stock_code: str
    start_date: date
    end_date: date
    total_records: int
    issues: list[QualityIssueResponse]
    summary: dict[str, int]


class CacheInvalidateResponse(BaseModel):
    """캐시 무효화 응답"""

    deleted_count: int = Field(..., description="삭제된 레코드 수")


# ───────────────────── Endpoints ─────────────────────


@router.post("/collect", response_model=CollectResponse)
async def collect_data(
    request: CollectRequest,
    kis_client=Depends(get_kis_client),
    session_factory=Depends(get_session_factory),
) -> CollectResponse:
    """
    수동 데이터 수집

    지정된 종목들의 시세 데이터를 수집하여 DB에 저장합니다.
    이미 존재하는 데이터는 스킵됩니다.
    """
    logger.info(
        "데이터 수집 요청: %d개 종목 (%s ~ %s)",
        len(request.stock_codes),
        request.start_date,
        request.end_date,
    )

    collector = MarketDataCollector(kis_client)
    pipeline = DailyDataPipeline(collector, session_factory)

    result: CollectionResult = pipeline.collect_and_store(
        request.stock_codes,
        request.start_date,
        request.end_date,
    )

    return CollectResponse(
        success_count=result.success_count,
        fail_count=result.fail_count,
        skipped_count=result.skipped_count,
        errors=result.errors,
    )


@router.get("/cache/stats", response_model=CacheStatsResponse)
async def get_cache_stats(
    session_factory=Depends(get_session_factory),
) -> CacheStatsResponse:
    """
    캐시 통계 조회

    DB에 저장된 시세 데이터 통계를 반환합니다.
    """
    logger.info("캐시 통계 조회 요청")

    cache = MarketDataCache(session_factory)
    stats = cache.get_cache_stats()

    return CacheStatsResponse(
        total_records=stats["total_records"],
        stock_count=stats["stock_count"],
        by_stock=stats["by_stock"],
    )


@router.get("/quality/{stock_code}", response_model=QualityReportResponse)
async def get_quality_report(
    stock_code: str,
    start_date: date | None = None,
    end_date: date | None = None,
    session_factory=Depends(get_session_factory),
) -> QualityReportResponse:
    """
    데이터 품질 리포트 조회

    특정 종목의 데이터 품질 이슈를 검증합니다.
    OHLCV 무결성, 이상치, 누락 날짜를 분석합니다.
    """
    logger.info("품질 리포트 요청: %s", stock_code)

    # 기본값: 최근 30일
    if not end_date:
        end_date = date.today()
    if not start_date:
        start_date = date(end_date.year, end_date.month, 1)

    cache = MarketDataCache(session_factory)
    validator = DataQualityValidator()

    # 데이터 조회
    data_list = cache.get_cached(stock_code, start_date, end_date)

    if not data_list:
        return QualityReportResponse(
            stock_code=stock_code,
            start_date=start_date,
            end_date=end_date,
            total_records=0,
            issues=[],
            summary={},
        )

    # 품질 검증
    all_issues: list[QualityIssue] = []

    # 1. OHLCV 검증
    for data in data_list:
        issues = validator.validate_ohlcv(data)
        all_issues.extend(issues)

    # 2. 이상치 탐지
    outliers = validator.detect_outliers(data_list)
    all_issues.extend(outliers)

    # 3. 누락 날짜 탐지
    existing_dates = [d.date.date() for d in data_list if d.date]
    missing_dates = validator.detect_missing_dates(
        stock_code,
        start_date,
        end_date,
        existing_dates,
    )

    # 누락 날짜를 이슈로 변환
    for missing_date in missing_dates:
        all_issues.append(
            QualityIssue(
                stock_code=stock_code,
                date=missing_date,
                issue_type="missing_date",
                description=f"영업일 데이터 누락: {missing_date}",
                severity="medium",
            ),
        )

    # 요약 통계
    summary = {
        "total_issues": len(all_issues),
        "critical": len([i for i in all_issues if i.severity == "critical"]),
        "high": len([i for i in all_issues if i.severity == "high"]),
        "medium": len([i for i in all_issues if i.severity == "medium"]),
        "low": len([i for i in all_issues if i.severity == "low"]),
    }

    logger.info(
        "품질 리포트 완료: %s — %d건 데이터, %d개 이슈",
        stock_code,
        len(data_list),
        len(all_issues),
    )

    return QualityReportResponse(
        stock_code=stock_code,
        start_date=start_date,
        end_date=end_date,
        total_records=len(data_list),
        issues=[
            QualityIssueResponse(
                stock_code=issue.stock_code,
                date=issue.date,
                issue_type=issue.issue_type,
                description=issue.description,
                severity=issue.severity,
            )
            for issue in all_issues
        ],
        summary=summary,
    )


@router.delete("/cache/{stock_code}", response_model=CacheInvalidateResponse)
async def invalidate_cache(
    stock_code: str,
    start_date: date | None = None,
    end_date: date | None = None,
    session_factory=Depends(get_session_factory),
) -> CacheInvalidateResponse:
    """
    캐시 무효화

    특정 종목의 캐시 데이터를 삭제합니다.
    start_date, end_date를 지정하면 해당 기간만 삭제합니다.
    """
    logger.info("캐시 무효화 요청: %s (%s ~ %s)", stock_code, start_date, end_date)

    cache = MarketDataCache(session_factory)
    deleted = cache.invalidate(stock_code, start_date, end_date)

    return CacheInvalidateResponse(deleted_count=deleted)

"""
RSS 뉴스 수집기

네이버 경제뉴스, Reuters, Google News RSS 피드에서
헤드라인을 비동기로 수집합니다.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import feedparser
import httpx

from src.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------


@dataclass
class NewsHeadline:
    """뉴스 헤드라인"""

    title: str
    source: str
    url: str
    published_at: datetime
    category: str = "general"


# ---------------------------------------------------------------------------
# Default RSS Sources
# ---------------------------------------------------------------------------

DEFAULT_SOURCES: list[str] = [
    "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtdHZHZ0pMVWlnQVAB?hl=ko&gl=KR&ceid=KR:ko",  # Google News 경제
    "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml",  # NYT Business
    "https://feeds.bbci.co.uk/news/business/rss.xml",  # BBC Business
]


# ---------------------------------------------------------------------------
# NewsCollector
# ---------------------------------------------------------------------------


class NewsCollector:
    """RSS 피드에서 뉴스 헤드라인을 비동기로 수집"""

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self._client = http_client

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        return httpx.AsyncClient(timeout=15)

    async def fetch_headlines(
        self, sources: list[str] | None = None
    ) -> list[NewsHeadline]:
        """RSS 소스에서 헤드라인 수집 (중복 제거)

        Args:
            sources: RSS URL 목록. None이면 DEFAULT_SOURCES 사용.

        Returns:
            중복 제거된 NewsHeadline 리스트 (최신순 정렬)
        """
        feeds = DEFAULT_SOURCES if sources is None else sources
        client = await self._get_client()
        owns_client = self._client is None

        try:
            tasks = [self._fetch_single(client, url) for url in feeds]
            results = await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            if owns_client:
                await client.aclose()

        headlines: list[NewsHeadline] = []
        seen_urls: set[str] = set()

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.warning("RSS 수집 실패 (%s): %s", feeds[i], result)
                continue
            assert isinstance(result, list)
            for h in result:
                if h.url not in seen_urls:
                    seen_urls.add(h.url)
                    headlines.append(h)

        headlines.sort(key=lambda h: h.published_at, reverse=True)
        logger.info("뉴스 헤드라인 %d건 수집 완료", len(headlines))
        return headlines

    async def _fetch_single(
        self, client: httpx.AsyncClient, url: str
    ) -> list[NewsHeadline]:
        """단일 RSS 피드 수집"""
        resp = await client.get(
            url, headers={"User-Agent": "market-auto-trader/1.0"}
        )
        resp.raise_for_status()
        feed = feedparser.parse(resp.text)
        source_title = feed.feed.get("title", url)

        headlines: list[NewsHeadline] = []
        for entry in feed.entries:
            published_at = self._parse_date(entry)
            headlines.append(
                NewsHeadline(
                    title=entry.get("title", ""),
                    source=source_title,
                    url=entry.get("link", ""),
                    published_at=published_at,
                    category=self._detect_category(entry),
                )
            )
        return headlines

    @staticmethod
    def _parse_date(entry: dict) -> datetime:  # type: ignore[type-arg]
        """RSS 엔트리에서 날짜 파싱"""
        for key in ("published", "updated"):
            raw = entry.get(key)
            if raw:
                try:
                    return parsedate_to_datetime(raw)
                except Exception:
                    pass
        return datetime.now(tz=timezone.utc)

    @staticmethod
    def _detect_category(entry: dict) -> str:  # type: ignore[type-arg]
        """태그/카테고리 감지"""
        tags = entry.get("tags", [])
        if tags:
            return tags[0].get("term", "general")
        return "general"

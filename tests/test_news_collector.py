"""
뉴스 수집기 테스트
"""

from __future__ import annotations


import httpx
import pytest

from src.analysis.news_collector import (
    DEFAULT_SOURCES,
    NewsCollector,
    _get_source_category,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test News</title>
    <item>
      <title>Economy grows 3%</title>
      <link>https://example.com/article1</link>
      <pubDate>Mon, 19 Feb 2024 10:00:00 GMT</pubDate>
      <category>economy</category>
    </item>
    <item>
      <title>Fed raises rates</title>
      <link>https://example.com/article2</link>
      <pubDate>Mon, 19 Feb 2024 09:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>"""

SAMPLE_RSS_2 = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Other News</title>
    <item>
      <title>Trade deal signed</title>
      <link>https://example.com/article3</link>
      <pubDate>Mon, 19 Feb 2024 08:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Economy grows 3%</title>
      <link>https://example.com/article1</link>
      <pubDate>Mon, 19 Feb 2024 10:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>"""


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestNewsCollector:
    @pytest.mark.asyncio
    async def test_fetch_headlines_parses_rss(self) -> None:
        """RSS 피드를 정상적으로 파싱한다"""
        transport = httpx.MockTransport(
            lambda req: httpx.Response(200, text=SAMPLE_RSS)
        )
        client = httpx.AsyncClient(transport=transport)
        collector = NewsCollector(http_client=client)

        headlines = await collector.fetch_headlines(
            sources=["https://example.com/rss"]
        )

        assert len(headlines) == 2
        assert headlines[0].title == "Economy grows 3%"
        assert headlines[0].source == "Test News"
        assert headlines[0].url == "https://example.com/article1"

    @pytest.mark.asyncio
    async def test_deduplication_by_url(self) -> None:
        """URL 기반 중복 제거"""
        call_count = 0

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(200, text=SAMPLE_RSS)
            return httpx.Response(200, text=SAMPLE_RSS_2)

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        collector = NewsCollector(http_client=client)

        headlines = await collector.fetch_headlines(
            sources=["https://a.com/rss", "https://b.com/rss"]
        )

        urls = [h.url for h in headlines]
        assert len(urls) == len(set(urls)), "중복 URL이 존재함"
        assert len(headlines) == 3  # article1, article2, article3

    @pytest.mark.asyncio
    async def test_error_handling_partial_failure(self) -> None:
        """일부 소스 실패 시 나머지 계속 수집"""
        call_count = 0

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(500, text="Internal Server Error")
            return httpx.Response(200, text=SAMPLE_RSS)

        transport = httpx.MockTransport(handler)
        client = httpx.AsyncClient(transport=transport)
        collector = NewsCollector(http_client=client)

        headlines = await collector.fetch_headlines(
            sources=["https://fail.com/rss", "https://ok.com/rss"]
        )

        assert len(headlines) == 2

    @pytest.mark.asyncio
    async def test_empty_sources(self) -> None:
        """빈 소스 리스트"""
        transport = httpx.MockTransport(
            lambda req: httpx.Response(200, text=SAMPLE_RSS)
        )
        client = httpx.AsyncClient(transport=transport)
        collector = NewsCollector(http_client=client)

        headlines = await collector.fetch_headlines(sources=[])
        assert headlines == []

    @pytest.mark.asyncio
    async def test_sorted_by_date_descending(self) -> None:
        """최신순 정렬 확인"""
        transport = httpx.MockTransport(
            lambda req: httpx.Response(200, text=SAMPLE_RSS)
        )
        client = httpx.AsyncClient(transport=transport)
        collector = NewsCollector(http_client=client)

        headlines = await collector.fetch_headlines(
            sources=["https://example.com/rss"]
        )

        for i in range(len(headlines) - 1):
            assert headlines[i].published_at >= headlines[i + 1].published_at

    @pytest.mark.asyncio
    async def test_category_detection(self) -> None:
        """카테고리 감지"""
        transport = httpx.MockTransport(
            lambda req: httpx.Response(200, text=SAMPLE_RSS)
        )
        client = httpx.AsyncClient(transport=transport)
        collector = NewsCollector(http_client=client)

        headlines = await collector.fetch_headlines(
            sources=["https://example.com/rss"]
        )

        # First article has <category>economy</category>
        economy_article = [h for h in headlines if h.title == "Economy grows 3%"]
        assert economy_article[0].category == "economy"


class TestKRNewsSources:
    """한국 경제뉴스 RSS 소스 관련 테스트"""

    def test_default_sources_include_kr_feeds(self) -> None:
        """DEFAULT_SOURCES에 한국 경제뉴스 소스가 포함되어 있다"""
        source_urls = " ".join(DEFAULT_SOURCES)
        assert "hankyung.com" in source_urls
        assert "mk.co.kr" in source_urls
        assert "sedaily.com" in source_urls
        assert "yna.co.kr" in source_urls

    def test_default_sources_include_keyword_feeds(self) -> None:
        """DEFAULT_SOURCES에 Google News 키워드 피드가 포함되어 있다"""
        keyword_feeds = [
            s for s in DEFAULT_SOURCES if "news.google.com/rss/search" in s
        ]
        assert len(keyword_feeds) >= 2

    def test_source_category_mapping(self) -> None:
        """소스별 카테고리가 올바르게 매핑된다"""
        assert (
            _get_source_category("https://www.hankyung.com/feed/economy")
            == "domestic_economy"
        )
        assert (
            _get_source_category("https://www.mk.co.kr/rss/30100041/")
            == "domestic_economy"
        )
        assert (
            _get_source_category("https://www.sedaily.com/rss/economy")
            == "domestic_economy"
        )
        assert (
            _get_source_category("https://www.yna.co.kr/rss/economy.xml")
            == "domestic_economy"
        )
        assert (
            _get_source_category(
                "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml"
            )
            == "global_economy"
        )
        assert (
            _get_source_category(
                "https://feeds.bbci.co.uk/news/business/rss.xml"
            )
            == "global_economy"
        )

    def test_google_search_feeds_are_stock_market(self) -> None:
        """Google News 키워드 피드는 stock_market 카테고리"""
        url = "https://news.google.com/rss/search?q=코스피&hl=ko"
        assert _get_source_category(url) == "stock_market"

    def test_unknown_source_returns_general(self) -> None:
        """알 수 없는 소스는 general 카테고리"""
        assert _get_source_category("https://unknown.com/rss") == "general"

    @pytest.mark.asyncio
    async def test_source_category_applied_to_headlines(self) -> None:
        """소스 카테고리가 태그 없는 엔트리에 적용된다"""
        rss_no_tags = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>한국경제</title>
    <item>
      <title>코스피 상승</title>
      <link>https://example.com/kospi</link>
      <pubDate>Mon, 19 Feb 2024 10:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>"""
        transport = httpx.MockTransport(
            lambda req: httpx.Response(200, text=rss_no_tags)
        )
        client = httpx.AsyncClient(transport=transport)
        collector = NewsCollector(http_client=client)

        headlines = await collector.fetch_headlines(
            sources=["https://www.hankyung.com/feed/economy"]
        )

        assert len(headlines) == 1
        assert headlines[0].category == "domestic_economy"

    @pytest.mark.asyncio
    async def test_entry_tag_overrides_source_category(self) -> None:
        """엔트리 자체 태그가 소스 카테고리보다 우선한다"""
        rss_with_tag = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>한국경제</title>
    <item>
      <title>정치 뉴스</title>
      <link>https://example.com/politics</link>
      <pubDate>Mon, 19 Feb 2024 10:00:00 GMT</pubDate>
      <category>politics</category>
    </item>
  </channel>
</rss>"""
        transport = httpx.MockTransport(
            lambda req: httpx.Response(200, text=rss_with_tag)
        )
        client = httpx.AsyncClient(transport=transport)
        collector = NewsCollector(http_client=client)

        headlines = await collector.fetch_headlines(
            sources=["https://www.hankyung.com/feed/economy"]
        )

        assert headlines[0].category == "politics"

    def test_default_sources_preserve_original_three(self) -> None:
        """기존 3개 소스가 유지된다"""
        original = [
            "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtdHZHZ0pMVWlnQVAB?hl=ko&gl=KR&ceid=KR:ko",
            "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml",
            "https://feeds.bbci.co.uk/news/business/rss.xml",
        ]
        for url in original:
            assert url in DEFAULT_SOURCES

    def test_default_sources_count(self) -> None:
        """DEFAULT_SOURCES는 10개 소스를 포함한다"""
        assert len(DEFAULT_SOURCES) == 10

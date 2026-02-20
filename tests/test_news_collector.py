"""
뉴스 수집기 테스트
"""

from __future__ import annotations


import httpx
import pytest

from src.analysis.news_collector import NewsCollector

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

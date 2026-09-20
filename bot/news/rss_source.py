"""Fuente de noticias vía feeds RSS (gratis, sin API key)."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from time import mktime

import feedparser

from bot.models import NewsItem
from bot.news.base import NewsSource

logger = logging.getLogger(__name__)


class RssNewsSource(NewsSource):
    name = "rss"

    def __init__(self, feed_urls: list[str]):
        self.feed_urls = feed_urls

    async def fetch_latest(self) -> list[NewsItem]:
        results = await asyncio.gather(
            *(self._fetch_one(url) for url in self.feed_urls),
            return_exceptions=True,
        )
        items: list[NewsItem] = []
        for url, result in zip(self.feed_urls, results):
            if isinstance(result, Exception):
                logger.warning("RSS %s falló: %s", url, result)
                continue
            items.extend(result)
        return items

    async def _fetch_one(self, url: str) -> list[NewsItem]:
        parsed = await asyncio.to_thread(feedparser.parse, url)
        items: list[NewsItem] = []
        for entry in parsed.entries:
            published = self._parse_time(entry)
            items.append(
                NewsItem(
                    source=f"rss:{parsed.feed.get('title', url)}",
                    title=entry.get("title", ""),
                    summary=entry.get("summary", entry.get("description", "")),
                    url=entry.get("link", ""),
                    published_at=published,
                )
            )
        return items

    @staticmethod
    def _parse_time(entry) -> datetime:
        struct = entry.get("published_parsed") or entry.get("updated_parsed")
        if struct:
            return datetime.fromtimestamp(mktime(struct), tz=timezone.utc)
        return datetime.now(timezone.utc)

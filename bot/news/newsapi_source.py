"""Fuente de noticias vía NewsAPI.org (requiere API key)."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import requests

from bot.models import NewsItem
from bot.news.base import NewsSource

logger = logging.getLogger(__name__)

_ENDPOINT = "https://newsapi.org/v2/top-headlines"


class NewsApiSource(NewsSource):
    name = "newsapi"

    def __init__(self, api_key: str, category: str = "business", page_size: int = 50):
        self.api_key = api_key
        self.category = category
        self.page_size = page_size

    async def fetch_latest(self) -> list[NewsItem]:
        return await asyncio.to_thread(self._fetch_sync)

    def _fetch_sync(self) -> list[NewsItem]:
        try:
            resp = requests.get(
                _ENDPOINT,
                params={
                    "category": self.category,
                    "language": "en",
                    "pageSize": self.page_size,
                    "apiKey": self.api_key,
                },
                timeout=10,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("NewsAPI falló: %s", exc)
            return []

        items: list[NewsItem] = []
        for article in resp.json().get("articles", []):
            published = self._parse_time(article.get("publishedAt"))
            items.append(
                NewsItem(
                    source=f"newsapi:{article.get('source', {}).get('name', 'unknown')}",
                    title=article.get("title") or "",
                    summary=article.get("description") or "",
                    url=article.get("url") or "",
                    published_at=published,
                )
            )
        return items

    @staticmethod
    def _parse_time(value: str | None) -> datetime:
        if not value:
            return datetime.now(timezone.utc)
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return datetime.now(timezone.utc)

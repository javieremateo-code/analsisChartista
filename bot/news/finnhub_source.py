"""Fuente de noticias vía Finnhub (requiere API key, tiene capa gratuita)."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import requests

from bot.models import NewsItem
from bot.news.base import NewsSource

logger = logging.getLogger(__name__)

_ENDPOINT = "https://finnhub.io/api/v1/news"


class FinnhubNewsSource(NewsSource):
    name = "finnhub"

    def __init__(self, api_key: str, category: str = "general"):
        self.api_key = api_key
        self.category = category

    async def fetch_latest(self) -> list[NewsItem]:
        return await asyncio.to_thread(self._fetch_sync)

    def _fetch_sync(self) -> list[NewsItem]:
        try:
            resp = requests.get(
                _ENDPOINT,
                params={"category": self.category, "token": self.api_key},
                timeout=10,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("Finnhub falló: %s", exc)
            return []

        items: list[NewsItem] = []
        for article in resp.json():
            ts = article.get("datetime")
            published = (
                datetime.fromtimestamp(ts, tz=timezone.utc) if ts else datetime.now(timezone.utc)
            )
            items.append(
                NewsItem(
                    source=f"finnhub:{article.get('source', 'unknown')}",
                    title=article.get("headline") or "",
                    summary=article.get("summary") or "",
                    url=article.get("url") or "",
                    published_at=published,
                )
            )
        return items

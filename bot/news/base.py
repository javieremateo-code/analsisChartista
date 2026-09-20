"""Interfaz común para cualquier fuente de noticias."""
from __future__ import annotations

from abc import ABC, abstractmethod

from bot.models import NewsItem


class NewsSource(ABC):
    name: str = "base"

    @abstractmethod
    async def fetch_latest(self) -> list[NewsItem]:
        """Devuelve los items de noticias más recientes disponibles en esta fuente."""
        raise NotImplementedError

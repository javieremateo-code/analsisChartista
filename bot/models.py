"""Tipos de datos compartidos: noticias y señales de trading."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class NewsItem:
    source: str
    title: str
    summary: str
    url: str
    published_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def id(self) -> str:
        """Identificador estable para deduplicar entre fuentes/ciclos."""
        basis = self.url or f"{self.source}:{self.title}"
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()

    @property
    def text(self) -> str:
        return f"{self.title}. {self.summary}".strip()


@dataclass
class Signal:
    news: NewsItem
    ticker: str
    direction: str  # "buy" | "sell"
    confidence: float  # 0..1
    category: str
    reason: str

    def __post_init__(self) -> None:
        if self.direction not in ("buy", "sell"):
            raise ValueError(f"direction inválida: {self.direction}")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence fuera de rango: {self.confidence}")

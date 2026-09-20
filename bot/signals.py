"""Motor de señales: dedupe de noticias + clasificación + cooldown por ticker."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Protocol

from bot.models import NewsItem, Signal
from bot.storage import Storage

logger = logging.getLogger(__name__)


class Classifier(Protocol):
    def classify(self, news: NewsItem) -> list[Signal]: ...


class SignalEngine:
    def __init__(self, classifier: Classifier, storage: Storage, cooldown_minutes: int, min_confidence: float):
        self._classifier = classifier
        self._storage = storage
        self._cooldown = timedelta(minutes=cooldown_minutes)
        self._min_confidence = min_confidence

    def process(self, news_items: list[NewsItem]) -> list[Signal]:
        """Filtra noticias nuevas, las clasifica y devuelve señales accionables."""
        accepted: list[Signal] = []
        for news in news_items:
            if self._storage.is_news_seen(news.id):
                continue
            self._storage.mark_news_seen(news.id, news.url, news.title)

            try:
                signals = self._classifier.classify(news)
            except Exception:  # noqa: BLE001
                logger.exception("Clasificación falló para noticia: %s", news.title)
                continue

            for signal in signals:
                if signal.confidence < self._min_confidence:
                    continue
                if not self._cooldown_elapsed(signal.ticker):
                    logger.info("Señal para %s en cooldown, descartada", signal.ticker)
                    continue
                accepted.append(signal)
        return accepted

    def _cooldown_elapsed(self, ticker: str) -> bool:
        last = self._storage.last_trade_time(ticker)
        if last is None:
            return True
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - last >= self._cooldown

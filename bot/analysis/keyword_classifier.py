"""Clasificador de noticias basado en reglas: sin dependencias externas de red,
rápido y 100% auditable. Es el motor por defecto; ver claude_classifier.py para
una alternativa basada en LLM opcional.
"""
from __future__ import annotations

import re

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from bot.analysis.tickers import CATEGORY_KEYWORDS, COMPANY_EVENT_KEYWORDS, COMPANY_TICKERS, MACRO_TICKERS
from bot.models import NewsItem, Signal

_analyzer = SentimentIntensityAnalyzer()

_TICKER_TAG_RE = re.compile(r"\(?\b(?:NASDAQ|NYSE):\s*([A-Z]{1,5})\)?")
_DOLLAR_TICKER_RE = re.compile(r"\$([A-Z]{1,5})\b")
_PHRASE_CACHE: dict[str, re.Pattern] = {}


def _contains_phrase(text_lower: str, phrase: str) -> bool:
    """Coincidencia de frase completa con límites de palabra (evita falsos positivos
    como "war" dentro de "award")."""
    pattern = _PHRASE_CACHE.get(phrase)
    if pattern is None:
        pattern = re.compile(r"\b" + re.escape(phrase) + r"\b")
        _PHRASE_CACHE[phrase] = pattern
    return pattern.search(text_lower) is not None


class KeywordClassifier:
    """Genera Signal(s) a partir de un NewsItem usando coincidencia de palabras clave."""

    def classify(self, news: NewsItem) -> list[Signal]:
        text = news.text
        text_lower = text.lower()
        sentiment = _analyzer.polarity_scores(text)["compound"]  # -1..1

        signals: list[Signal] = []
        signals.extend(self._macro_signals(news, text_lower, sentiment))
        signals.extend(self._company_signals(news, text, text_lower, sentiment))
        return signals

    def _macro_signals(self, news: NewsItem, text_lower: str, sentiment: float) -> list[Signal]:
        signals = []
        for category, keywords in CATEGORY_KEYWORDS.items():
            hits = [kw for kw in keywords if _contains_phrase(text_lower, kw)]
            if not hits:
                continue
            relevance = min(1.0, 0.5 + 0.15 * len(hits))
            for ticker, direction in MACRO_TICKERS.get(category, []):
                confidence = relevance * (0.5 + 0.5 * min(1.0, abs(sentiment)))
                signals.append(
                    Signal(
                        news=news,
                        ticker=ticker,
                        direction=direction,
                        confidence=round(min(confidence, 0.95), 3),
                        category=category,
                        reason=f"Categoría macro '{category}' detectada por: {', '.join(hits)}",
                    )
                )
        return signals

    def _company_signals(
        self, news: NewsItem, text: str, text_lower: str, sentiment: float
    ) -> list[Signal]:
        signals = []
        tickers_found: set[str] = set()

        for match in _TICKER_TAG_RE.finditer(text):
            tickers_found.add(match.group(1))
        for match in _DOLLAR_TICKER_RE.finditer(text):
            tickers_found.add(match.group(1))
        for name, ticker in COMPANY_TICKERS.items():
            if _contains_phrase(text_lower, name):
                tickers_found.add(ticker)

        if not tickers_found:
            return signals

        event_direction = None
        event_hit = None
        for phrase, direction in COMPANY_EVENT_KEYWORDS.items():
            if _contains_phrase(text_lower, phrase):
                event_direction = direction
                event_hit = phrase
                break

        if event_direction is None:
            # Sin evento explícito: usar sentimiento general si es suficientemente fuerte.
            if sentiment >= 0.4:
                event_direction, event_hit = "buy", "sentimiento positivo fuerte"
            elif sentiment <= -0.4:
                event_direction, event_hit = "sell", "sentimiento negativo fuerte"
            else:
                return signals

        base_confidence = 0.5 + 0.4 * min(1.0, abs(sentiment))
        for ticker in tickers_found:
            signals.append(
                Signal(
                    news=news,
                    ticker=ticker,
                    direction=event_direction,
                    confidence=round(min(base_confidence, 0.95), 3),
                    category="company_event",
                    reason=f"Evento de empresa detectado ({event_hit}) en {ticker}",
                )
            )
        return signals

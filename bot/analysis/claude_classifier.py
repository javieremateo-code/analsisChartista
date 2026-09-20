"""Clasificador de noticias opcional basado en Claude (Anthropic API).

Más preciso que el clasificador por reglas para relevancia/sentimiento/tickers,
a costa de latencia y coste por llamada. Se activa con USE_LLM_CLASSIFIER=true
y ANTHROPIC_API_KEY en el .env. Si la llamada falla, cae automáticamente al
clasificador por reglas.
"""
from __future__ import annotations

import logging

import anthropic

from bot.analysis.keyword_classifier import KeywordClassifier
from bot.models import NewsItem, Signal

logger = logging.getLogger(__name__)

_MODEL = "claude-opus-5"

_TOOL = {
    "name": "extract_trading_signals",
    "description": (
        "Extrae señales de trading accionables de una noticia financiera: si es "
        "relevante para los mercados, qué tickers afecta y en qué dirección."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "is_market_relevant": {
                "type": "boolean",
                "description": "true si la noticia puede mover algún mercado/activo de forma inmediata",
            },
            "category": {
                "type": "string",
                "description": "categoría breve, p.ej. 'war', 'rate_hike', 'earnings', 'geopolitics'",
            },
            "signals": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "ticker": {"type": "string", "description": "símbolo bursátil, p.ej. AAPL"},
                        "direction": {"type": "string", "enum": ["buy", "sell"]},
                        "confidence": {"type": "number", "description": "0.0 a 1.0"},
                        "reason": {"type": "string"},
                    },
                    "required": ["ticker", "direction", "confidence", "reason"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["is_market_relevant", "category", "signals"],
        "additionalProperties": False,
    },
    "strict": True,
}

_SYSTEM = (
    "Eres un analista de mercados financieros. Dada una noticia, decides si es "
    "relevante para el trading a corto plazo (guerras, sanciones, decisiones de "
    "bancos centrales, resultados corporativos, fusiones, quiebras, etc.) y qué "
    "tickers/ETFs se verían afectados y en qué dirección. Sé conservador: si la "
    "noticia es ambigua, ruido, opinión o ya está descontada por el mercado, "
    "devuelve is_market_relevant=false y una lista de señales vacía. Nunca "
    "inventes tickers de empresas que no se mencionan o infieres con baja certeza; "
    "en ese caso usa ETFs sectoriales/macro conocidos (SPY, TLT, USO, etc.)."
)


class ClaudeClassifier:
    def __init__(self, api_key: str):
        self._client = anthropic.Anthropic(api_key=api_key)
        self._fallback = KeywordClassifier()

    def classify(self, news: NewsItem) -> list[Signal]:
        try:
            response = self._client.messages.create(
                model=_MODEL,
                max_tokens=1024,
                system=_SYSTEM,
                tools=[_TOOL],
                tool_choice={"type": "tool", "name": "extract_trading_signals"},
                output_config={"effort": "low"},
                messages=[
                    {
                        "role": "user",
                        "content": f"Titular: {news.title}\n\nResumen: {news.summary}",
                    }
                ],
            )
        except anthropic.APIError as exc:
            logger.warning("Clasificador Claude falló, usando fallback por reglas: %s", exc)
            return self._fallback.classify(news)

        for block in response.content:
            if block.type == "tool_use" and block.name == "extract_trading_signals":
                return self._parse(news, block.input)

        logger.warning("Claude no devolvió tool_use, usando fallback por reglas")
        return self._fallback.classify(news)

    @staticmethod
    def _parse(news: NewsItem, data: dict) -> list[Signal]:
        if not data.get("is_market_relevant"):
            return []
        category = data.get("category", "llm")
        signals: list[Signal] = []
        for raw in data.get("signals", []):
            try:
                signals.append(
                    Signal(
                        news=news,
                        ticker=str(raw["ticker"]).upper(),
                        direction=raw["direction"],
                        confidence=float(raw["confidence"]),
                        category=category,
                        reason=raw.get("reason", ""),
                    )
                )
            except (KeyError, ValueError, TypeError) as exc:
                logger.warning("Señal LLM inválida descartada: %s (%s)", raw, exc)
        return signals

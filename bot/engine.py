"""Orquestador principal: noticias -> señales -> riesgo -> ejecución."""
from __future__ import annotations

import asyncio
import logging

from bot.analysis.claude_classifier import ClaudeClassifier
from bot.analysis.keyword_classifier import KeywordClassifier
from bot.config import Settings
from bot.execution.alpaca_broker import AlpacaBroker
from bot.execution.base import Broker
from bot.models import Signal
from bot.news.base import NewsSource
from bot.news.finnhub_source import FinnhubNewsSource
from bot.news.newsapi_source import NewsApiSource
from bot.news.rss_source import RssNewsSource
from bot.news.twitter_source import TwitterNewsSource
from bot.notify import Notifier
from bot.risk import RiskManager
from bot.signals import SignalEngine
from bot.storage import Storage

logger = logging.getLogger(__name__)


class TradingBot:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.storage = Storage(settings.db_path)
        self.notifier = Notifier(settings.telegram_bot_token, settings.telegram_chat_id)
        self.risk = RiskManager(settings.risk, self.storage)
        self.broker: Broker | None = self._build_broker()
        self.signal_engine = SignalEngine(
            classifier=self._build_classifier(),
            storage=self.storage,
            cooldown_minutes=settings.risk.cooldown_minutes_per_ticker,
            min_confidence=settings.risk.min_confidence,
        )
        self.sources: list[NewsSource] = self._build_sources()

    def _build_classifier(self):
        if self.settings.use_llm_classifier and self.settings.anthropic_api_key:
            logger.info("Usando clasificador Claude (LLM)")
            return ClaudeClassifier(self.settings.anthropic_api_key)
        logger.info("Usando clasificador por reglas (keyword)")
        return KeywordClassifier()

    def _build_broker(self) -> Broker | None:
        if not (self.settings.alpaca_api_key and self.settings.alpaca_secret_key):
            logger.warning(
                "Sin credenciales de Alpaca: el bot funcionará en modo solo-señales (no ejecuta órdenes)."
            )
            return None
        try:
            return AlpacaBroker(
                api_key=self.settings.alpaca_api_key,
                secret_key=self.settings.alpaca_secret_key,
                paper=self.settings.alpaca_paper,
                live_trading_allowed=self.settings.live_trading_allowed,
                stop_loss_pct=self.settings.risk.stop_loss_pct,
                take_profit_pct=self.settings.risk.take_profit_pct,
            )
        except RuntimeError as exc:
            logger.warning(
                "Broker desactivado, el bot sólo generará y registrará señales: %s", exc
            )
            return None

    def _build_sources(self) -> list[NewsSource]:
        sources: list[NewsSource] = []
        if self.settings.rss_feeds:
            sources.append(RssNewsSource(self.settings.rss_feeds))
        if self.settings.newsapi_key:
            sources.append(NewsApiSource(self.settings.newsapi_key))
        if self.settings.finnhub_key:
            sources.append(FinnhubNewsSource(self.settings.finnhub_key))
        if self.settings.twitter_bearer_token:
            try:
                sources.append(
                    TwitterNewsSource(
                        self.settings.twitter_bearer_token, self.settings.twitter_watch_accounts
                    )
                )
            except RuntimeError as exc:
                logger.warning("Fuente de Twitter desactivada: %s", exc)
        if not sources:
            logger.warning("Ninguna fuente de noticias configurada.")
        return sources

    async def run_once(self) -> None:
        news_items = await self._fetch_all_news()
        signals = self.signal_engine.process(news_items)
        for signal in signals:
            await self._handle_signal(signal)

    async def _fetch_all_news(self):
        if not self.sources:
            return []
        results = await asyncio.gather(
            *(source.fetch_latest() for source in self.sources), return_exceptions=True
        )
        items = []
        for source, result in zip(self.sources, results):
            if isinstance(result, Exception):
                logger.warning("Fuente %s falló: %s", source.name, result)
                continue
            items.extend(result)
        return items

    async def _handle_signal(self, signal: Signal) -> None:
        self.notifier.notify(
            f"Señal detectada: {signal.direction.upper()} {signal.ticker} "
            f"(confianza {signal.confidence:.2f}, categoría {signal.category}) — {signal.reason} "
            f"[{signal.news.url}]"
        )

        if self.broker is None:
            return

        if self.settings.trade_only_market_hours and not await asyncio.to_thread(
            self.broker.is_market_open
        ):
            self.notifier.notify(f"Mercado cerrado: señal para {signal.ticker} no ejecutada")
            return

        equity = await asyncio.to_thread(self.broker.get_equity)
        decision = self.risk.evaluate(signal, equity)
        if not decision.allowed:
            self.notifier.notify(f"Señal para {signal.ticker} rechazada por riesgo: {decision.reason}")
            return

        try:
            result = await asyncio.to_thread(
                self.broker.submit_signal_order, signal, decision.notional_usd
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error ejecutando orden para %s", signal.ticker)
            self.notifier.notify(f"ERROR ejecutando orden para {signal.ticker}: {exc}")
            return

        self.storage.record_trade(signal, decision.notional_usd, result.order_id, result.status)
        self.notifier.notify(
            f"ORDEN ENVIADA: {signal.direction.upper()} {signal.ticker} ${decision.notional_usd:.2f} "
            f"(order_id={result.order_id}, status={result.status})"
        )

    async def run_forever(self) -> None:
        logger.info("Bot iniciado. Fuentes activas: %s", [s.name for s in self.sources])
        while True:
            try:
                await self.run_once()
            except Exception:  # noqa: BLE001
                logger.exception("Error en el ciclo principal")
            await asyncio.sleep(self.settings.poll_interval_seconds)

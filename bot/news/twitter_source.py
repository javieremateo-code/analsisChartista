"""Fuente de noticias vía streaming de X/Twitter (requiere API de pago con acceso a streaming).

Usa tweepy.StreamingClient, que es bloqueante, así que corre en un hilo aparte
y empuja los tweets a una cola asyncio consumida por fetch_latest().
"""
from __future__ import annotations

import asyncio
import logging
import threading

from bot.models import NewsItem
from bot.news.base import NewsSource

logger = logging.getLogger(__name__)

try:
    import tweepy
except ImportError:  # pragma: no cover - dependencia opcional
    tweepy = None


class TwitterNewsSource(NewsSource):
    name = "twitter"

    def __init__(self, bearer_token: str, watch_accounts: list[str] | None = None):
        if tweepy is None:
            raise RuntimeError(
                "tweepy no está instalado. Instala con `pip install tweepy` para usar esta fuente."
            )
        self.bearer_token = bearer_token
        self.watch_accounts = watch_accounts or []
        self._queue: asyncio.Queue[NewsItem] = asyncio.Queue()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stream: "_Stream | None" = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Arranca el stream en background. Llamar una vez, antes del primer fetch_latest()."""
        self._loop = asyncio.get_event_loop()
        self._stream = _Stream(self.bearer_token, self._queue, self._loop)
        rules = [tweepy.StreamRule(f"from:{acct} -is:retweet") for acct in self.watch_accounts]
        if rules:
            try:
                self._stream.add_rules(rules)
            except Exception as exc:  # noqa: BLE001
                logger.warning("No se pudieron fijar reglas de Twitter: %s", exc)
        self._thread = threading.Thread(
            target=self._stream.filter,
            kwargs={"tweet_fields": ["created_at"], "threaded": False},
            daemon=True,
        )
        self._thread.start()

    async def fetch_latest(self) -> list[NewsItem]:
        if self._stream is None:
            self.start()
        items: list[NewsItem] = []
        while not self._queue.empty():
            items.append(self._queue.get_nowait())
        return items


class _Stream:
    """Envuelve tweepy.StreamingClient para no acoplar el import a nivel de módulo."""

    def __init__(self, bearer_token: str, queue: "asyncio.Queue[NewsItem]", loop: asyncio.AbstractEventLoop):
        self._client = tweepy.StreamingClient(bearer_token)
        self._queue = queue
        self._loop = loop
        client = self._client

        def on_tweet(tweet):  # noqa: ANN001
            item = NewsItem(
                source="twitter",
                title=tweet.text[:120],
                summary=tweet.text,
                url=f"https://twitter.com/i/web/status/{tweet.id}",
            )
            loop.call_soon_threadsafe(queue.put_nowait, item)

        client.on_tweet = on_tweet

    def add_rules(self, rules):  # noqa: ANN001
        self._client.add_rules(rules)

    def filter(self, **kwargs):  # noqa: ANN003
        self._client.filter(**kwargs)

import tempfile
from pathlib import Path

import pytest

from bot.models import NewsItem, Signal
from bot.signals import SignalEngine
from bot.storage import Storage


@pytest.fixture
def storage():
    with tempfile.TemporaryDirectory() as tmpdir:
        s = Storage(str(Path(tmpdir) / "test.sqlite3"))
        yield s
        s.close()


class FakeClassifier:
    def __init__(self, signals_by_url):
        self._signals_by_url = signals_by_url

    def classify(self, news: NewsItem):
        return self._signals_by_url.get(news.url, [])


def make_news(url: str) -> NewsItem:
    return NewsItem(source="test", title="t", summary="s", url=url)


def test_duplicate_news_is_only_processed_once(storage):
    news = make_news("https://example.com/1")
    signal = Signal(news=news, ticker="AAPL", direction="buy", confidence=0.9, category="c", reason="r")
    classifier = FakeClassifier({news.url: [signal]})
    engine = SignalEngine(classifier, storage, cooldown_minutes=0, min_confidence=0.5)

    first = engine.process([news])
    second = engine.process([news])

    assert len(first) == 1
    assert second == []


def test_low_confidence_signal_filtered_out(storage):
    news = make_news("https://example.com/2")
    signal = Signal(news=news, ticker="AAPL", direction="buy", confidence=0.3, category="c", reason="r")
    classifier = FakeClassifier({news.url: [signal]})
    engine = SignalEngine(classifier, storage, cooldown_minutes=0, min_confidence=0.5)

    assert engine.process([news]) == []


def test_cooldown_blocks_repeated_ticker_signal(storage):
    storage_signal = Signal(
        news=make_news("https://example.com/old"),
        ticker="AAPL",
        direction="buy",
        confidence=0.9,
        category="c",
        reason="r",
    )
    storage.record_trade(storage_signal, 100.0, "order-1", "filled")

    news = make_news("https://example.com/3")
    signal = Signal(news=news, ticker="AAPL", direction="buy", confidence=0.9, category="c", reason="r")
    classifier = FakeClassifier({news.url: [signal]})
    engine = SignalEngine(classifier, storage, cooldown_minutes=240, min_confidence=0.5)

    assert engine.process([news]) == []

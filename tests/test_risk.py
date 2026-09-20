import tempfile
from pathlib import Path

import pytest

from bot.config import RiskConfig
from bot.models import NewsItem, Signal
from bot.risk import RiskManager
from bot.storage import Storage


@pytest.fixture
def storage():
    with tempfile.TemporaryDirectory() as tmpdir:
        s = Storage(str(Path(tmpdir) / "test.sqlite3"))
        yield s
        s.close()


def make_signal(ticker="AAPL", confidence=0.9, direction="buy"):
    news = NewsItem(source="test", title="t", summary="s", url="https://example.com/x")
    return Signal(news=news, ticker=ticker, direction=direction, confidence=confidence, category="test", reason="r")


def test_low_confidence_signal_is_rejected(storage):
    risk = RiskManager(RiskConfig(min_confidence=0.7), storage)
    decision = risk.evaluate(make_signal(confidence=0.5), account_equity=10000)
    assert not decision.allowed


def test_valid_signal_is_allowed_and_sized(storage):
    config = RiskConfig(max_position_usd=1000, max_position_pct_equity=0.5, min_confidence=0.5)
    risk = RiskManager(config, storage)
    decision = risk.evaluate(make_signal(confidence=0.8), account_equity=10000)
    assert decision.allowed
    # min(1000, 10000*0.5) * 0.8 confidence = 800
    assert decision.notional_usd == 800.0


def test_kill_switch_blocks_all_trades(storage):
    risk = RiskManager(RiskConfig(min_confidence=0.0), storage)
    risk.trip_kill_switch("test")
    decision = risk.evaluate(make_signal(confidence=1.0), account_equity=10000)
    assert not decision.allowed


def test_max_trades_per_day_is_enforced(storage):
    signal = make_signal()
    for _ in range(3):
        storage.record_trade(signal, 100.0, "order-id", "filled")

    risk = RiskManager(RiskConfig(max_trades_per_day=3, min_confidence=0.0), storage)
    decision = risk.evaluate(make_signal(), account_equity=10000)
    assert not decision.allowed
    assert "operaciones diarias" in decision.reason

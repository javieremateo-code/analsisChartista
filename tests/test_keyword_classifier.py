from bot.analysis.keyword_classifier import KeywordClassifier
from bot.models import NewsItem


def make_news(title: str, summary: str = "") -> NewsItem:
    return NewsItem(source="test", title=title, summary=summary, url="https://example.com/1")


def test_war_headline_generates_defense_and_oil_signals():
    news = make_news("Country X invades neighboring Country Y, military strike reported")
    signals = KeywordClassifier().classify(news)

    tickers = {s.ticker for s in signals}
    assert "LMT" in tickers
    assert "USO" in tickers
    assert all(s.category == "war" for s in signals if s.ticker in ("LMT", "USO"))


def test_company_earnings_beat_generates_buy_signal():
    news = make_news("Apple beats estimates in latest earnings report, stock surges")
    signals = KeywordClassifier().classify(news)

    aapl_signals = [s for s in signals if s.ticker == "AAPL"]
    assert aapl_signals
    assert aapl_signals[0].direction == "buy"


def test_company_bankruptcy_generates_sell_signal():
    news = make_news("Tesla files for bankruptcy amid mounting debt")
    signals = KeywordClassifier().classify(news)

    tsla_signals = [s for s in signals if s.ticker == "TSLA"]
    assert tsla_signals
    assert tsla_signals[0].direction == "sell"


def test_irrelevant_news_generates_no_signals():
    news = make_news("Local bakery wins regional pastry award")
    signals = KeywordClassifier().classify(news)
    assert signals == []


def test_dollar_ticker_tag_is_recognized():
    news = make_news("$NVDA soars after chip demand outlook raised, beats estimates")
    signals = KeywordClassifier().classify(news)
    tickers = {s.ticker for s in signals}
    assert "NVDA" in tickers

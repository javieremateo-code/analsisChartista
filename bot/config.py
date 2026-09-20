"""Carga de configuración desde variables de entorno (.env)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _float(name: str, default: float) -> float:
    val = os.getenv(name)
    return float(val) if val else default


def _int(name: str, default: int) -> int:
    val = os.getenv(name)
    return int(val) if val else default


def _list(name: str, default: list[str]) -> list[str]:
    val = os.getenv(name)
    if not val:
        return default
    return [item.strip() for item in val.split(",") if item.strip()]


DEFAULT_RSS_FEEDS = [
    "https://feeds.reuters.com/reuters/businessNews",
    "https://feeds.reuters.com/reuters/worldNews",
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "https://feeds.bbci.co.uk/news/business/rss.xml",
]

# Frase de confirmación explícita exigida para operar con dinero real.
LIVE_TRADING_CONFIRM_PHRASE = "YES_I_UNDERSTAND_THE_RISK"


@dataclass
class RiskConfig:
    max_position_usd: float = _float("MAX_POSITION_USD", 500.0)
    max_position_pct_equity: float = _float("MAX_POSITION_PCT_EQUITY", 0.05)
    max_daily_loss_usd: float = _float("MAX_DAILY_LOSS_USD", 300.0)
    max_open_positions: int = _int("MAX_OPEN_POSITIONS", 5)
    max_trades_per_day: int = _int("MAX_TRADES_PER_DAY", 10)
    cooldown_minutes_per_ticker: int = _int("COOLDOWN_MINUTES_PER_TICKER", 240)
    min_confidence: float = _float("MIN_CONFIDENCE", 0.65)
    stop_loss_pct: float = _float("STOP_LOSS_PCT", 0.03)
    take_profit_pct: float = _float("TAKE_PROFIT_PCT", 0.06)


@dataclass
class Settings:
    # --- Broker (Alpaca) ---
    alpaca_api_key: str = field(default_factory=lambda: os.getenv("ALPACA_API_KEY", ""))
    alpaca_secret_key: str = field(default_factory=lambda: os.getenv("ALPACA_SECRET_KEY", ""))
    alpaca_paper: bool = field(default_factory=lambda: _bool("ALPACA_PAPER", True))
    live_trading_confirm: str = field(default_factory=lambda: os.getenv("LIVE_TRADING_CONFIRM", ""))

    # --- Fuentes de noticias ---
    newsapi_key: str = field(default_factory=lambda: os.getenv("NEWSAPI_KEY", ""))
    finnhub_key: str = field(default_factory=lambda: os.getenv("FINNHUB_KEY", ""))
    twitter_bearer_token: str = field(default_factory=lambda: os.getenv("TWITTER_BEARER_TOKEN", ""))
    twitter_watch_accounts: list[str] = field(
        default_factory=lambda: _list("TWITTER_WATCH_ACCOUNTS", [])
    )
    rss_feeds: list[str] = field(default_factory=lambda: _list("RSS_FEEDS", DEFAULT_RSS_FEEDS))

    # --- Clasificador LLM opcional (Claude) ---
    use_llm_classifier: bool = field(default_factory=lambda: _bool("USE_LLM_CLASSIFIER", False))
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))

    # --- Notificaciones ---
    telegram_bot_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))

    # --- Motor ---
    poll_interval_seconds: int = field(default_factory=lambda: _int("POLL_INTERVAL_SECONDS", 30))
    db_path: str = field(default_factory=lambda: os.getenv("DB_PATH", "bot_state.sqlite3"))
    trade_only_market_hours: bool = field(
        default_factory=lambda: _bool("TRADE_ONLY_MARKET_HOURS", True)
    )

    risk: RiskConfig = field(default_factory=RiskConfig)

    @property
    def live_trading_allowed(self) -> bool:
        """Sólo permite órdenes reales si paper=False Y se confirmó explícitamente."""
        if self.alpaca_paper:
            return False
        return self.live_trading_confirm == LIVE_TRADING_CONFIRM_PHRASE

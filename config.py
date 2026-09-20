"""Configuración central del sistema. No hardcodear claves de API: van por variables de entorno."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class RiskConfig:
    capital_total: float = 1000.0          # EUR, capital asignado al bot
    max_daily_loss_pct: float = 0.10       # circuit breaker diario: -10% del capital del día
    max_drawdown_pct: float = 0.50         # kill switch total: -50% del capital inicial (alto, revisar)
    risk_per_trade_pct: float = 0.01       # arriesgar 1% del capital en cada operación (ajustable)


@dataclass(frozen=True)
class MarketConfig:
    exchange: str = "binance"
    symbol: str = "BTC/USDT"
    timeframe: str = "15m"                 # intradía


@dataclass(frozen=True)
class ExecutionConfig:
    # "paper" usa Binance Spot Testnet. "live" usa la cuenta real: requiere
    # cumplir el criterio de graduación descrito en README.md antes de activarlo.
    mode: str = os.getenv("TRADING_MODE", "paper")
    binance_api_key: str = os.getenv("BINANCE_API_KEY", "")
    binance_api_secret: str = os.getenv("BINANCE_API_SECRET", "")


RISK = RiskConfig()
MARKET = MarketConfig()
EXECUTION = ExecutionConfig()

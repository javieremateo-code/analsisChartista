"""Ejecutor de órdenes vía Binance, usando ccxt.

Modo controlado por config.EXECUTION.mode:
  - "paper" (default): usa Binance Spot Testnet (testnet.binance.vision).
    Requiere generar API keys ahí — son independientes de la cuenta real y
    no arriesgan dinero.
  - "live": usa la cuenta real. Solo debería activarse a mano, después de
    cumplir el criterio de graduación descrito en README.md. Este módulo no
    lo activa por sí mismo: siempre lee el modo de config.EXECUTION.
"""
import ccxt

from config import EXECUTION


class BinanceExecutor:
    def __init__(self, mode: str | None = None):
        self.mode = mode or EXECUTION.mode
        if self.mode not in ("paper", "live"):
            raise ValueError(f"Modo de ejecución desconocido: {self.mode}")
        if not EXECUTION.binance_api_key or not EXECUTION.binance_api_secret:
            raise RuntimeError(
                "Faltan BINANCE_API_KEY / BINANCE_API_SECRET en el entorno. "
                "En modo paper, generalas en https://testnet.binance.vision/"
            )
        self.exchange = ccxt.binance({
            "apiKey": EXECUTION.binance_api_key,
            "secret": EXECUTION.binance_api_secret,
            "enableRateLimit": True,
        })
        if self.mode == "paper":
            self.exchange.set_sandbox_mode(True)

    def get_balance(self, asset: str = "USDT") -> float:
        balance = self.exchange.fetch_balance()
        return float(balance.get(asset, {}).get("free", 0.0))

    def market_order(self, symbol: str, side: str, quantity: float) -> dict:
        return self.exchange.create_order(symbol=symbol, type="market", side=side, amount=quantity)

    def close(self) -> None:
        self.exchange.close()

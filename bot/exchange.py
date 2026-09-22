"""Ejecución de órdenes. SOLO dos modos: simulado (precios reales, sin claves) y testnet de Binance (dinero de prueba).

No existe modo con dinero real: se añadiría solo tras el periodo en papel y por decisión explícita del usuario.
Las claves del testnet se leen únicamente de variables de entorno (.env local) y nunca se imprimen.
"""
import os
from dataclasses import dataclass

TAKER_FEE = 0.001   # comisión spot taker de Binance
EXTRA_SLIP = 0.0005  # colchón de slippage del modo simulado (equivale al 0.15%/lado usado en los backtests)


@dataclass
class Fill:
    coin: str
    side: str
    qty: float
    price: float
    fee_usdt: float
    usdt: float        # compra: USDT gastados (incluye comisión); venta: USDT recibidos (neto de comisión)
    mode: str          # 'sim' | 'testnet' | 'sim_fallback' | 'sim_stop'
    ref: float         # precio de referencia (cierre de la vela) para medir el slippage


class SimExchange:
    mode = "sim"

    def __init__(self, feed, fee=TAKER_FEE, slip=EXTRA_SLIP):
        self.feed, self.fee, self.slip = feed, fee, slip

    def _q(self, coin):
        q = self.feed.quotes().get(coin)
        if not q:
            raise RuntimeError(f"sin cotización para {coin}")
        return q

    def buy(self, coin, usdt, ref):
        px = self._q(coin)["ask"] * (1 + self.slip)
        qty = usdt / (px * (1 + self.fee))
        return Fill(coin, "buy", qty, px, qty * px * self.fee, usdt, self.mode, ref)

    def sell(self, coin, qty, ref):
        px = self._q(coin)["bid"] * (1 - self.slip)
        fee = qty * px * self.fee
        return Fill(coin, "sell", qty, px, fee, qty * px - fee, self.mode, ref)

    def sell_at(self, coin, qty, price, ref):
        """Salida a un precio dado (stop de catástrofe tocado): se contabiliza al precio del stop con slippage."""
        px = price * (1 - 0.003)
        fee = qty * px * self.fee
        return Fill(coin, "sell", qty, px, fee, qty * px - fee, "sim_stop", ref)


class TestnetExchange(SimExchange):
    """Órdenes de mercado reales en el testnet de Binance (https://testnet.binance.vision). Si una moneda no está listada
    en el testnet (solo tiene unas pocas) o falla la orden, se cae a una ejecución simulada marcada como 'sim_fallback'."""
    mode = "testnet"

    def __init__(self, feed, key=None, secret=None, **kw):
        super().__init__(feed, **kw)
        key = key or os.getenv("BINANCE_TESTNET_KEY", "")
        secret = secret or os.getenv("BINANCE_TESTNET_SECRET", "")
        if not key or not secret:
            raise RuntimeError("Faltan BINANCE_TESTNET_KEY / BINANCE_TESTNET_SECRET en el entorno (.env). Créalas en https://testnet.binance.vision/")
        import ccxt  # import diferido: el modo simulado no lo necesita
        self.ccxt = ccxt.binance({"apiKey": key, "secret": secret, "enableRateLimit": True})
        self.ccxt.set_sandbox_mode(True)
        self.markets = self.ccxt.load_markets()

    def _ok(self, coin, usdt=None, qty=None):
        m = self.markets.get(f"{coin}/USDT")
        if not m or not m.get("active", True):
            return None
        return m

    def buy(self, coin, usdt, ref):
        m = self._ok(coin)
        if m is None:
            f = super().buy(coin, usdt, ref)
            f.mode = "sim_fallback"
            return f
        try:
            px = self._q(coin)["ask"]
            qty = float(self.ccxt.amount_to_precision(f"{coin}/USDT", usdt / (px * (1 + self.fee))))
            o = self.ccxt.create_order(f"{coin}/USDT", "market", "buy", qty)
            price = float(o.get("average") or o.get("price") or px)
            fee = sum(float(x.get("cost", 0) or 0) for x in (o.get("fees") or []) if x.get("currency") == "USDT") or qty * price * self.fee
            return Fill(coin, "buy", float(o.get("filled") or qty), price, fee, float(o.get("cost") or qty * price) + fee, "testnet", ref)
        except Exception:
            f = super().buy(coin, usdt, ref)
            f.mode = "sim_fallback"
            return f

    def sell(self, coin, qty, ref):
        m = self._ok(coin)
        if m is None:
            f = super().sell(coin, qty, ref)
            f.mode = "sim_fallback"
            return f
        try:
            q = float(self.ccxt.amount_to_precision(f"{coin}/USDT", qty))
            o = self.ccxt.create_order(f"{coin}/USDT", "market", "sell", q)
            price = float(o.get("average") or o.get("price") or self._q(coin)["bid"])
            fee = sum(float(x.get("cost", 0) or 0) for x in (o.get("fees") or []) if x.get("currency") == "USDT") or q * price * self.fee
            return Fill(coin, "sell", q, price, fee, q * price - fee, "testnet", ref)
        except Exception:
            f = super().sell(coin, qty, ref)
            f.mode = "sim_fallback"
            return f

"""Broker de ejecución vía Alpaca (acciones/ETFs US).

Envía órdenes de mercado con stop-loss y take-profit adjuntos (bracket order),
para que cada posición tenga su riesgo acotado desde el momento en que se abre.

Por defecto opera contra el endpoint de "paper trading" (dinero simulado) de
Alpaca. Para operar con dinero real hace falta ALPACA_PAPER=false Y
LIVE_TRADING_CONFIRM=YES_I_UNDERSTAND_THE_RISK en el .env; sin ambas cosas,
este broker se niega a arrancar en modo real.
"""
from __future__ import annotations

import logging
import math

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestTradeRequest
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest, StopLossRequest, TakeProfitRequest

from bot.execution.base import Broker, OrderResult
from bot.models import Signal

logger = logging.getLogger(__name__)


class AlpacaBroker(Broker):
    def __init__(
        self,
        api_key: str,
        secret_key: str,
        paper: bool,
        live_trading_allowed: bool,
        stop_loss_pct: float,
        take_profit_pct: float,
    ):
        if not paper and not live_trading_allowed:
            raise RuntimeError(
                "Configuración insegura: ALPACA_PAPER=false pero LIVE_TRADING_CONFIRM no "
                "coincide con la frase de confirmación requerida. Revisa el .env.example."
            )
        self._trading = TradingClient(api_key, secret_key, paper=paper)
        self._data = StockHistoricalDataClient(api_key, secret_key)
        self._paper = paper
        self._stop_loss_pct = stop_loss_pct
        self._take_profit_pct = take_profit_pct

    def get_equity(self) -> float:
        account = self._trading.get_account()
        return float(account.equity)

    def is_market_open(self) -> bool:
        clock = self._trading.get_clock()
        return bool(clock.is_open)

    def submit_signal_order(self, signal: Signal, notional_usd: float) -> OrderResult:
        last_price = self._last_price(signal.ticker)
        qty = math.floor(notional_usd / last_price) if last_price > 0 else 0
        if qty < 1:
            raise ValueError(
                f"Tamaño calculado ({notional_usd} USD a {last_price} USD/acción) da 0 acciones"
            )

        side = OrderSide.BUY if signal.direction == "buy" else OrderSide.SELL
        if signal.direction == "buy":
            stop_price = round(last_price * (1 - self._stop_loss_pct), 2)
            take_price = round(last_price * (1 + self._take_profit_pct), 2)
        else:
            stop_price = round(last_price * (1 + self._stop_loss_pct), 2)
            take_price = round(last_price * (1 - self._take_profit_pct), 2)

        order_request = MarketOrderRequest(
            symbol=signal.ticker,
            qty=qty,
            side=side,
            time_in_force=TimeInForce.DAY,
            order_class=OrderClass.BRACKET,
            take_profit=TakeProfitRequest(limit_price=take_price),
            stop_loss=StopLossRequest(stop_price=stop_price),
        )
        order = self._trading.submit_order(order_request)
        logger.info(
            "Orden enviada (%s): %s %s x%d @mercado, TP=%.2f SL=%.2f",
            "PAPER" if self._paper else "LIVE",
            side.value,
            signal.ticker,
            qty,
            take_price,
            stop_price,
        )
        return OrderResult(order_id=str(order.id), status=str(order.status))

    def _last_price(self, ticker: str) -> float:
        request = StockLatestTradeRequest(symbol_or_symbols=ticker)
        trades = self._data.get_stock_latest_trade(request)
        return float(trades[ticker].price)

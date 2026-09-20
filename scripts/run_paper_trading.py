"""Runner de paper trading: pensado para ejecutarse por cron una vez por vela
cerrada (ej. cada 15 min si MARKET.timeframe = "15m"), no como proceso
permanente. Cada invocación:
  1. Carga el estado (equity, drawdown, posición abierta) del disco.
  2. Descarga las últimas velas y calcula la señal de la estrategia.
  3. Si hay posición abierta, chequea si tocó stop/target y la cierra.
  4. Si no hay posición y el risk manager lo permite, evalúa nueva entrada.
  5. Guarda el estado actualizado.

Uso (cron cada 15 min):
    */15 * * * * cd /ruta/al/proyecto && .venv/bin/python -m scripts.run_paper_trading
"""
import logging
from datetime import datetime, timezone

from config import EXECUTION, MARKET, RISK
from data.fetch_binance import fetch_recent
from execution.binance_executor import BinanceExecutor
from execution.state_store import load_position, load_risk_manager, save_position, save_risk_manager
from risk.risk_manager import RiskManager
from strategy.donchian_breakout import StrategyParams, compute_signals

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("paper_trading")


def main() -> None:
    symbol_ccxt = MARKET.symbol            # ej. "BTC/USDT" (formato ccxt)
    symbol_rest = MARKET.symbol.replace("/", "")  # ej. "BTCUSDT" (formato REST klines)

    default_rm = RiskManager(
        initial_capital=RISK.capital_total,
        max_daily_loss_pct=RISK.max_daily_loss_pct,
        max_drawdown_pct=RISK.max_drawdown_pct,
        risk_per_trade_pct=RISK.risk_per_trade_pct,
    )
    risk_manager = load_risk_manager(default_rm)
    position = load_position()

    today = datetime.now(timezone.utc).date()
    risk_manager.reset_daily_halt_if_new_day(today)

    df = fetch_recent(symbol_rest, MARKET.timeframe, limit=max(300, StrategyParams().trend_ema_period + 50))
    signals = compute_signals(df, StrategyParams())
    last = signals.iloc[-1]
    log.info(f"Última vela cerrada: {last['open_time']} close={last['close']:.2f}")

    executor = BinanceExecutor(mode=EXECUTION.mode)

    if position is not None:
        exit_price, reason = None, None
        if position["side"] == "long":
            if last["low"] <= position["stop"]:
                exit_price, reason = position["stop"], "stop"
            elif last["high"] >= position["target"]:
                exit_price, reason = position["target"], "target"
        else:
            if last["high"] >= position["stop"]:
                exit_price, reason = position["stop"], "stop"
            elif last["low"] <= position["target"]:
                exit_price, reason = position["target"], "target"

        if exit_price is not None:
            close_side = "sell" if position["side"] == "long" else "buy"
            order = executor.market_order(symbol_ccxt, close_side, position["quantity"])
            fill_price = float(order.get("average") or order.get("price") or exit_price)
            gross = (
                (fill_price - position["entry_price"]) * position["quantity"]
                if position["side"] == "long"
                else (position["entry_price"] - fill_price) * position["quantity"]
            )
            risk_manager.record_trade_result(gross, today)
            log.info(f"Posición cerrada por {reason} a {fill_price:.2f} | pnl={gross:.2f}")
            position = None
        else:
            log.info("Posición abierta, sin toque de stop/target todavía.")

    elif risk_manager.can_trade():
        if last["long_entry"] or last["short_entry"]:
            side = "long" if last["long_entry"] else "short"
            stop = last["long_stop"] if side == "long" else last["short_stop"]
            target = last["long_target"] if side == "long" else last["short_target"]
            quantity = risk_manager.position_size(last["close"], stop)
            if quantity > 0:
                order_side = "buy" if side == "long" else "sell"
                order = executor.market_order(symbol_ccxt, order_side, quantity)
                fill_price = float(order.get("average") or order.get("price") or last["close"])
                position = {
                    "side": side, "entry_price": fill_price, "quantity": quantity,
                    "stop": stop, "target": target, "entry_time": str(last["open_time"]),
                }
                log.info(f"Nueva entrada {side} a {fill_price:.2f} qty={quantity:.6f}")
        else:
            log.info("Sin señal de entrada en la última vela.")
    else:
        log.warning(f"Trading detenido por risk manager: {risk_manager.halt_reason}")

    save_risk_manager(risk_manager)
    save_position(position)
    executor.close()


if __name__ == "__main__":
    main()

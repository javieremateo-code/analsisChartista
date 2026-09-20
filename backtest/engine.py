"""Motor de backtest bar-by-bar con costos realistas y validación walk-forward.

Decisiones de diseño relevantes para la validez del resultado:
  - Los costos (comisión + slippage) se aplican en CADA entrada y salida, no
    como ajuste posterior — si la estrategia no sobrevive esto, no sirve.
  - Solo una posición abierta a la vez (sin pirámides), para que el sizing por
    riesgo del RiskManager sea directamente interpretable.
  - El walk-forward evalúa exclusivamente en ventanas "test" nunca usadas para
    ajustar nada; no hay optimización de parámetros en este motor todavía —
    eso es a propósito, para no mezclar "medir" con "ajustar" en el mismo paso.
"""
from dataclasses import dataclass

import pandas as pd

from risk.risk_manager import RiskManager
from strategy.donchian_breakout import StrategyParams, compute_signals

TAKER_FEE_PCT = 0.001      # comisión taker spot de Binance (~0.1%)
SLIPPAGE_PCT = 0.0005      # estimación conservadora de slippage intradía


@dataclass
class Trade:
    side: str
    entry_time: pd.Timestamp
    entry_price: float
    exit_time: pd.Timestamp
    exit_price: float
    quantity: float
    pnl: float


def _apply_costs(price: float, side: str, is_entry: bool) -> float:
    """Ajusta el precio de ejecución por slippage y aplica la comisión aparte."""
    direction = 1 if (side == "long") == is_entry else -1
    return price * (1 + direction * SLIPPAGE_PCT)


def run_backtest(
    df: pd.DataFrame,
    strategy_params: StrategyParams,
    risk_manager: RiskManager,
) -> tuple[pd.DataFrame, pd.Series]:
    signals = compute_signals(df, strategy_params)
    trades: list[Trade] = []
    equity_points = [(signals.iloc[0]["open_time"], risk_manager.equity)]

    position = None  # dict con side, entry_price, quantity, stop, target, entry_time

    for _, row in signals.iterrows():
        as_of = row["open_time"].date()
        risk_manager.reset_daily_halt_if_new_day(as_of)

        if position is not None:
            exit_price = None
            if position["side"] == "long":
                if row["low"] <= position["stop"]:
                    exit_price = position["stop"]
                elif row["high"] >= position["target"]:
                    exit_price = position["target"]
            else:
                if row["high"] >= position["stop"]:
                    exit_price = position["stop"]
                elif row["low"] <= position["target"]:
                    exit_price = position["target"]

            if exit_price is not None:
                fill_price = _apply_costs(exit_price, position["side"], is_entry=False)
                gross = (
                    (fill_price - position["entry_price"]) * position["quantity"]
                    if position["side"] == "long"
                    else (position["entry_price"] - fill_price) * position["quantity"]
                )
                fee = fill_price * position["quantity"] * TAKER_FEE_PCT
                pnl = gross - fee
                trades.append(Trade(
                    side=position["side"], entry_time=position["entry_time"],
                    entry_price=position["entry_price"], exit_time=row["open_time"],
                    exit_price=fill_price, quantity=position["quantity"], pnl=pnl,
                ))
                risk_manager.record_trade_result(pnl, as_of)
                equity_points.append((row["open_time"], risk_manager.equity))
                position = None

        if position is None and risk_manager.can_trade():
            if row.get("long_entry"):
                entry_price = _apply_costs(row["close"], "long", is_entry=True)
                qty = risk_manager.position_size(entry_price, row["long_stop"])
                entry_fee = entry_price * qty * TAKER_FEE_PCT
                risk_manager.equity -= entry_fee
                if qty > 0:
                    position = dict(side="long", entry_price=entry_price, quantity=qty,
                                     stop=row["long_stop"], target=row["long_target"],
                                     entry_time=row["open_time"])
            elif row.get("short_entry"):
                entry_price = _apply_costs(row["close"], "short", is_entry=True)
                qty = risk_manager.position_size(entry_price, row["short_stop"])
                entry_fee = entry_price * qty * TAKER_FEE_PCT
                risk_manager.equity -= entry_fee
                if qty > 0:
                    position = dict(side="short", entry_price=entry_price, quantity=qty,
                                     stop=row["short_stop"], target=row["short_target"],
                                     entry_time=row["open_time"])

    trades_df = pd.DataFrame([t.__dict__ for t in trades])
    equity_curve = pd.Series(
        [e for _, e in equity_points], index=[t for t, _ in equity_points], name="equity"
    )
    return trades_df, equity_curve


def walk_forward_windows(df: pd.DataFrame, train_days: int, test_days: int):
    """Genera ventanas rolantes (train, test) sin overlap entre test consecutivos."""
    start = df["open_time"].min()
    end = df["open_time"].max()
    train_span = pd.Timedelta(days=train_days)
    test_span = pd.Timedelta(days=test_days)

    cursor = start
    while cursor + train_span + test_span <= end:
        train_start, train_end = cursor, cursor + train_span
        test_start, test_end = train_end, train_end + test_span
        train_df = df[(df["open_time"] >= train_start) & (df["open_time"] < train_end)]
        test_df = df[(df["open_time"] >= test_start) & (df["open_time"] < test_end)]
        yield train_df, test_df
        cursor += test_span

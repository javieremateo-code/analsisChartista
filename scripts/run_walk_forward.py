"""Corre la validación walk-forward completa sobre el baseline y reporta métricas
SOLO sobre datos out-of-sample (nunca vistos durante el "ajuste" de cada ventana).

Uso:
    python -m scripts.run_walk_forward --days 365 --train-days 60 --test-days 14
"""
import argparse

import pandas as pd

from backtest.engine import run_backtest, walk_forward_windows
from backtest.metrics import summarize
from config import MARKET, RISK
from data.fetch_binance import load_or_fetch
from risk.risk_manager import RiskManager
from strategy.donchian_breakout import StrategyParams

PERIODS_PER_YEAR = {"15m": 365 * 24 * 4, "1h": 365 * 24, "1d": 365}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--train-days", type=int, default=60)
    parser.add_argument("--test-days", type=int, default=14)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    symbol = MARKET.symbol.replace("/", "")
    df = load_or_fetch(symbol, MARKET.timeframe, args.days, refresh=args.refresh)
    if df.empty:
        raise SystemExit("No se pudo descargar data de Binance (revisar conectividad).")

    params = StrategyParams()
    risk_manager = RiskManager(
        initial_capital=RISK.capital_total,
        max_daily_loss_pct=RISK.max_daily_loss_pct,
        max_drawdown_pct=RISK.max_drawdown_pct,
        risk_per_trade_pct=RISK.risk_per_trade_pct,
    )

    oos_frames = []
    n_windows = 0
    for _, test_df in walk_forward_windows(df, args.train_days, args.test_days):
        if test_df.empty:
            continue
        oos_frames.append(test_df)
        n_windows += 1

    if not oos_frames:
        raise SystemExit(
            f"No hay suficientes datos para {args.train_days}d train + {args.test_days}d test. "
            f"Bajá --days o el rango de ventana."
        )

    oos_data = pd.concat(oos_frames, ignore_index=True).drop_duplicates("open_time").sort_values("open_time")
    trades, equity_curve = run_backtest(oos_data, params, risk_manager)

    metrics = summarize(trades, equity_curve, PERIODS_PER_YEAR.get(MARKET.timeframe, 365 * 24))

    print(f"Ventanas walk-forward evaluadas (solo out-of-sample): {n_windows}")
    print(f"Periodo total OOS: {oos_data['open_time'].min()} -> {oos_data['open_time'].max()}")
    print(f"Capital inicial: {RISK.capital_total:.2f} | Capital final: {equity_curve.iloc[-1]:.2f}")
    for key, value in metrics.items():
        print(f"  {key}: {value:.4f}" if isinstance(value, float) else f"  {key}: {value}")

    if risk_manager.halted:
        print(f"\n[HALT] {risk_manager.halt_reason}")


if __name__ == "__main__":
    main()

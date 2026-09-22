"""Estrategias técnicas intradía/swing sobre BTC/USDT (Donchian breakout y RSI mean-reversion) en 15m, 1h y 4h,
con y sin costos, con validación walk-forward (solo periodos out-of-sample). Es la primera línea de trabajo del proyecto;
se conserva como referencia de lo que NO funcionó.

Uso: python -m scripts.study_intraday_timeframes
"""
import importlib
import warnings

import pandas as pd

import backtest.engine as eng
from backtest.metrics import summarize
from config import RISK
from data.fetch_binance import load_or_fetch
from risk.risk_manager import RiskManager

warnings.filterwarnings("ignore")
SETS = {"15m": 365, "1h": 1095, "4h": 1095}


def main():
    for tf, days in SETS.items():
        df = load_or_fetch("BTCUSDT", tf, days)
        oos = pd.concat([t for _, t in eng.walk_forward_windows(df, 60, 14) if not t.empty]).drop_duplicates("open_time").sort_values("open_time")
        bh = oos["close"].iloc[-1] / oos["close"].iloc[0] - 1
        print(f"\n=== BTC/USDT {tf}: {len(oos)} velas OOS ({oos['open_time'].min().date()} -> {oos['open_time'].max().date()}) | comprar y mantener {bh:+.1%}")
        for name, mod in (("donchian", "strategy.donchian_breakout"), ("rsi_mr", "strategy.rsi_mean_reversion")):
            m = importlib.import_module(mod)
            for label, fee, slip in (("sin costos", 0.0, 0.0), ("costos reales", 0.001, 0.0005)):
                eng.TAKER_FEE_PCT, eng.SLIPPAGE_PCT = fee, slip
                rm = RiskManager(RISK.capital_total, 0.10, 10.0, RISK.risk_per_trade_pct)  # sin kill switch total: se mide la señal
                trades, eq = eng.run_backtest(oos, m.StrategyParams(), rm, m.compute_signals)
                s = summarize(trades, eq)
                print(f"  {name:9} {label:14} operaciones={s['n_trades']:5} ganadoras={s['win_rate']:.0%} profit_factor={s['profit_factor']:.2f} retorno={s['total_return_pct']:+.1%} maxDD={s['max_drawdown_pct']:.0%}")


if __name__ == "__main__":
    main()

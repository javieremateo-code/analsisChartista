"""Backtest del bot de rejilla sobre acciones elegidas por ser objetivamente laterales (screener/grid.py, ya
validado y con el bug de cruces corregido — ver research/2026-09-22-bot-de-rejilla-grid.md). Velas DIARIAS reales
(no hay tanto histórico horario gratuito para acciones), con el mismo cortafuegos obligatorio.

Selección de candidatas (no es opinión): sobre las 493 acciones del S&P 500 con >=15 años de historial, se calculó
el ratio de eficiencia de Kaufman (movimiento neto / suma de movimientos absolutos: 0=lateral puro, 1=tendencia
pura) y el % de sesiones dentro del +-15% de su precio mediano en los últimos 15 años, exigiendo además que no
fuera una acción cuasi-arruinada (caída máxima > -70%, rango total < 200%). Ganadora: DOC (Healthpeak Properties,
REIT sanitario) con 71% del tiempo cerca de su mediana — tiene sentido: los REIT cotizan más ligados a su dividendo
que al crecimiento. Se prueban también las siguientes dos candidatas (FRT, PPL) para ver si el resultado depende
de haber elegido justo la mejor de la lista (sobreajuste de selección).

Uso: python -m scripts.study_grid_stock [DOC|FRT|PPL ...]
"""
import sys

import numpy as np
import pandas as pd

from screener.grid import GridConfig, simulate_grid
from screener.universe import CACHE

DATA_DIR = CACHE / "grid_stocks_daily"
SPLIT = pd.Timestamp("2018-01-01")  # deja ~8 años fuera de muestra


def perf(equity, ann=252):
    if len(equity) < 10:
        return dict(ret=np.nan, cagr=np.nan, dd=np.nan, sharpe=np.nan)
    r = equity.pct_change().fillna(0.0)
    dd = (equity / equity.cummax() - 1).min()
    yrs = (equity.index[-1] - equity.index[0]).days / 365.25
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / yrs) - 1 if yrs > 0 else np.nan
    sharpe = r.mean() / r.std() * np.sqrt(ann) if r.std() > 0 else np.nan
    return dict(ret=equity.iloc[-1] / equity.iloc[0] - 1, cagr=cagr, dd=dd, sharpe=sharpe)


def line(label, equity):
    p = perf(equity)
    print(f"  {label:<42} ret total {p['ret']:+8.1%} | CAGR {p['cagr']:+7.1%} | Sharpe {p['sharpe']:5.2f} | DD máx {p['dd']:7.1%}")
    return p


def main():
    tickers = sys.argv[1:] or ["DOC", "FRT", "PPL"]
    for tk in tickers:
        f = DATA_DIR / f"{tk}.pkl"
        if not f.exists():
            print(f"{tk}: sin datos (ejecuta antes scripts.fetch_stock_ohlc {tk})")
            continue
        df = pd.read_pickle(f)
        print(f"\n{'=' * 100}\n{tk}: {len(df):,} sesiones diarias | {df.index[0].date()} -> {df.index[-1].date()}\n{'=' * 100}")
        bh = df["close"] / df["close"].iloc[0] * 1000

        print("\nComparación con y sin cortafuegos (range=15%, 15 grids, comisión 0.05%/operación, recentrado cada 60 días):")
        cfg_stop = GridConfig(range_pct=0.15, n_grids=15, fee=0.0005, stop_buffer=0.05, panic_slippage=0.003, recenter_days=60, pause_days=14)
        cfg_nostop = GridConfig(range_pct=0.15, n_grids=15, fee=0.0005, stop_buffer=99.0, recenter_days=60, pause_days=14)
        res_stop = simulate_grid(df, 1000.0, cfg_stop)
        res_nostop = simulate_grid(df, 1000.0, cfg_nostop)
        line("Comprar y mantener", bh)
        line("Rejilla CON cortafuegos", res_stop.equity)
        line("Rejilla SIN cortafuegos", res_nostop.equity)
        print(f"  Cortafuegos saltó {len(res_stop.stops)} veces en {(df.index[-1]-df.index[0]).days} días "
              f"({(df.index[-1]-df.index[0]).days/365.25:.0f} años) | operaciones: {len(res_stop.trades)} "
              f"(compras {(res_stop.trades['side']=='buy').sum()}, ventas {(res_stop.trades['side']=='sell').sum()}, "
              f"cortafuegos {(res_stop.trades['side']=='stop').sum()}, recentrados {(res_stop.trades['side']=='recenter').sum()})")
        if res_stop.stops:
            print("  Fechas del cortafuegos: " + ", ".join(str(s.date()) for s in res_stop.stops))

        print("\nDentro (hasta 2018) vs fuera de muestra (2018-2026):")
        line("  hasta 2018", res_stop.equity[res_stop.equity.index < SPLIT])
        line("  2018-2026 (incluye el Covid)", res_stop.equity[res_stop.equity.index >= SPLIT])
        line("  [ref.] comprar y mantener 2018-2026", bh[bh.index >= SPLIT] / bh[bh.index >= SPLIT].iloc[0] * 1000)

        print("\nSensibilidad al ancho del rango, nº de grids y comisión:")
        for rp in (0.08, 0.12, 0.15, 0.20, 0.25):
            r = simulate_grid(df, 1000.0, GridConfig(range_pct=rp, n_grids=15, fee=0.0005, stop_buffer=0.05, panic_slippage=0.003, recenter_days=60, pause_days=14))
            line(f"  range_pct={rp:.0%}", r.equity)
        for ng in (8, 15, 25):
            r = simulate_grid(df, 1000.0, GridConfig(range_pct=0.15, n_grids=ng, fee=0.0005, stop_buffer=0.05, panic_slippage=0.003, recenter_days=60, pause_days=14))
            line(f"  n_grids={ng}", r.equity)
        for fee in (0.0002, 0.0005, 0.001, 0.002):
            r = simulate_grid(df, 1000.0, GridConfig(range_pct=0.15, n_grids=15, fee=fee, stop_buffer=0.05, panic_slippage=0.003, recenter_days=60, pause_days=14))
            line(f"  comisión {fee:.2%}/operación", r.equity)


if __name__ == "__main__":
    main()

"""Backtest de cartera sobre eventos de racha (compra tras caídas, opcionalmente venta en corto tras subidas).

Entrada al cierre de t, salida al cierre de t+1. Peso por posición = min(max_w, 1/n_posiciones_del_día).
Sin apalancamiento. Costos por lado configurables.
"""
import numpy as np
import pandas as pd


def portfolio(ev, index, cost, dirs=("down",), kmin=2, zmin=4.0, max_w=0.10):
    sel = ev[ev["next"].notna() & (ev["k"] >= kmin) & (ev["z"] >= zmin) & ev["dir"].isin(dirs)].copy()
    sel["pnl"] = np.where(sel["dir"] == "down", sel["next"], -sel["next"]) - 2 * cost
    n = sel.groupby("date")["pnl"].transform("size")
    sel["w"] = np.minimum(max_w, 1.0 / n)
    daily = (sel["pnl"] * sel["w"]).groupby(sel["date"]).sum().reindex(index).fillna(0.0)
    expo = sel.groupby("date")["w"].sum().reindex(index).fillna(0.0)
    return daily, expo, sel["pnl"]


def perf(daily, ann):
    if len(daily) < 30 or daily.std() == 0:
        return dict(cagr=np.nan, sharpe=np.nan, dd=np.nan)
    eq = (1 + daily).cumprod()
    yrs = max((daily.index[-1] - daily.index[0]).days / 365.25, 1e-9)
    return dict(cagr=eq.iloc[-1] ** (1 / yrs) - 1, sharpe=daily.mean() / daily.std() * np.sqrt(ann),
                dd=(eq / eq.cummax() - 1).min())

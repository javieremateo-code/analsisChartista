"""Pregunta 1: ¿mejoran los futuros de commodities la situación (los ETFs no tenían edge)?

Los futuros aportan: historia desde 2000 (más datos), más contratos, posibilidad de operar en corto y de apalancar, costos menores.
Se prueba con las mismas reglas del resto del proyecto (racha + magnitud en σ) y, además, la alternativa clásica de los
futuros: seguimiento de tendencia (time-series momentum) diversificado, largo/corto.

Reglas pre-declaradas: racha >=2 días, z >= 3/4/5; mantener 1 día; costo 0.03%/lado (estrés 0.08%). Corte IS/OOS: 2013.
Grupos: 'líquidos' (19 contratos) y 'todos' (25, incluye avena, arroz, zumo, ganado y cerdo: datos más ruidosos/roll).

Uso: python -m scripts.study_futures
"""
import warnings

import numpy as np
import pandas as pd

from screener.backtest import perf
from screener.events import build_events
from screener.futures import FUTURES, load_futures
from scripts.study_trend_pullback import hold_portfolio

warnings.filterwarnings("ignore")
SPLIT = pd.Timestamp("2013-01-01")
COST = 0.0003
ANN = 252
THIN = ["ZO=F", "ZR=F", "OJ=F", "LE=F", "GF=F", "HE=F"]


def line(label, d, extra=""):
    p, pi, po = perf(d, ANN), perf(d[d.index < SPLIT], ANN), perf(d[d.index >= SPLIT], ANN)
    print(f"  {label:<46} CAGR {p['cagr']:+6.1%} Sharpe {p['sharpe']:5.2f} DD {p['dd']:6.1%} | IS {pi['cagr']:+6.1%} ({pi['sharpe']:5.2f}) | OOS {po['cagr']:+6.1%} ({po['sharpe']:5.2f}, DD {po['dd']:5.1%}){extra}")


def streak_rules(close, name):
    ev = build_events(close)
    e = ev[ev["next"].notna()].copy()
    print(f"\n### {name}: {close.shape[1]} contratos | {close.index[0].date()} -> {close.index[-1].date()} | {len(e):,} eventos")
    e2 = e[e["k"] >= 2].copy()
    e2["fav_rev"] = np.where(e2["dir"] == "down", e2["next"], -e2["next"])  # a favor de la reversión
    print("  P(reversión al día siguiente) por z (racha>=2)   [ todo | IS | OOS ]  y retorno a favor de la reversión")
    for dr, lab in (("down", "BAJADA→sube"), ("up", "SUBIDA→baja")):
        base = (e[(e["dir"] == dr)].pipe(lambda x: (x["next"] > 0) if dr == "down" else (x["next"] < 0))).mean()
        print(f"   {lab} (base {base:.1%})")
        for zb in range(0, 5):
            g = e2[(e2["dir"] == dr) & (e2["zb"] == zb)]
            if len(g) < 50:
                continue
            gi, go = g[g["date"] < SPLIT], g[g["date"] >= SPLIT]
            pr = lambda x: (x["fav_rev"] > 0).mean() if len(x) else float("nan")
            print(f"     z {zb}{'+' if zb == 4 else '-' + str(zb + 1)}σ: n={len(g):6} P={pr(g):5.1%} ret {g['fav_rev'].mean():+.3%} | IS {len(gi):5}/{pr(gi):4.0%} | OOS {len(go):5}/{pr(go):4.0%}")
    print("  Backtest de cartera (peso máx 10%, sin apalancamiento, mantener 1 día)   [total | IS | OOS]")
    for zmin in (3, 4, 5):
        down = e[(e["dir"] == "down") & (e["k"] >= 2) & (e["z"] >= zmin)]
        up = e[(e["dir"] == "up") & (e["k"] >= 2) & (e["z"] >= zmin)]
        line(f"LARGO tras caída z>={zmin}  (n={len(down)})", hold_portfolio(down, close, COST, 1, side=1))
        line(f"CORTO tras subida z>={zmin} (n={len(up)})", hold_portfolio(up, close, COST, 1, side=-1))
        line(f"CONTINUACIÓN: largo tras subida z>={zmin}", hold_portfolio(up, close, COST, 1, side=1))
        line(f"CONTINUACIÓN: corto tras caída z>={zmin}", hold_portfolio(down, close, COST, 1, side=-1))
    d = e[(e["dir"] == "down") & (e["k"] >= 2) & (e["z"] >= 4)]
    line("Estrés de costos: LARGO tras caída z>=4 (0.08%/lado)", hold_portfolio(d, close, 0.0008, 1, side=1))


def tsmom(close, name, lookback=252, skip=21, target=0.10, cost=COST, longonly=False):
    r = close.pct_change().fillna(0.0)
    sig = np.sign(close.shift(skip) / close.shift(lookback) - 1)  # momentum de 12 meses excluyendo el último mes
    if longonly:
        sig = sig.clip(lower=0)
    vol = r.rolling(60).std().shift(1) * np.sqrt(252)
    active = close.notna() & vol.notna() & sig.notna()
    n = active.sum(axis=1).replace(0, np.nan)
    pos = (sig * (target / vol)).clip(-3, 3).where(active).div(n, axis=0).fillna(0.0)  # riesgo repartido entre contratos
    pnl = (pos.shift(1) * r).sum(axis=1) - cost * (pos.diff().abs().sum(axis=1))
    return pnl, pos


def trend_section(close, name):
    print(f"\n### Seguimiento de tendencia (time-series momentum 12-1 meses, riesgo 10% por contrato repartido) — {name}")
    d, pos = tsmom(close, name)
    line("Largo/corto, vol-objetivo", d, f" | exposición bruta media {pos.abs().sum(axis=1).mean():.2f}")
    d2, _ = tsmom(close, name, longonly=True)
    line("Solo largo (comprar lo que sube)", d2)
    d3, _ = tsmom(close, name, cost=0.0008)
    line("Largo/corto con costos 0.08%/lado (estrés)", d3)
    d4, _ = tsmom(close, name, lookback=126, skip=5)
    line("Largo/corto, ventana 6 meses (variante)", d4)
    bh = close.pct_change().mean(axis=1).fillna(0.0)
    line("Referencia: comprar y mantener cesta equiponderada", bh)
    yr = d.groupby(d.index.year).apply(lambda x: (1 + x).prod() - 1)
    print("  Por año (largo/corto): " + " | ".join(f"{y}:{v:+.0%}" for y, v in yr.items()))


def main():
    fut = load_futures()
    liquid = fut[[c for c in fut.columns if c not in THIN]]
    streak_rules(liquid, "FUTUROS LÍQUIDOS (19)")
    streak_rules(fut, "TODOS LOS FUTUROS (25)")
    trend_section(liquid, "líquidos (19)")
    trend_section(fut, "todos (25)")


if __name__ == "__main__":
    main()

"""Tercera campaña: calidad frente a cantidad, más operaciones por día (universo de 200), otros activos como filtro de la capa de tendencia y apalancamiento.

E1) Relación entre probabilidad de ganar y ganancia: escalonando el umbral del modelo (0.6 ... 0.9) y escalando el tamaño al mismo riesgo (caída -10%).
E2) Más operaciones al día: universo de las ~200 principales (liquidez >= 5 M) en lugar de 100.
E3) Filtros de otros activos (S&P sobre su SMA200, VIX < 30, dólar no en tendencia alcista) sobre la capa de tendencia BTC/ETH.
E4) Apalancamiento del sistema completo con costo de financiación (6% anual sobre lo prestado) y apalancamiento selectivo solo en señales de alta probabilidad.

Uso: python -m scripts.optimize_more [E1|E2|E3|E4]
"""
import sys
import warnings

import numpy as np
import pandas as pd

from screener import crypto100
from screener.backtest import perf
from screener.events import build_events
from screener.external import us_levels
from screener.ml_score import compute_features
from screener.news import fear_greed
from screener.risk import PROFILES
from screener.trend import WINDOWS
from scripts.backtest_system import START, SPLIT_T
from scripts.optimize_bot import add_walkforward_ml, load_events, report, run
from scripts.study_trend_pullback import hold_portfolio

warnings.filterwarnings("ignore")
COST = 0.0015
CASH = 0.03 / 365
BORROW = 0.06 / 365


def fmt(s, label, ann=365, start=START):
    s = s[s.index >= start]
    p, po = perf(s, ann), perf(s[s.index >= SPLIT_T], ann)
    return f"{label:<40} CAGR {p['cagr']:+6.1%} Sharpe {p['sharpe']:4.2f} DD {p['dd']:6.1%} | 2022+ {po['cagr']:+6.1%} ({po['sharpe']:.2f}, DD {po['dd']:.1%})"


def e1():
    close, down = load_events()
    down = add_walkforward_ml(down)
    prof = PROFILES["balanceado"]
    print("E1) CALIDAD FRENTE A CANTIDAD — perfil balanceado, filtro por probabilidad del modelo y tamaño reescalado a caída máxima ≈ -10%")
    print(f"{'umbral P':>9} | {'ops':>4} {'ops/año':>7} {'gana':>5} {'neto/op':>8} | {'CAGR (tamaño base)':>19} {'DD':>7} | {'CAGR con tamaño para DD -10%':>30}")
    for thr in (0.0, 0.6, 0.7, 0.8, 0.9):
        tr = []
        s, n = run(down, prof, mode="mlboth", ml_min=thr, trades=tr)
        s = s[s.index >= START]
        t = pd.DataFrame(tr)
        p = perf(s, 365)
        k = 0.10 / abs(p["dd"]) if p["dd"] < 0 else 1.0
        pk = perf(s * k, 365)
        print(f"{thr:9.2f} | {n:4} {n / 6.7:7.0f} {(t['net'] > 0).mean():5.0%} {t['net'].mean():+8.2%} | {p['cagr']:+18.1%} {p['dd']:7.1%} | {pk['cagr']:+12.1%} (x{k:.1f}, Sharpe {pk['sharpe']:.2f})")
    print("  (el retorno escalado supone poder aumentar el tamaño x k, es decir, apalancar si el capital no alcanza)")
    tr = []
    run(down, prof, mode="mlboth", ml_min=0.6, trades=tr)
    t = pd.DataFrame(tr)
    print("\n  Tasa de acierto por tramo de probabilidad del modelo (operaciones del replay balanceado):")
    for lo, hi in ((0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01)):
        g = t[(t["ml"] >= lo) & (t["ml"] < hi)]
        if len(g):
            print(f"     P {lo:.1f}-{min(hi, 1.0):.1f}: n={len(g):3} | gana {(g['net'] > 0).mean():4.0%} | neto medio {g['net'].mean():+.2%} | peor {g['net'].min():+.1%}")


def events_universe(n):
    uni = crypto100.get_universe(n=n)["coins"]
    coins = [c for c in uni if c not in crypto100.EXCLUDE and c.isascii()]
    close, qv = crypto100.clean_universe(*crypto100.load("1d", coins=coins))
    ev = build_events(close)
    down = ev[(ev["dir"] == "down") & (ev["k"] >= 2) & ev["next"].notna()].copy()
    down = compute_features(close, qv, fear_greed(), down)
    down = down[down["liq"] >= crypto100.MIN_LIQUIDITY].reset_index(drop=True)
    return close, down


def e2():
    print("E2) MÁS OPERACIONES AL DÍA — universo de 100 frente a ~200 principales (liquidez >= 5 M USDT/día)")
    for n in (100, 200):
        close, down = events_universe(n)
        down = add_walkforward_ml(down)
        d3 = down[(down["z"] >= 3) & (down["date"] >= START)]
        print(f"\n  Universo {n}: {close.shape[1]} monedas | eventos z>=3 desde 2020: {len(d3)} en {d3['date'].nunique()} días (media {len(d3) / d3['date'].nunique():.1f} por día con señal)")
        for pname in ("balanceado", "agresivo"):
            tr = []
            s, k = run(down, PROFILES[pname], mode="mlboth", ml_min=0.60, trades=tr)
            t = pd.DataFrame(tr)
            print("   " + fmt(s, f"{pname} (ops {k}, {t['date'].nunique()} días con operación)"))


def trend_pos(px, gate=None):
    sig = pd.concat([(px > px.rolling(n).mean()).astype(float) for n in WINDOWS], axis=1).mean(axis=1)
    if gate is not None:
        sig = sig * gate.reindex(px.index).fillna(0.0)
    return sig.shift(1).fillna(0.0)


def sleeve_from(close, gate=None, cost=COST):
    rets, poss = [], []
    for c in ("BTC", "ETH"):
        pos = trend_pos(close[c], gate)
        rets.append(pos * close[c].pct_change().fillna(0.0) - cost * pos.diff().abs().fillna(0.0))
        poss.append(pos)
    return sum(rets) / 2, sum(poss) / 2


def e3():
    close, _ = crypto100.clean_universe(*crypto100.load("1d"))
    lv = us_levels().reindex(close.index, method="ffill", limit=5)
    gates = {"sin filtro": None,
             "S&P sobre su SMA200": (lv["SPY"] > lv["SPY"].rolling(200).mean()).astype(float),
             "VIX < 30": (lv["VIX"] < 30).astype(float),
             "dólar (UUP) bajo su SMA100": (lv["DXY"] < lv["DXY"].rolling(100).mean()).astype(float),
             "S&P sobre SMA200 y VIX < 30": ((lv["SPY"] > lv["SPY"].rolling(200).mean()) & (lv["VIX"] < 30)).astype(float)}
    print("E3) OTROS ACTIVOS COMO FILTRO DE LA CAPA DE TENDENCIA (BTC+ETH, media SMA100/150/200, 2018-06 a 2026)")
    start = pd.Timestamp("2018-06-01")
    base = None
    for name, g in gates.items():
        s, pos = sleeve_from(close, g)
        r = s[s.index >= start]
        p, pi, po = perf(r, 365), perf(r[r.index < SPLIT_T], 365), perf(r[r.index >= SPLIT_T], 365)
        if base is None:
            base = (p, po)
        print(f"  {name:<32} CAGR {p['cagr']:+6.1%} Sharpe {p['sharpe']:4.2f} DD {p['dd']:6.1%} | IS {pi['cagr']:+6.1%} ({pi['sharpe']:.2f}) | OOS {po['cagr']:+6.1%} ({po['sharpe']:.2f}, DD {po['dd']:.1%}) | en mercado {pos[pos.index >= start].mean():.0%}")
    print("  Criterio: adoptar si mejora el Sharpe OOS en >= 0.10 y no pierde más del 15% del CAGR total")


def mc(r, n=3000, seed=3):
    rng = np.random.default_rng(seed)
    pool, fin, dds = r.values, [], []
    for _ in range(n):
        path = []
        while len(path) < 365:
            s = rng.integers(0, len(pool) - 10)
            path.extend(pool[s:s + 10])
        eq = np.cumprod(1 + np.array(path[:365]))
        fin.append(eq[-1] - 1)
        dds.append((eq / np.maximum.accumulate(eq) - 1).min())
    return np.array(fin), np.array(dds)


def e4():
    close, down = load_events()
    down = add_walkforward_ml(down)
    prof = PROFILES["balanceado"]
    A, _ = run(down, prof, mode="mlboth", ml_min=0.60)
    c4 = crypto100.clean_universe(crypto100.load("4h")[0])
    e4 = build_events(c4)
    e4 = e4[(e4["dir"] == "down") & (e4["k"] >= 2) & (e4["z"] >= 6) & e4["next"].notna()]
    B = hold_portfolio(e4, c4, COST, 1)
    B = B.groupby(B.index.normalize()).sum()
    idx = pd.date_range(START, A.index.max(), freq="D")
    A, B = A.reindex(idx, fill_value=0.0), B.reindex(idx, fill_value=0.0)
    sleeve, pos = sleeve_from(close)
    sleeve, pos = sleeve.reindex(idx, fill_value=0.0), pos.reindex(idx, fill_value=0.0)
    f = prof.trend_fraction
    print("E4) APALANCAMIENTO del sistema completo balanceado (reglas + 4h x0.55 + capa de tendencia 20% + caja 3%); financiación 6% anual sobre lo prestado")
    print("    Nota: las reglas de rebote se mantienen 1 día (financiación despreciable); la capa de tendencia paga financiación mientras está en mercado.")
    print(f"{'L':>4} | {'CAGR':>7} {'Sharpe':>6} {'DD':>7} | {'2022+':>7} | {'peor día':>8} | {'1 año 1000 €: mediana / peor 5%':>32} | P(DD>20%) P(DD>30%) P(DD>50%)")
    for L in (1.0, 1.5, 2.0, 3.0, 5.0):
        fin_cost = (L - 1) * f * pos * BORROW  # solo la capa de tendencia paga financiación continua
        r = L * (A + 0.55 * B + f * sleeve) + (1 - f) * CASH - fin_cost
        r = r[r.index >= START]
        p, po = perf(r, 365), perf(r[r.index >= SPLIT_T], 365)
        fin, dd = mc(r)
        print(f"{L:4.1f} | {p['cagr']:+7.1%} {p['sharpe']:6.2f} {p['dd']:7.1%} | {po['cagr']:+7.1%} | {r.min():+8.1%} | {np.median(fin) * 1000:+14.0f} € / {np.percentile(fin, 5) * 1000:+6.0f} € | {(dd < -0.2).mean():8.0%} {(dd < -0.3).mean():9.0%} {(dd < -0.5).mean():9.1%}")
    print("\n    Apalancamiento SELECTIVO: x2 de tamaño solo en señales diarias con P(rebote) del modelo >= 0.85 (el resto igual)")
    base_s, _ = run(down, prof, mode="mlboth", ml_min=0.60)
    for thr, mult in ((0.85, 2.0), (0.80, 2.0), (0.85, 3.0)):
        extra = lambda r, thr=thr, mult=mult: (False, mult if (pd.notna(r.ml) and r.ml >= thr) else 1.0)
        tr = []
        s, n = run(down, prof, mode="mlboth", ml_min=0.60, extra=extra, trades=tr)
        t = pd.DataFrame(tr)
        hi = t[t["ml"] >= thr]
        print("     " + fmt(s, f"P>={thr:.2f} x{mult:.0f} (ops alta conf.: {len(hi)}, gana {(hi['net'] > 0).mean():.0%})"))
    print("     " + fmt(base_s, "referencia sin apalancar"))


def main():
    what = sys.argv[1:] or ["E1", "E2", "E3", "E4"]
    for w, fn in (("E1", e1), ("E2", e2), ("E3", e3), ("E4", e4)):
        if w in what:
            fn()
            print()


if __name__ == "__main__":
    main()

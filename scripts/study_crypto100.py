"""Ampliación a las ~100 principales criptos: regla diaria (perfiles), regla de 4 h y regla de 1 h.

Secciones (argumento): daily | 8h | 4h | 1h  (sin argumento: todas). Datos: `python -m scripts.fetch_crypto100`.
Exclusiones: stablecoins, oro tokenizado (XAUT, PAXG), FRAX, RLUSD, U y tokens con símbolo no ASCII.
AVISO: universo = top 100 de HOY (sesgo de supervivencia).

Uso: python -m scripts.study_crypto100 [daily|4h|1h]
"""
import sys
import warnings

import numpy as np
import pandas as pd

from screener import crypto100
from screener.backtest import perf
from screener.events import build_events
from screener.risk import PROFILES
from screener.universe import COST, CRYPTO
from scripts.backtest_system import START, SPLIT_T, montecarlo, run_profile
from scripts.study_trend_pullback import hold_portfolio

warnings.filterwarnings("ignore")
COST_C = COST["crypto"]
ORIG = set(CRYPTO)


clean = crypto100.clean_universe


def line(label, s, tr=None, start=START, ann=365):
    s = s[s.index >= start]
    p, po = perf(s, ann), perf(s[s.index >= SPLIT_T], ann)
    ex = f" | ops {len(tr):4} neto/op {tr['ret'].mean():+.2%} gana {(tr['ret'] > 0).mean():3.0%}" if tr is not None and len(tr) else ""
    print(f"  {label:<42} CAGR {p['cagr']:+6.1%} Sharpe {p['sharpe']:5.2f} DD {p['dd']:6.1%} | OOS22+ {po['cagr']:+6.1%} ({po['sharpe']:.2f}, DD {po['dd']:.1%}){ex}")


def daily():
    close, qv = clean(*crypto100.load("1d"))
    print(f"DIARIO: {close.shape[1]} monedas ({close.index[0].date()} -> {close.index[-1].date()}) | de ellas {len(set(close.columns) & ORIG)} estaban en el universo original")
    ev = build_events(close)
    down = ev[(ev["dir"] == "down") & (ev["k"] >= 2) & ev["next"].notna()].copy()
    btc = close["BTC"]
    down["dd90"] = down["date"].map(btc / btc.rolling(90).max() - 1)
    liq = qv.rolling(30).mean()
    pos, col = close.index.get_indexer(down["date"]), close.columns.get_indexer(down["asset"])
    down["liq"] = liq.values[pos, col]
    down["net"] = down["next"] - 2 * COST_C
    print(f"Eventos de caída (2+ días): {len(down):,} | z>=3: {(down['z'] >= 3).sum()} eventos en {down[down['z'] >= 3]['date'].nunique()} fechas")

    print("\n--- P(rebote) y retorno neto a 1 día por magnitud: universo original vs monedas NUEVAS (no estaban en el original) ---")
    for lab, m in (("original", down["asset"].isin(ORIG)), ("nuevas", ~down["asset"].isin(ORIG))):
        for zlo, zhi in ((2, 3), (3, 4), (4, 99)):
            g = down[m & (down["z"] >= zlo) & (down["z"] < zhi)]
            gi, go = g[g["date"] < SPLIT_T], g[g["date"] >= SPLIT_T]
            print(f"  {lab:>8} z {zlo}{'+' if zhi == 99 else '-' + str(zhi)}σ: n={len(g):5} P={(g['next'] > 0).mean():5.1%} neto {g['net'].mean():+.2%} | IS n={len(gi)} {(gi['net'].mean() if len(gi) else float('nan')):+.2%} | OOS n={len(go)} {(go['net'].mean() if len(go) else float('nan')):+.2%} | peor {g['net'].min():+.0%}")

    print("\n--- Replay día a día del informe (estadísticas sin lookahead, refresco trimestral) ---")
    res = {}
    for name, prof in PROFILES.items():
        s, tr = run_profile(down, prof)
        res[name] = (s, tr)
        line(f"TOP-100, perfil {name}", s, tr)
    prof = PROFILES["balanceado"]
    print("\n  Comparación de universos (perfil balanceado):")
    variants = {"universo original (~41)": down[down["asset"].isin(ORIG)], "TOP-100 completo": down,
                "solo monedas NUEVAS": down[~down["asset"].isin(ORIG)], "TOP-100 liquidez >= 5 M USDT/día": down[down["liq"] >= 5e6],
                "TOP-100 liquidez >= 20 M USDT/día": down[down["liq"] >= 20e6], "TOP-100 liquidez >= 50 M USDT/día": down[down["liq"] >= 50e6]}
    for lab, d in variants.items():
        if (d["z"] >= 3).sum() < 30:
            print(f"  {lab:<42} pocos eventos ({int((d['z'] >= 3).sum())})")
            continue
        s, tr = run_profile(d, prof)
        line(lab, s, tr)
    print("\n  Robustez del TOP-100 (balanceado):")
    for c in (0.003, 0.005, 0.01):
        s, tr = run_profile(down, prof, cost=c)
        line(f"costo {c:.2%}/lado", s, tr)
    b = res["balanceado"][0]
    b = b[b.index >= START]
    p = perf(b.drop(b.nlargest(5).index), 365)
    print(f"  {'sin los 5 mejores días':<42} CAGR {p['cagr']:+6.1%} Sharpe {p['sharpe']:5.2f} DD {p['dd']:6.1%}")
    yr = b.groupby(b.index.year).apply(lambda x: (1 + x).prod() - 1)
    print("  Por año (balanceado): " + " | ".join(f"{y}:{v:+.1%}" for y, v in yr.items()))
    print("\n  Monte Carlo 1 año con 1000 € (TOP-100):")
    for name, (s, _) in res.items():
        montecarlo(s, name)
    return down


def bars(interval, hold_bars, zs=(3, 4, 5, 6, 7), ann=None):
    close, qv = clean(*crypto100.load(interval))
    per_day = {"8h": 3, "4h": 6, "1h": 24}[interval]
    ann = ann or 365 * per_day
    print(f"\n{interval.upper()}: {close.shape[1]} monedas | {len(close):,} velas | {close.index[0].date()} -> {close.index[-1].date()}")
    ev = build_events(close)
    e = ev[ev["next"].notna() & (ev["dir"] == "down") & (ev["k"] >= 2)].copy()
    e["net"] = e["next"] - 2 * COST_C
    print(f"Eventos de caída (2+ velas): {len(e):,}")
    print("  P(sube en la vela siguiente) y neto por magnitud:   [ todo | IS | OOS ]")
    for zlo in (3, 4, 5, 6, 7, 8):
        g = e[e["z"] >= zlo]
        gi, go = g[g["date"] < SPLIT_T], g[g["date"] >= SPLIT_T]
        if len(g) < 40:
            continue
        print(f"   z>={zlo}: n={len(g):6} P={(g['next'] > 0).mean():5.1%} neto/op {g['net'].mean():+.3%} | IS {len(gi):5} {(gi['net'].mean() if len(gi) else float('nan')):+.2%} | OOS {len(go):5} {(go['net'].mean() if len(go) else float('nan')):+.2%}")

    def pline(label, d):
        p, pi, po = perf(d, ann), perf(d[d.index < SPLIT_T], ann), perf(d[d.index >= SPLIT_T], ann)
        print(f"   {label:<44} CAGR {p['cagr']:+6.1%} Sharpe {p['sharpe']:5.2f} DD {p['dd']:6.1%} | IS {pi['cagr']:+6.1%} ({pi['sharpe']:.2f}) | OOS {po['cagr']:+6.1%} ({po['sharpe']:.2f}, DD {po['dd']:.1%})")

    print("  Cartera (peso máx 10%, sin apalancamiento)   [total | IS | OOS]")
    best = None
    for zmin in zs:
        sel = e[e["z"] >= zmin]
        if len(sel) < 60:
            continue
        for h in hold_bars:
            d = hold_portfolio(sel, close, COST_C, h)
            pline(f"z>={zmin}, mantener {h} vela(s) (n={len(sel)})", d)
    return close, e


def main():
    what = sys.argv[1:] or ["daily", "8h", "4h", "1h"]
    if "daily" in what:
        daily()
    if "8h" in what:
        bars("8h", (1, 3))
    if "4h" in what:
        bars("4h", (1, 6))
    if "1h" in what:
        close, e = bars("1h", (1, 4, 24))
        for zmin, h in ((6, 1), (7, 1), (8, 1)):
            sel = e[e["z"] >= zmin]
            if len(sel) < 60:
                continue
            print(f"\n  Robustez 1h z>={zmin}, mantener {h} vela (n={len(sel)}):")
            for c in (0.0015, 0.003, 0.005):
                d = hold_portfolio(sel, close, c, h)
                p, po = perf(d, 365 * 24), perf(d[d.index >= SPLIT_T], 365 * 24)
                print(f"    costo {c:.2%}/lado: CAGR {p['cagr']:+6.1%} Sharpe {p['sharpe']:5.2f} DD {p['dd']:6.1%} | OOS {po['cagr']:+6.1%} ({po['sharpe']:.2f})")
            d = hold_portfolio(sel, close, COST_C, h)
            p = perf(d.drop(d.nlargest(20).index), 365 * 24)
            print(f"    sin las 20 mejores velas: CAGR {p['cagr']:+6.1%} Sharpe {p['sharpe']:5.2f}")


if __name__ == "__main__":
    main()

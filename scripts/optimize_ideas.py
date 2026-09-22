"""Barrido de ideas para mejorar el rendimiento, cada una con criterio de adopción fijado de antemano.

A) Pistas de otros activos para el modelo de probabilidad: mercados externos (S&P, Nasdaq, VIX, dólar, bonos, oro), funding de futuros y caída relativa a BTC.
   Adoptar solo si mejora el CAGR y el Sharpe de 2022-2026 frente al modelo actual sin empeorar la caída máxima más de 1.5x.
B) Capa de tendencia sobre el capital parado (BTC/ETH por encima de su media móvil): mejora del sistema completo en Sharpe y caída máxima.
C) Factores entre monedas (momentum, reversión, volatilidad, volumen) como capa independiente, rebalanceo semanal, costos incluidos.
Uso: python -m scripts.optimize_ideas [A|B|C]
"""
import sys
import warnings

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

from screener import crypto100
from screener.backtest import perf
from screener.events import build_events
from screener.external import cross_asset_features, funding_100
from screener.ml_score import FEATS, compute_features
from screener.news import fear_greed
from screener.risk import PROFILES
from scripts.backtest_system import START, SPLIT_T
from scripts.optimize_bot import report, run
from scripts.study_trend_pullback import hold_portfolio

warnings.filterwarnings("ignore")
COST = 0.0015
CROSS = ["spy_ret1", "spy_ret5", "qqq_ret5", "vix", "vix_chg5", "dxy_ret5", "tnx_chg5", "gld_ret5"]
FUND = ["fund3", "fund_z"]
REL = ["rel_btc"]


def extended_events():
    close, qv = crypto100.clean_universe(*crypto100.load("1d"))
    ev = build_events(close)
    down = ev[(ev["dir"] == "down") & (ev["k"] >= 2) & ev["next"].notna()].copy()
    down = compute_features(close, qv, fear_greed(), down)
    down = down[down["liq"] >= 5e6].reset_index(drop=True)
    X = cross_asset_features(close.index)
    for c in X.columns:
        down[c] = X[c].reindex(down["date"]).values
    fund = funding_100(list(close.columns)).reindex(index=close.index, columns=close.columns)
    f3 = fund.rolling(3, min_periods=2).mean()
    fz = (f3 - f3.rolling(90).mean()) / f3.rolling(90).std()
    pos, col = close.index.get_indexer(down["date"]), close.columns.get_indexer(down["asset"])
    down["fund3"], down["fund_z"] = f3.values[pos, col], fz.values[pos, col]
    btc = close["BTC"]
    rel = close.pct_change(3).sub(btc.pct_change(3), axis=0)
    down["rel_btc"] = rel.values[pos, col]
    return close, down


def wf_ml(down, feats):
    """Probabilidad de rebote con reentrenamiento trimestral solo con eventos anteriores (z>=2)."""
    out = pd.Series(np.nan, index=down.index)
    broad = down[down["z"] >= 2]
    for q in pd.date_range(START, down["date"].max(), freq="QS"):
        tr = broad[broad["date"] < q - pd.Timedelta(days=1)]
        te = down.index[(down["date"] >= q) & (down["date"] < q + pd.offsets.QuarterBegin(startingMonth=1)) & (down["z"] >= 2)]
        if len(tr) < 300 or len(te) == 0:
            continue
        m = HistGradientBoostingClassifier(max_depth=3, max_iter=100, learning_rate=0.05, l2_regularization=1.0, random_state=0)
        m.fit(tr[feats], (tr["next"] > 0).astype(int))
        out.loc[te] = m.predict_proba(down.loc[te, feats])[:, 1]
    return out


def section_a():
    close, down = extended_events()
    print(f"A) PISTAS DE OTROS ACTIVOS — eventos {len(down)} | z>=3: {(down['z'] >= 3).sum()}")
    print("   Datos disponibles (no nulos, eventos z>=3): " + " ".join(f"{c}:{down.loc[down['z'] >= 3, c].notna().mean():.0%}" for c in CROSS + FUND + REL))
    d3 = down[down["z"] >= 3]
    print("\n   Régimen de renta variable (S&P a 5 días) y el rebote de la regla (z>=3, neto a 1 día):")
    for lab, m in (("S&P cae >= 5% en 5d", d3["spy_ret5"] <= -0.05), ("S&P entre -5% y 0%", (d3["spy_ret5"] > -0.05) & (d3["spy_ret5"] <= 0)), ("S&P sube", d3["spy_ret5"] > 0),
                   ("VIX > 25", d3["vix"] > 25), ("VIX <= 25", d3["vix"] <= 25)):
        g = d3[m & d3["spy_ret5"].notna()]
        gi, go = g[g["date"] < SPLIT_T], g[g["date"] >= SPLIT_T]
        print(f"     {lab:<22} n={len(g):4} P={(g['next'] > 0).mean():4.0%} neto {g['next'].mean() - 0.003:+.2%} | IS n={len(gi)} {(gi['next'].mean() - 0.003 if len(gi) else float('nan')):+.2%} | OOS n={len(go)} {(go['next'].mean() - 0.003 if len(go) else float('nan')):+.2%}")
    prof = PROFILES["balanceado"]
    variants = {"modelo actual (17 variables)": FEATS, "+ mercados externos": FEATS + CROSS, "+ funding": FEATS + FUND, "+ caída relativa a BTC": FEATS + REL,
                "+ todo": FEATS + CROSS + FUND + REL}
    print("\n   Modelo walk-forward con cada grupo de variables (perfil balanceado, replay 2020-2026):")
    res = {}
    for name, feats in variants.items():
        down["ml"] = wf_ml(down, feats)
        d = down[(down["z"] >= 3) & down["ml"].notna()]
        auc = roc_auc_score((d["next"] > 0).astype(int), d["ml"])
        s, n = run(down, prof, mode="mlboth", ml_min=0.60)
        print(f"   AUC {auc:.3f} |", end="")
        res[name] = report(name, s, n)
    b = res["modelo actual (17 variables)"]
    print("\n   Criterio: mejora CAGR y Sharpe en 2022+ frente al modelo actual, DD <= 1.5x, sin peor 'sin 5 mejores días'")
    for k, r in res.items():
        if k.startswith("modelo actual"):
            continue
        ok = r["o_cagr"] > b["o_cagr"] and r["o_sh"] > b["o_sh"] and r["dd"] >= b["dd"] * 1.5 and r["x5"] >= b["x5"]
        print(f"     {k:<26} -> {'ADOPTABLE' if ok else 'no cumple'}")


def section_a2():
    """Filtro explícito de pánico sistémico: salta la señal si el S&P sube (crash específico de cripto) y agranda si hay estrés (VIX>25)."""
    close, down = extended_events()
    down["ml_base"] = wf_ml(down, FEATS)
    down["ml_cross"] = wf_ml(down, FEATS + CROSS)
    print("A2) FILTRO DE PÁNICO SISTÉMICO (S&P a 5 días > 0 -> no operar) y tilt por VIX (x1.3 si VIX>25)")
    no_up = lambda r: (bool(pd.notna(r.spy_ret5) and r.spy_ret5 > 0), 1.0)
    tilt = lambda r: (bool(pd.notna(r.spy_ret5) and r.spy_ret5 > 0), 1.3 if (pd.notna(r.vix) and r.vix > 25) else 1.0)
    tilt_only = lambda r: (False, 1.3 if (pd.notna(r.vix) and r.vix > 25) else 1.0)
    for pname in ("balanceado", "agresivo"):
        prof = PROFILES[pname]
        print(f"\n  Perfil {pname}")
        res = {}
        down["ml"] = down["ml_base"]
        res["base"] = report("sin modelo ni filtros", *run(down, prof))
        res["ml"] = report("modelo actual (mlboth)", *run(down, prof, mode="mlboth", ml_min=0.60))
        res["f"] = report("solo filtro 'S&P no sube'", *run(down, prof, extra=no_up))
        res["ft"] = report("filtro + tilt VIX", *run(down, prof, extra=tilt))
        res["mlf"] = report("modelo actual + filtro", *run(down, prof, mode="mlboth", ml_min=0.60, extra=no_up))
        res["mlft"] = report("modelo actual + filtro + tilt VIX", *run(down, prof, mode="mlboth", ml_min=0.60, extra=tilt))
        down["ml"] = down["ml_cross"]
        res["mcf"] = report("modelo + mercados externos + filtro", *run(down, prof, mode="mlboth", ml_min=0.60, extra=no_up))
        res["mcft"] = report("modelo + mercados ext. + filtro + tilt", *run(down, prof, mode="mlboth", ml_min=0.60, extra=tilt))
        b = res["ml"]
        print("  Criterio frente al modelo actual: mejora CAGR y Sharpe 2022+, DD <= 1.5x, 'sin 5 mejores' no inferior")
        for k in ("f", "ft", "mlf", "mlft", "mcf", "mcft"):
            r = res[k]
            ok = r["o_cagr"] > b["o_cagr"] and r["o_sh"] > b["o_sh"] and r["dd"] >= b["dd"] * 1.5 and r["x5"] >= b["x5"]
            print(f"     {k:<5} -> {'ADOPTABLE' if ok else 'no cumple'}")


def trend_series(px, n, cost=COST):
    sig = (px > px.rolling(n).mean()).astype(float)
    pos = sig.shift(1).fillna(0.0)
    r = px.pct_change().fillna(0.0)
    return pos * r - cost * pos.diff().abs().fillna(0.0)


def section_b():
    close, qv = crypto100.clean_universe(*crypto100.load("1d"))
    print("B) CAPA DE TENDENCIA SOBRE EL CAPITAL PARADO (posición 100% si el precio > media móvil de N días, si no, caja)")
    print("   Sin comisión de financiación; costo 0.15% por cambio de posición. Periodo 2018-06 a 2026.")
    start = pd.Timestamp("2018-06-01")

    def line(label, r):
        r = r[r.index >= start]
        p, pi, po = perf(r, 365), perf(r[r.index < SPLIT_T], 365), perf(r[r.index >= SPLIT_T], 365)
        print(f"   {label:<34} CAGR {p['cagr']:+6.1%} Sharpe {p['sharpe']:4.2f} DD {p['dd']:6.1%} | IS {pi['cagr']:+6.1%} ({pi['sharpe']:.2f}) | OOS {po['cagr']:+6.1%} ({po['sharpe']:.2f}, DD {po['dd']:.1%})")
        return r

    for coin in ("BTC", "ETH"):
        line(f"{coin} comprar y mantener", close[coin].pct_change().fillna(0.0))
        for n in (100, 150, 200):
            line(f"{coin} tendencia SMA{n}", trend_series(close[coin], n))
    liq = qv.rolling(30).mean()
    top = [c for c in close.columns if liq[c].iloc[-1] >= 5e7][:10]
    ew = pd.concat([trend_series(close[c], 200) for c in top], axis=1).mean(axis=1)
    line(f"cesta {len(top)} líquidas, SMA200 (cada una)", ew)
    line("cesta equiponderada mantener", close[top].pct_change().mean(axis=1).fillna(0.0))

    # combinación con el sistema (balanceado + modelo + 4 h con retraso + caja)
    from scripts.optimize_bot import add_walkforward_ml, load_events
    _, down = load_events()
    down = add_walkforward_ml(down)
    A, _ = run(down, PROFILES["balanceado"], mode="mlboth", ml_min=0.60)
    c4 = crypto100.clean_universe(crypto100.load("4h")[0])
    e4 = build_events(c4)
    e4 = e4[(e4["dir"] == "down") & (e4["k"] >= 2) & (e4["z"] >= 6) & e4["next"].notna()]
    B = hold_portfolio(e4, c4, COST, 1)
    B = B.groupby(B.index.normalize()).sum()
    idx = pd.date_range(START, A.index.max(), freq="D")
    A, B = A.reindex(idx, fill_value=0.0), B.reindex(idx, fill_value=0.0)
    CASH = 0.03 / 365
    print("\n   SISTEMA + capa de tendencia sobre parte del capital (BTC SMA200) — comparar con 'solo sistema'")
    trend = trend_series(close["BTC"], 200).reindex(idx, fill_value=0.0)
    ethtr = trend_series(close["ETH"], 200).reindex(idx, fill_value=0.0)
    base = A + 0.55 * B

    def show(label, r):
        r = r[r.index >= START]
        p, po = perf(r, 365), perf(r[r.index >= SPLIT_T], 365)
        rng = np.random.default_rng(3)
        pool, fin, dds = r.values, [], []
        for _ in range(3000):
            path = []
            while len(path) < 365:
                s0 = rng.integers(0, len(pool) - 10)
                path.extend(pool[s0:s0 + 10])
            eq = np.cumprod(1 + np.array(path[:365]))
            fin.append(eq[-1] - 1)
            dds.append((eq / np.maximum.accumulate(eq) - 1).min())
        fin, dds = np.array(fin), np.array(dds)
        print(f"   {label:<46} CAGR {p['cagr']:+6.1%} Sharpe {p['sharpe']:4.2f} DD {p['dd']:6.1%} | 2022+ {po['cagr']:+6.1%} | 1 año 1000 €: mediana {np.median(fin) * 1000:+4.0f} €, peor 5% {np.percentile(fin, 5) * 1000:+5.0f} €, P(DD>20%) {(dds < -0.2).mean():3.0%}")

    show("solo sistema + caja 3%", base + CASH)
    for f in (0.25, 0.5, 0.75):
        show(f"sistema + {f:.0%} del capital en tendencia BTC", base + (1 - f) * CASH + f * trend)
    for f in (0.25, 0.5):
        show(f"sistema + {f:.0%} en tendencia (BTC+ETH mitad y mitad)", base + (1 - f) * CASH + f * 0.5 * (trend + ethtr))


def section_c():
    close, qv = crypto100.clean_universe(*crypto100.load("1d"))
    print("C) FACTORES ENTRE MONEDAS (long-only, quintil superior, rebalanceo cada 7 días, liquidez >= 5 M, costo 0.15% por lado sobre lo operado)")
    liq = qv.rolling(30).mean()
    R = close.pct_change()
    factors = {"momentum 30d": close / close.shift(30) - 1, "momentum 90d": close / close.shift(90) - 1, "reversión 7d (perdedoras)": -(close / close.shift(7) - 1),
               "baja volatilidad 30d": -R.rolling(30).std(), "volumen creciente (vr 7/30)": qv.rolling(7).mean() / qv.rolling(30).mean(),
               "cerca de máximos 30d": close / close.rolling(30).max(), "lejos de máximos 90d (barata)": -(close / close.rolling(90).max())}
    reb = close.index[close.index >= pd.Timestamp("2019-01-01")][::7]
    start = reb[0]

    def portfolio(score, top=0.2):
        W = pd.DataFrame(0.0, index=close.index, columns=close.columns)
        prev = pd.Series(0.0, index=close.columns)
        cost_days = pd.Series(0.0, index=close.index)
        for d in reb:
            elig = liq.loc[d] >= 5e6
            sc = score.loc[d][elig].dropna()
            if len(sc) < 10:
                w = prev * 0
            else:
                pick = sc.nlargest(max(3, int(len(sc) * top))).index
                w = pd.Series(0.0, index=close.columns)
                w[pick] = 1.0 / len(pick)
            cost_days.loc[d] = 0.0015 * (w - prev).abs().sum()
            i = close.index.get_loc(d)
            j = min(i + 7, len(close.index))
            W.iloc[i:j] = w.values
            prev = w
        ret = (W.shift(1) * R.fillna(0.0)).sum(axis=1) - cost_days
        return ret[ret.index >= start]

    def line(label, r):
        p, pi, po = perf(r, 365), perf(r[r.index < SPLIT_T], 365), perf(r[r.index >= SPLIT_T], 365)
        print(f"   {label:<34} CAGR {p['cagr']:+6.1%} Sharpe {p['sharpe']:4.2f} DD {p['dd']:6.1%} | IS {pi['cagr']:+6.1%} ({pi['sharpe']:.2f}) | OOS {po['cagr']:+6.1%} ({po['sharpe']:.2f}, DD {po['dd']:.1%})")
        return p

    bench = portfolio(pd.DataFrame(1.0, index=close.index, columns=close.columns), top=1.0)
    line("universo equiponderado (semanal)", bench)
    line("BTC comprar y mantener", R["BTC"].fillna(0.0)[R.index >= start])
    for name, sc in factors.items():
        line(name, portfolio(sc))


def main():
    what = sys.argv[1:] or ["A", "A2", "B", "C"]
    if "A" in what:
        section_a()
        print()
    if "A2" in what:
        section_a2()
        print()
    if "B" in what:
        section_b()
        print()
    if "C" in what:
        section_c()


if __name__ == "__main__":
    main()

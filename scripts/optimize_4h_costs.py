"""(1) Filtro de machine learning walk-forward sobre la regla de 4 h (z>=6, mantener 1 vela); (2) palanca de costos sobre la regla diaria.

Uso: python -m scripts.optimize_4h_costs
"""
import warnings

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

from screener import crypto100
from screener.backtest import perf
from screener.events import build_events
from screener.news import fear_greed
from screener.risk import PROFILES
from scripts.optimize_bot import add_walkforward_ml, load_events, report, run
from scripts.study_trend_pullback import hold_portfolio

warnings.filterwarnings("ignore")
COST_C = 0.0015
F4 = ["btc_dd", "btc_ret6", "n_sig", "frac_down", "mkt_ret", "sig_rel", "vr1", "dist200", "pos60", "k", "z", "hour", "weekend", "fg", "liq"]


def features_4h():
    c4, q4 = crypto100.clean_universe(*crypto100.load("4h"))
    ev = build_events(c4)
    e = ev[(ev["dir"] == "down") & (ev["k"] >= 2) & (ev["z"] >= 4) & ev["next"].notna()].copy()
    idx = c4.index
    R = c4.pct_change()
    sigma = R.rolling(60).std()
    mats = {"sig_rel": sigma / sigma.rolling(500).median(), "vr1": q4 / q4.rolling(20).mean().shift(1), "dist200": c4 / c4.rolling(200).mean() - 1,
            "pos60": c4 / c4.rolling(60).max() - 1, "liq": q4.rolling(180).mean() * 6}
    btc = c4["BTC"]
    fg = fear_greed().reindex(idx.normalize()).values
    day = pd.DataFrame({"btc_dd": btc / btc.rolling(540).max() - 1, "btc_ret6": btc.pct_change(6), "mkt_ret": R.mean(axis=1),
                        "frac_down": (R < 0).sum(axis=1) / R.notna().sum(axis=1), "fg": fg}, index=idx)
    pos, col = idx.get_indexer(e["date"]), c4.columns.get_indexer(e["asset"])
    for k, m in mats.items():
        e[k] = m.values[pos, col]
    for k in day.columns:
        e[k] = day[k].values[pos]
    e["n_sig"] = e["date"].map(e.groupby("date").size()).values
    e["hour"] = e["date"].dt.hour
    e["weekend"] = (e["date"].dt.dayofweek >= 5).astype(float)
    e = e[e["liq"] >= 5e6]
    return c4, e.reset_index(drop=True)


def main():
    c4, e = features_4h()
    print(f"REGLA DE 4 h — eventos z>=4 con liquidez>=5M: {len(e)} | z>=6: {(e['z'] >= 6).sum()}")
    e["ml"] = np.nan
    for y in range(2021, e["date"].dt.year.max() + 1):
        y0 = pd.Timestamp(f"{y}-01-01")
        tr = e[e["date"] < y0 - pd.Timedelta(days=1)]
        te = e.index[(e["date"] >= y0) & (e["date"] < pd.Timestamp(f"{y + 1}-01-01"))]
        if len(tr) < 300 or len(te) == 0:
            continue
        m = HistGradientBoostingClassifier(max_depth=3, max_iter=100, learning_rate=0.05, l2_regularization=1.0, random_state=0)
        m.fit(tr[F4], (tr["next"] > 0).astype(int))
        e.loc[te, "ml"] = m.predict_proba(e.loc[te, F4])[:, 1]
    main6 = e[(e["z"] >= 6) & e["ml"].notna()]
    print(f"  ML walk-forward anual (2021-2026): {len(main6)} eventos z>=6 puntuados | AUC {roc_auc_score((main6['next'] > 0).astype(int), main6['ml']):.3f} | "
          f"neto mitad alta {(main6[main6['ml'] >= main6['ml'].median()]['next'].mean() - 0.003):+.2%} vs baja {(main6[main6['ml'] < main6['ml'].median()]['next'].mean() - 0.003):+.2%}")
    print("  Cartera 2021-2026 (peso máx 10%, mantener 1 vela, costo 0.15%/lado):")
    for lab, sel in (("z>=6 sin filtro (base)", main6), ("z>=6 y P(rebote)>=0.60", main6[main6["ml"] >= 0.60]), ("z>=6 y P(rebote)>=0.65", main6[main6["ml"] >= 0.65]),
                     ("z>=6 y P(rebote)>=0.70", main6[main6["ml"] >= 0.70]), ("z>=5 y P(rebote)>=0.70", e[(e["z"] >= 5) & (e["ml"] >= 0.70)])):
        d = hold_portfolio(sel, c4, COST_C, 1)
        d = d[d.index >= "2021-01-01"]
        p = perf(d, 365 * 6)
        x = perf(d.drop(d.nlargest(20).index), 365 * 6)
        print(f"   {lab:<28} n={len(sel):4} | CAGR {p['cagr']:+6.1%} Sharpe {p['sharpe']:4.2f} DD {p['dd']:6.1%} | sin 20 mejores velas {x['cagr']:+5.1%}")

    print("\nPALANCA DE COSTOS — regla diaria balanceado, con y sin ML (replay 2020-2026)")
    close, down = load_events()
    down = add_walkforward_ml(down)
    prof = PROFILES["balanceado"]
    for cost, lab in ((0.0015, "0.15%/lado (comisión 0.10% + slippage 0.05%)"), (0.0012, "0.12%/lado"), (0.0010, "0.10%/lado (ej. BNB 0.075% + slippage 0.025%)"), (0.00075, "0.075%/lado")):
        report(f"{lab}", *run(down, prof, cost=cost))
        report(f"   + ML filtro+tamaño", *run(down, prof, cost=cost, mode="mlboth", ml_min=0.60))


if __name__ == "__main__":
    main()

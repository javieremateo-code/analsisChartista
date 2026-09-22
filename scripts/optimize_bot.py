"""Campaña de mejora del rendimiento de la regla diaria (top-100, liquidez >= 5 M), con disciplina anti-sobreajuste.

Todas las variantes se pre-declaran aquí y se evalúan en el replay día a día (estadísticas trimestrales sin lookahead). Las que usan
machine learning se reentrenan cada trimestre SOLO con eventos anteriores. Criterio de adopción (fijado antes de ver resultados):
mejora del CAGR Y del Sharpe en 2022-2026, sin empeorar la caída máxima más de 1.5x y sin volverse más frágil (CAGR sin los 5 mejores días
no inferior al de la base).

Uso: python -m scripts.optimize_bot
"""
import warnings

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

from screener import crypto100
from screener.backtest import perf
from screener.events import build_events
from screener.ml_score import FEATS, compute_features
from screener.news import fear_greed
from screener.risk import PROFILES
from scripts.backtest_system import START, SPLIT_T, stats_before

warnings.filterwarnings("ignore")
COST_C = 0.0015


def load_events():
    close, qv = crypto100.clean_universe(*crypto100.load("1d"))
    ev = build_events(close)
    down = ev[(ev["dir"] == "down") & (ev["k"] >= 2) & ev["next"].notna()].copy()
    down = compute_features(close, qv, fear_greed(), down)  # misma implementación que usa el informe y el bot
    down = down[down["liq"] >= 5e6]
    return close, down.reset_index(drop=True)


def add_walkforward_ml(down, n_models=5):
    """Probabilidad de rebote por evento: conjunto de n_models modelos (bootstrap + semillas), reentrenado cada
    trimestre solo con eventos anteriores (z>=2). El conjunto de 5 es el adoptado en producción (screener/ml_score.py):
    mejora CAGR/Sharpe/DD frente a 1 solo modelo (ver research/2026-09-22-cuarta-campana.md)."""
    down = down.copy()
    down["ml"] = np.nan
    broad = down[down["z"] >= 2]
    for q in pd.date_range(START, down["date"].max(), freq="QS"):
        tr = broad[broad["date"] < q - pd.Timedelta(days=1)]
        te_idx = down.index[(down["date"] >= q) & (down["date"] < q + pd.offsets.QuarterBegin(startingMonth=1)) & (down["z"] >= 2)]
        if len(tr) < 300 or len(te_idx) == 0:
            continue
        rng = np.random.default_rng(0)
        preds = []
        for seed in range(n_models):
            boot = tr if seed == 0 else tr.iloc[rng.choice(len(tr), size=len(tr), replace=True)]
            m = HistGradientBoostingClassifier(max_depth=3, max_iter=100, learning_rate=0.05, l2_regularization=1.0, random_state=seed)
            m.fit(boot[FEATS], (boot["next"] > 0).astype(int))
            preds.append(m.predict_proba(down.loc[te_idx, FEATS])[:, 1])
        down.loc[te_idx, "ml"] = np.mean(preds, axis=0)
    return down


def run(down, prof, cost=COST_C, cap_thr=-0.25, mode="base", ml_min=0.0, max_w_boost=1.0, tier=None, pnl_col="next", extra=None, trades=None):
    """Replay como el del sistema, con variantes de filtro/tamaño. mode: base | mlfilter | mlsize | tier."""
    start, end = START, down["date"].max()
    days = pd.date_range(start, end, freq="D")
    by_date = {k: v for k, v in down[down["date"] >= start].groupby("date")}
    refresh = set(pd.date_range(start, end, freq="QS")) | {start}
    stats, equity, peak, halted_forever, prev_pnl = {}, 1.0, 1.0, False, 0.0
    daily, ntr = {}, 0
    for day in days:
        if day in refresh:
            stats = stats_before(down, day)
        equity *= 1 + prev_pnl
        peak = max(peak, equity)
        halted_forever = halted_forever or equity <= peak * 0.5
        halt = halted_forever or prev_pnl <= -prof.daily_loss_limit
        pnl = 0.0
        cand = by_date.get(day)
        if cand is not None and not halt:
            picks = []
            for r in cand.itertuples():
                s = stats.get(int(r.zb))
                if s is None or r.zb < prof.min_z or s["p_low"] < prof.min_p_low or s["n"] < prof.min_n or s["mean"] - 2 * cost <= 0:
                    continue
                strong = r.dd90 <= cap_thr
                if not strong and prof.weak_size_factor <= 0:
                    continue
                if mode in ("mlfilter", "mlboth") and pd.notna(r.ml) and r.ml < ml_min:
                    continue
                loss = max(-s["p5"], 1e-4)
                w = min(prof.max_w * (max_w_boost if mode == "tier" else 1.0), prof.risk_per_trade / loss) * (1.0 if strong else prof.weak_size_factor)
                if mode in ("mlsize", "mlboth") and pd.notna(r.ml):
                    w = min(prof.max_w * 1.4, w * float(np.clip(r.ml / 0.70, 0.6, 1.4)))
                if mode == "tier" and tier:
                    w = min(prof.max_w * max_w_boost, w * tier(r.z))
                if extra is not None:
                    skip, mult = extra(r)
                    if skip:
                        continue
                    w = min(prof.max_w * max(1.5, mult), w * mult)
                picks.append((s["mean"] / loss, w, r))
            picks.sort(key=lambda x: -x[0])
            picks = picks[:prof.max_positions]
            tot = sum(p[1] for p in picks)
            scale = min(1.0, prof.max_exposure / tot) if tot > 0 else 1.0
            for _, w, r in picks:
                net = (getattr(r, pnl_col) if pd.notna(getattr(r, pnl_col)) else r.next) - 2 * cost
                pnl += w * scale * net
                ntr += 1
                if trades is not None:
                    trades.append(dict(date=day, asset=r.asset, w=w * scale, net=net, ml=getattr(r, "ml", float("nan")), z=r.z))
        daily[day + pd.Timedelta(days=1)] = pnl
        prev_pnl = pnl
    return pd.Series(daily).sort_index(), ntr


def report(label, s, ntr, base=None):
    s = s[s.index >= START]
    p, po = perf(s, 365), perf(s[s.index >= SPLIT_T], 365)
    x5 = perf(s.drop(s.nlargest(5).index), 365)
    print(f"  {label:<44} CAGR {p['cagr']:+6.1%} Sharpe {p['sharpe']:4.2f} DD {p['dd']:6.1%} | 2022+ {po['cagr']:+6.1%} ({po['sharpe']:.2f}) | sin 5 mejores días {x5['cagr']:+5.1%} | ops {ntr}")
    return dict(cagr=p["cagr"], sharpe=p["sharpe"], dd=p["dd"], o_cagr=po["cagr"], o_sh=po["sharpe"], x5=x5["cagr"])


def main():
    close, down = load_events()
    print(f"Eventos (top-100, liquidez>=5M): {len(down)} | z>=3: {(down['z'] >= 3).sum()}")
    down = add_walkforward_ml(down)
    d3 = down[down["z"] >= 3]
    ok = d3["ml"].notna()
    from sklearn.metrics import roc_auc_score
    print(f"ML walk-forward: {ok.sum()} eventos z>=3 puntuados | AUC {roc_auc_score((d3.loc[ok, 'next'] > 0).astype(int), d3.loc[ok, 'ml']):.3f} | "
          f"neto medio mitad alta {(d3[ok & (d3['ml'] >= d3.loc[ok, 'ml'].median())]['next'].mean() - 2 * COST_C):+.2%} vs baja {(d3[ok & (d3['ml'] < d3.loc[ok, 'ml'].median())]['next'].mean() - 2 * COST_C):+.2%}")
    prof = PROFILES["balanceado"]
    print("\nPERFIL BALANCEADO (replay 2020-2026)")
    res = {"base": report("BASE", *run(down, prof))}
    for thr in (0.55, 0.60, 0.65):
        res[f"mlf{thr}"] = report(f"filtro ML: solo si P(rebote) >= {thr:.2f}", *run(down, prof, mode="mlfilter", ml_min=thr))
    res["mlsize"] = report("tamaño ∝ P(rebote) (x0.6..1.4, tope 14%)", *run(down, prof, mode="mlsize"))
    res["mlboth"] = report("filtro ML 0.60 + tamaño ∝ P", *run(down, prof, mode="mlboth", ml_min=0.60))
    tier = lambda z: 1.0 if z < 4 else (1.3 if z < 5 else 1.6)
    res["tier"] = report("tamaño por magnitud (z>=4 x1.3, z>=5 x1.6; tope 16%)", *run(down, prof, mode="tier", max_w_boost=1.6, tier=tier))
    print("\nCriterio de adopción: mejora CAGR y Sharpe en 2022+, DD <= 1.5x, sin peor 'sin 5 mejores días' que la base")
    b = res["base"]
    for k, r in res.items():
        if k == "base":
            continue
        good = r["o_cagr"] > b["o_cagr"] and r["o_sh"] > b["o_sh"] and r["dd"] >= b["dd"] * 1.5 and r["x5"] >= b["x5"]
        print(f"  {k:<10} -> {'ADOPTABLE' if good else 'no cumple'}")


if __name__ == "__main__":
    main()

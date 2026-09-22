"""¿Puede alguna variable mejorar la regla validada de cripto (comprar tras caída >=3σ de 2+ días)?

Batería pre-declarada de variables (sentimiento, régimen, amplitud de mercado, volumen, funding, volatilidad, posición):
  1) Tabla univariante (terciles calculados SOLO con 2017-2021): P(sube mañana) y retorno neto a 1 día por cubeta,
     dentro/fuera de muestra, con t por fecha y corrección por comparaciones múltiples.
  2) Modelo de machine learning entrenado en 2017-2021 y evaluado en 2022-2026 (AUC, retorno por cuartiles, importancia).
  3) Walk-forward: cada año se elige el filtro con datos ANTERIORES y se aplica al año siguiente; se compara contra la regla sin filtrar.
Se analiza el conjunto principal (z>=3) y uno más amplio (z>=2, con más casos) para ganar potencia estadística.

Uso: python -m scripts.study_crash_filters
"""
import warnings

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer

from screener.backtest import perf, portfolio
from screener.events import build_events
from screener.extra_data import load_funding, load_qvol
from screener.news import fear_greed
from screener.universe import ANN, COST, SPLIT, load_history

warnings.filterwarnings("ignore")
SPLIT_T = pd.Timestamp(SPLIT["crypto"])
COST_C = COST["crypto"]
MAJORS = {"BTC", "ETH", "BNB", "XRP", "ADA", "SOL", "DOGE", "TRX"}
FEATS = ["fg", "fg_chg7", "btc_bull", "btc_dd", "btc_ret3", "n_sig_day", "frac_down", "mkt_ret", "sig_rel", "vr1", "vr3",
         "fund3", "dist200", "pos30", "k", "z", "weekend", "major"]
NICE = {"fg": "Fear&Greed (nivel)", "fg_chg7": "Fear&Greed cambio 7d", "btc_bull": "BTC > SMA200", "btc_dd": "BTC vs máx. 90d",
        "btc_ret3": "BTC retorno 3d", "n_sig_day": "nº monedas en caída fuerte el mismo día", "frac_down": "% del mercado en rojo ese día",
        "mkt_ret": "retorno medio del mercado ese día", "sig_rel": "volatilidad relativa de la moneda", "vr1": "volumen último día / media 20d",
        "vr3": "volumen 3d / media 20d", "fund3": "funding medio 3d (perp)", "dist200": "distancia a SMA200 de la moneda",
        "pos30": "posición vs máx. 30d", "k": "días de racha", "z": "magnitud (σ)", "weekend": "fin de semana", "major": "moneda grande"}


def build_features(ev, close):
    idx = close.index
    R = close.pct_change()
    sigma = R.rolling(60).std()
    mats = {
        "sig_rel": sigma / sigma.rolling(250).median(),
        "dist200": close / close.rolling(200).mean() - 1,
        "pos30": close / close.rolling(30).max() - 1,
    }
    qv = load_qvol().reindex(idx)
    mats["vr1"] = qv / qv.rolling(20).mean().shift(1)
    mats["vr3"] = qv.rolling(3).mean() / qv.rolling(20).mean().shift(3)
    mats["fund3"] = load_funding().reindex(idx).rolling(3, min_periods=2).mean()
    btc = close["BTC"]
    day = pd.DataFrame({
        "btc_bull": (btc > btc.rolling(200).mean()).astype(float).where(btc.rolling(200).mean().notna()),
        "btc_dd": btc / btc.rolling(90).max() - 1, "btc_ret3": btc.pct_change(3),
        "mkt_ret": R.mean(axis=1), "frac_down": (R < 0).sum(axis=1) / R.notna().sum(axis=1)}, index=idx)
    fg = fear_greed().reindex(idx)
    day["fg"], day["fg_chg7"] = fg, fg - fg.shift(7)
    pos = idx.get_indexer(ev["date"])
    col = close.columns.get_indexer(ev["asset"])
    out = ev.copy()
    for k, m in mats.items():
        out[k] = m.values[pos, col]
    for k in day.columns:
        out[k] = day[k].values[pos]
    sig_day = ev[(ev["dir"] == "down") & (ev["k"] >= 2) & (ev["z"] >= 2)].groupby("date").size()
    out["n_sig_day"] = out["date"].map(sig_day).fillna(0).values
    out["weekend"] = (out["date"].dt.dayofweek >= 5).astype(float)
    out["major"] = out["asset"].isin(MAJORS).astype(float)
    out["net"] = out["next"] - 2 * COST_C
    return out


def bucket_masks(ref, tgt):
    """Cubetas por variable; los umbrales de terciles se calculan SOLO con `ref` (datos anteriores)."""
    masks = {}
    bins = [(-1, 25, "miedo extremo <25"), (25, 45, "miedo 25-45"), (45, 55, "neutral 45-55"), (55, 75, "codicia 55-75"), (75, 101, "codicia extrema >=75")]
    for lo, hi, lab in bins:
        masks[("fg", lab)] = ((tgt["fg"] >= lo) & (tgt["fg"] < hi)).values & tgt["fg"].notna().values
    for f in ("btc_bull", "weekend", "major"):
        ok = tgt[f].notna().values
        masks[(f, "sí")] = (tgt[f] == 1).values & ok
        masks[(f, "no")] = (tgt[f] == 0).values & ok
    for f in ("fg_chg7", "btc_dd", "btc_ret3", "n_sig_day", "frac_down", "mkt_ret", "sig_rel", "vr1", "vr3", "fund3", "dist200", "pos30", "k", "z"):
        r = ref[f].dropna()
        if len(r) < 60 or r.nunique() < 3:
            continue
        q1, q2 = r.quantile([1 / 3, 2 / 3]).values
        if q1 == q2:
            continue
        v, ok = tgt[f].values, tgt[f].notna().values
        masks[(f, f"bajo (<{q1:.3g})")] = ok & (v < q1)
        masks[(f, "medio")] = ok & (v >= q1) & (v < q2)
        masks[(f, f"alto (>={q2:.3g})")] = ok & (v >= q2)
    return masks


def tstat(sub, rest):
    a, b = sub.groupby("date")["net"].mean(), rest.groupby("date")["net"].mean()
    if len(a) < 8 or len(b) < 8:
        return np.nan
    return (a.mean() - b.mean()) / np.sqrt(a.var() / len(a) + b.var() / len(b))


def main():
    close, _ = load_history("crypto")
    last_ok = close.apply(lambda s: s.last_valid_index())
    close = close.loc[:, last_ok >= last_ok.max() - pd.Timedelta(days=15)]
    ev_all = build_events(close)
    dn = ev_all[(ev_all["dir"] == "down") & (ev_all["k"] >= 2) & ev_all["next"].notna()]
    broad = build_features(dn[dn["z"] >= 2], close)
    main_set = broad[broad["z"] >= 3]
    print(f"Conjunto principal (z>=3): {len(main_set)} eventos en {main_set['date'].nunique()} fechas | amplio (z>=2): {len(broad)} eventos en {broad['date'].nunique()} fechas")
    b_is, b_os = broad[broad["date"] < SPLIT_T], broad[broad["date"] >= SPLIT_T]
    print(f"Amplio IS/OOS: {len(b_is)}/{len(b_os)} | principal IS/OOS: {int((main_set['date'] < SPLIT_T).sum())}/{int((main_set['date'] >= SPLIT_T).sum())}")
    base_m, base_b = main_set["net"].mean(), broad["net"].mean()
    print(f"Retorno neto a 1 día de la regla SIN filtrar: principal {base_m:+.2%} (P sube {(main_set['next'] > 0).mean():.0%}) | amplio {base_b:+.2%} (P sube {(broad['next'] > 0).mean():.0%})")

    # ------------------------------------------------------------------ 1) univariante
    print("\n" + "=" * 128)
    print("1) UNIVARIANTE: retorno neto a 1 día por cubeta (terciles fijados con 2017-2021)   ★ = |t|>=2.5, n>=150 y mismo signo dentro y fuera de muestra")
    print("=" * 128)
    masks_b = bucket_masks(b_is, broad)
    masks_m = bucket_masks(b_is, main_set)
    rows = []
    for (f, lab), mb in masks_b.items():
        sub, rest = broad[mb], broad[~mb]
        if len(sub) < 40:
            continue
        mm = masks_m.get((f, lab))
        subm = main_set[mm] if mm is not None else main_set.iloc[0:0]
        si, so = sub[sub["date"] < SPLIT_T], sub[sub["date"] >= SPLIT_T]
        d_all = sub["net"].mean() - base_b
        d_is = si["net"].mean() - b_is["net"].mean() if len(si) >= 20 else np.nan
        d_os = so["net"].mean() - b_os["net"].mean() if len(so) >= 20 else np.nan
        t = tstat(sub, rest)
        star = len(sub) >= 150 and abs(t) >= 2.5 and np.sign(d_is) == np.sign(d_os) == np.sign(d_all) and len(so) >= 50
        rows.append(dict(f=f, lab=lab, n=len(sub), net=sub["net"].mean(), p=(sub["next"] > 0).mean(), t=t, dis=d_is, dos=d_os, nis=len(si), nos=len(so),
                         nm=len(subm), netm=subm["net"].mean() if len(subm) else np.nan, pm=(subm["next"] > 0).mean() if len(subm) else np.nan, star=star))
    tab = pd.DataFrame(rows)
    ntests = len(tab)
    print(f"Cubetas testeadas: {ntests} | esperables |t|>=2 por azar: ~{ntests * 0.05:.0f} | observadas: {(tab['t'].abs() >= 2).sum()} | |t|>=3.5 (Bonferroni≈): {(tab['t'].abs() >= 3.5).sum()} | marcadas ★: {int(tab['star'].sum())}")
    print(f"{'variable / cubeta':<64} | {'AMPLIO n':>8} {'net1d':>7} {'P':>4} {'t':>5} {'Δ IS':>7} {'Δ OOS':>7} | {'PRINC. n':>8} {'net1d':>7} {'P':>4}")
    for f in FEATS:
        for _, r in tab[tab["f"] == f].iterrows():
            print(f"{'  ' + NICE[f] + ' — ' + r['lab']:<64} | {r['n']:8} {r['net']:+7.2%} {r['p']:4.0%} {r['t']:5.1f} {r['dis']:+7.2%} {r['dos']:+7.2%} | {r['nm']:8} "
                  f"{(r['netm'] if r['nm'] else np.nan):+7.2%} {(r['pm'] if r['nm'] else np.nan):4.0%}{'  ★' if r['star'] else ''}")

    # ------------------------------------------------------------------ 2) machine learning
    print("\n" + "=" * 128)
    print("2) MACHINE LEARNING: entrenado con 2017-2021, evaluado en 2022-2026 (objetivo: ¿sube al día siguiente?)")
    print("=" * 128)
    X_is, X_os = b_is[FEATS], b_os[FEATS]
    y_is, y_os = (b_is["next"] > 0).astype(int), (b_os["next"] > 0).astype(int)
    models = {
        "solo z y k (referencia)": (HistGradientBoostingClassifier(max_depth=2, max_iter=60, learning_rate=0.05, random_state=0), ["z", "k"]),
        "todas las variables (boosting)": (HistGradientBoostingClassifier(max_depth=3, max_iter=150, learning_rate=0.05, l2_regularization=1.0, random_state=0), FEATS),
        "todas las variables (logística)": (make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), LogisticRegression(C=0.3, max_iter=500)), FEATS),
    }
    fitted = {}
    for name, (mdl, cols) in models.items():
        mdl.fit(X_is[cols], y_is)
        p = mdl.predict_proba(X_os[cols])[:, 1]
        auc = roc_auc_score(y_os, p)
        pm = pd.Series(p, index=b_os.index)
        top = b_os.loc[pm >= pm.quantile(0.5), "net"].mean()
        bot = b_os.loc[pm < pm.quantile(0.5), "net"].mean()
        topq = b_os.loc[pm >= pm.quantile(0.75), "net"].mean()
        print(f"  {name:<34} AUC OOS {auc:.3f} | retorno neto 1d OOS: mitad alta {top:+.2%} | mitad baja {bot:+.2%} | cuartil alto {topq:+.2%} | todo {b_os['net'].mean():+.2%}")
        fitted[name] = (mdl, cols)
    mdl, cols = fitted["todas las variables (boosting)"]
    imp = permutation_importance(mdl, X_os[cols], y_os, scoring="roc_auc", n_repeats=15, random_state=0)
    order = np.argsort(-imp.importances_mean)[:8]
    print("  Importancia (caída de AUC OOS al barajar la variable): " + " | ".join(f"{NICE[cols[i]]}: {imp.importances_mean[i]:+.3f}" for i in order))

    # ------------------------------------------------------------------ 3) walk-forward de filtros
    print("\n" + "=" * 128)
    print("3) WALK-FORWARD: cada año se elige el mejor filtro con los años ANTERIORES (por t en el conjunto amplio) y se aplica a la regla principal")
    print("=" * 128)
    sel_idx, base_idx, log = [], [], []
    tot_f, tot_b = [], []
    for y in range(2021, 2027):
        y0 = pd.Timestamp(f"{y}-01-01")
        tr, te = broad[broad["date"] < y0], main_set[(main_set["date"] >= y0) & (main_set["date"] < pd.Timestamp(f"{y + 1}-01-01"))]
        if len(tr) < 250 or len(te) == 0:
            continue
        mtr, mte = bucket_masks(tr, tr), bucket_masks(tr, te)
        best, bt = None, -9
        for key, m in mtr.items():
            if m.sum() < 80:
                continue
            t = tstat(tr[m], tr[~m])
            if np.isfinite(t) and t > bt and tr[m]["net"].mean() > tr["net"].mean():
                best, bt = key, t
        if best is None:
            continue
        chosen = te[mte[best]]
        base_idx += list(te.index)
        sel_idx += list(chosen.index)
        log.append(f"{y}: {NICE[best[0]]} — {best[1]} (t_train={bt:.1f}) -> {len(chosen)}/{len(te)} eventos, neto {chosen['net'].mean() if len(chosen) else float('nan'):+.2%} vs sin filtro {te['net'].mean():+.2%}")
    print("\n".join("  " + l for l in log))
    fb, ff = main_set.loc[base_idx], main_set.loc[sel_idx]
    print(f"\n  TOTAL 2021-2026: sin filtro n={len(fb)} neto {fb['net'].mean():+.2%} P(sube) {(fb['next'] > 0).mean():.0%} | con filtro elegido cada año n={len(ff)} neto {ff['net'].mean():+.2%} P(sube) {(ff['next'] > 0).mean():.0%}")
    ev_idx = close.index
    for lab, sel in (("regla base (sin filtro)", ev_all.loc[fb.index]), ("regla con filtro walk-forward", ev_all.loc[ff.index])):
        d, e, tr = portfolio(sel, ev_idx, COST_C, dirs=("down",), kmin=2, zmin=3.0)
        d = d[d.index >= pd.Timestamp("2021-01-01")]
        p = perf(d, ANN["crypto"])
        print(f"  Cartera {lab:<32}: CAGR {p['cagr']:+6.1%} | Sharpe {p['sharpe']:5.2f} | maxDD {p['dd']:6.1%} | operaciones {len(tr)} | invertido {(e[e.index >= pd.Timestamp('2021-01-01')] > 0).mean():.0%}")

    # ------------------------------------------------------------------ 4) filtros marcados ★ elegidos solo con IS
    print("\n" + "=" * 128)
    print("4) FILTROS ★ (univariante) -> cartera fuera de muestra (2022-2026) sobre la regla principal")
    print("=" * 128)
    stars = tab[tab["star"]]
    if stars.empty:
        print("  Ninguna cubeta pasó el filtro ★.")
    for _, r in stars.iterrows():
        m = masks_m.get((r["f"], r["lab"]))
        if m is None:
            continue
        subm = main_set[m]
        so, base_o = subm[subm["date"] >= SPLIT_T], main_set[main_set["date"] >= SPLIT_T]
        if len(so) < 15:
            print(f"  {NICE[r['f']]} — {r['lab']}: pocos casos OOS en la regla principal ({len(so)})")
            continue
        d, e, tr = portfolio(ev_all.loc[so.index], close.index, COST_C, dirs=("down",), kmin=2, zmin=3.0)
        d0, e0, tr0 = portfolio(ev_all.loc[base_o.index], close.index, COST_C, dirs=("down",), kmin=2, zmin=3.0)
        p, p0 = perf(d[d.index >= SPLIT_T], ANN["crypto"]), perf(d0[d0.index >= SPLIT_T], ANN["crypto"])
        print(f"  {NICE[r['f']]} — {r['lab']}: OOS n={len(so)} neto {so['net'].mean():+.2%} P {(so['next'] > 0).mean():.0%} | cartera CAGR {p['cagr']:+.1%} Sharpe {p['sharpe']:.2f} DD {p['dd']:.0%}  "
              f"[sin filtro OOS: n={len(base_o)} neto {base_o['net'].mean():+.2%}, CAGR {p0['cagr']:+.1%} Sharpe {p0['sharpe']:.2f} DD {p0['dd']:.0%}]")


if __name__ == "__main__":
    main()

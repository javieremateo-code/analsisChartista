"""Cuarta campaña: ¿mantener más de 24h captura más rebote?, ¿el riesgo por operación ignora la correlación entre
monedas que caen el mismo día de pánico?, ¿un conjunto de modelos da una señal más estable que uno solo?

F1) Barrido de tiempo de mantenimiento (1, 2, 3, 5 días) para la regla diaria, mismo criterio de adopción de siempre.
F2) Correlación real entre los retornos del día siguiente de las monedas que caen el mismo día (¿la diversificación
    entre posiciones simultáneas es real o es un espejismo por tratarlas como independientes al dimensionar?).
F3) Conjunto de 5 modelos (semillas distintas) en vez de uno solo: ¿AUC más estable entre trimestres? ¿mejora el Sharpe?

Uso: python -m scripts.optimize_hold_risk [F1|F2|F3]
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
from screener.ml_score import FEATS
from screener.risk import PROFILES
from scripts.backtest_system import START, SPLIT_T, stats_before
from scripts.optimize_bot import add_walkforward_ml, load_events, report, run

warnings.filterwarnings("ignore")
COST_C = 0.0015


def multiday_events(close, down, horizons=(1, 2, 3, 5)):
    """Añade columnas next_h = retorno del cierre al cierre h días después (para cada evento existente)."""
    idx = close.index
    pos = idx.get_indexer(down["date"])
    for h in horizons:
        fwd = pd.DataFrame({c: close[c].shift(-h) / close[c] - 1 for c in close.columns})
        col = close.columns.get_indexer(down["asset"])
        valid = (pos >= 0) & (pos + h < len(idx))
        vals = np.full(len(down), np.nan)
        vals[valid] = fwd.values[pos[valid], col[valid]]
        down[f"next_h{h}"] = vals
    return down


def run_multiday(down, prof, h, cost=COST_C, mode="mlboth", ml_min=0.60):
    """Como run() pero la salida se produce h días después (una sola pata abierta por moneda a la vez no se impone;
    se asume que se puede tener una posición nueva mientras otra de h días sigue abierta, igual que en la práctica
    con varias monedas). El coste se paga una sola vez (entrada+salida), igual que en el resto del proyecto."""
    col = f"next_h{h}"
    down2 = down.copy()
    down2["net_h"] = down2[col] - 2 * cost
    s, ntr = run(down2, prof, cost=cost, mode=mode, ml_min=ml_min, pnl_col=col)
    return s, ntr


def f1():
    close, down = load_events()
    down = multiday_events(close, down)
    down = add_walkforward_ml(down)
    print("F1) TIEMPO DE MANTENIMIENTO — perfil balanceado, con modelo (filtro 0.60 + tamaño), replay 2020-2026")
    print("    (el retorno de mantener h días se anualiza igual que antes: no se descuenta el capital 'atado' más tiempo)")
    res = {}
    for h in (1, 2, 3, 5):
        col = f"next_h{h}" if h > 1 else "next"
        d2 = down.copy()
        if h > 1:
            d2["pnl_tmp"] = d2[col]
        s, n = run(d2, PROFILES["balanceado"], mode="mlboth", ml_min=0.60, pnl_col=(col if h > 1 else "next"))
        res[h] = report(f"mantener {h} día(s)", s, n)
    b = res[1]
    print("    Criterio: mejora CAGR y Sharpe 2022+, DD <= 1.5x, 'sin 5 mejores' no inferior")
    for h in (2, 3, 5):
        r = res[h]
        ok = r["o_cagr"] > b["o_cagr"] and r["o_sh"] > b["o_sh"] and r["dd"] >= b["dd"] * 1.5 and r["x5"] >= b["x5"]
        print(f"      {h}d -> {'ADOPTABLE' if ok else 'no cumple'}")
    # variante: elegir el mejor de {1,2,3,5} según el retorno esperado de CADA evento (no fijo)
    print("\n    Salida adaptativa: para cada evento se usa el horizonte con mayor retorno esperado según z (elegido con datos <2022)")
    tr_mask = down["date"] < SPLIT_T
    best_h_by_z = {}
    for zb in sorted(down.loc[down["z"] >= 3, "zb"].unique()):
        means = {h: down.loc[tr_mask & (down["zb"] == zb), f"next_h{h}" if h > 1 else "next"].mean() for h in (1, 2, 3, 5)}
        best_h_by_z[zb] = max(means, key=means.get)
    down["best_h"] = down["zb"].map(best_h_by_z).fillna(1)
    down["net_adapt"] = down.apply(lambda r: r["next"] if r["best_h"] == 1 else r[f"next_h{int(r['best_h'])}"], axis=1)
    s, n = run(down, PROFILES["balanceado"], mode="mlboth", ml_min=0.60, pnl_col="net_adapt")
    r = report("horizonte adaptativo por magnitud (elegido con <2022)", s, n)
    ok = r["o_cagr"] > b["o_cagr"] and r["o_sh"] > b["o_sh"] and r["dd"] >= b["dd"] * 1.5 and r["x5"] >= b["x5"]
    print(f"      -> {'ADOPTABLE' if ok else 'no cumple'} | horizontes elegidos: {best_h_by_z}")


def f2():
    close, down = load_events()
    print("F2) CORRELACIÓN ENTRE POSICIONES SIMULTÁNEAS (mismo día de señal, z>=3)")
    d3 = down[(down["z"] >= 3) & down["next"].notna()].copy()
    by_day = d3.groupby("date")
    multi = [g for _, g in by_day if len(g) >= 2]
    print(f"    Días con >=2 señales simultáneas (z>=3): {len(multi)} de {d3['date'].nunique()} días con señal")
    # correlación media par a par de los retornos 'next' entre monedas del mismo día
    corrs = []
    for g in multi:
        r = g.set_index("asset")["next"]
        if len(r) >= 2:
            # signo conjunto: ¿se mueven juntas? proxy simple = 1 si incluso 2 valores están a igual lado de la mediana del día
            pass
    # medida directa: para cada par de eventos del mismo día, ¿tienen next con el mismo signo?
    same_sign, total = 0, 0
    rets_by_day = []
    for g in multi:
        r = g["next"].values
        rets_by_day.append(r)
        for i in range(len(r)):
            for j in range(i + 1, len(r)):
                total += 1
                same_sign += int(np.sign(r[i]) == np.sign(r[j]))
    print(f"    Pares de monedas el mismo día con el mismo signo de retorno al día siguiente: {same_sign}/{total} = {same_sign / total:.0%} (azar = 50%)")
    # dispersión intra-día vs entre-días: si estuvieran correlacionadas, la desviación típica del retorno MEDIO diario
    # sería mayor de lo que predice 1/sqrt(n) asumiendo independencia
    day_means = np.array([r.mean() for r in rets_by_day])
    day_ns = np.array([len(r) for r in rets_by_day])
    all_r = d3["next"].values
    sigma_indiv = all_r.std()
    predicted_sigma_of_mean = sigma_indiv / np.sqrt(day_ns.mean())
    actual_sigma_of_mean = day_means.std()
    print(f"    Sigma de un evento individual: {sigma_indiv:.1%} | sigma del retorno medio diario si fueran independientes: {predicted_sigma_of_mean:.1%} | sigma real del retorno medio diario: {actual_sigma_of_mean:.1%}")
    infl = (actual_sigma_of_mean / predicted_sigma_of_mean) ** 2
    print(f"    -> el riesgo real de un día con varias señales es ~{infl:.1f}x el que asumiría el dimensionado por posición independiente")
    print("    Corrección propuesta: escalar el tamaño de cada posición por 1/sqrt(inflación) cuando hay N>=2 señales el mismo día, para igualar el riesgo de un día 'multi' al de un día con 1 sola señal.")

    prof = PROFILES["balanceado"]
    down2 = down.copy()
    down2 = add_walkforward_ml(down2)
    base_s, base_n = run(down2, prof, mode="mlboth", ml_min=0.60)
    # variante: penalizar el tamaño según el nº de señales simultáneas ese día (1/sqrt(n))
    extra = lambda r: (False, 1.0 / np.sqrt(max(1, r.n_sig_day)) ** 0.5)  # atenuación suave (raíz de raíz) para no sobre-corregir
    s2, n2 = run(down2, prof, mode="mlboth", ml_min=0.60, extra=extra)
    print("\n    Cartera con y sin la corrección de tamaño por señales simultáneas:")
    b = report("sin corrección (actual)", base_s, base_n)
    r = report("con corrección (atenúa el tamaño en días con muchas señales)", s2, n2)
    ok = r["o_cagr"] > b["o_cagr"] and r["o_sh"] > b["o_sh"] and r["dd"] >= b["dd"] * 1.5 and r["x5"] >= b["x5"]
    print(f"    -> {'ADOPTABLE' if ok else 'no cumple (comparar sobre todo el Sharpe y la caída, no solo el CAGR)'}")


def f3():
    close, down = load_events()
    print("F3) CONJUNTO DE MODELOS (5 semillas) frente a un solo modelo — walk-forward trimestral, perfil balanceado")
    broad = down[down["z"] >= 2]
    single = pd.Series(np.nan, index=down.index)
    ensemble = pd.Series(np.nan, index=down.index)
    quarters = pd.date_range(START, down["date"].max(), freq="QS")
    auc_single, auc_ens = [], []
    for q in quarters:
        tr = broad[broad["date"] < q - pd.Timedelta(days=1)]
        te = down.index[(down["date"] >= q) & (down["date"] < q + pd.offsets.QuarterBegin(startingMonth=1)) & (down["z"] >= 2)]
        if len(tr) < 300 or len(te) == 0:
            continue
        preds = []
        rng = np.random.default_rng(0)
        for seed in range(5):
            boot = tr if seed == 0 else tr.iloc[rng.choice(len(tr), size=len(tr), replace=True)]
            m = HistGradientBoostingClassifier(max_depth=3, max_iter=100, learning_rate=0.05, l2_regularization=1.0, random_state=seed)
            m.fit(boot[FEATS], (boot["next"] > 0).astype(int))
            preds.append(m.predict_proba(down.loc[te, FEATS])[:, 1])
        preds = np.array(preds)
        single.loc[te] = preds[0]
        ensemble.loc[te] = preds.mean(axis=0)
        yq = down.loc[te]
        if (yq["next"] > 0).nunique() == 2:
            auc_single.append(roc_auc_score((yq["next"] > 0).astype(int), preds[0]))
            auc_ens.append(roc_auc_score((yq["next"] > 0).astype(int), preds.mean(axis=0)))
    print(f"    AUC medio por trimestre: 1 modelo {np.mean(auc_single):.3f} (desv. {np.std(auc_single):.3f}) | ensemble 5 {np.mean(auc_ens):.3f} (desv. {np.std(auc_ens):.3f})")
    prof = PROFILES["balanceado"]
    d1, d2 = down.copy(), down.copy()
    d1["ml"], d2["ml"] = single, ensemble
    s1, n1 = run(d1, prof, mode="mlboth", ml_min=0.60)
    s2, n2 = run(d2, prof, mode="mlboth", ml_min=0.60)
    b = report("1 modelo (actual)", s1, n1)
    r = report("ensemble de 5 modelos", s2, n2)
    ok = r["o_cagr"] > b["o_cagr"] and r["o_sh"] > b["o_sh"] and r["dd"] >= b["dd"] * 1.5 and r["x5"] >= b["x5"]
    print(f"    -> {'ADOPTABLE' if ok else 'no cumple'}")


def main():
    what = sys.argv[1:] or ["F1", "F2", "F3"]
    for w, fn in (("F1", f1), ("F2", f2), ("F3", f3)):
        if w in what:
            fn()
            print()


if __name__ == "__main__":
    main()

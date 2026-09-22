"""Pregunta 2: ¿el movimiento de un futuro de commodity anticipa el de las acciones relacionadas en los días siguientes?
(petróleo -> petroleras/refinadoras/servicios/aerolíneas, oro -> mineras/joyerías, plata, cobre, gas, grano, cacao, café, algodón...)

Para cada par (futuro, cesta de acciones, signo esperado):
  - Retorno ANÓMALO de la cesta e_t = r_cesta - beta_rolling * r_mercado (SPY), con beta de los 250 días anteriores.
  - (a) Relación contemporánea: e_t sobre el retorno del futuro (comprueba que el par tiene sentido económico).
  - (b) Predicción: e_{t+1} (y acumulado 3 y 5 días) sobre r_futuro_t, controlando por e_t y r_mercado_t (errores HAC Newey-West).
  - (c) Reacción OPERABLE: apertura->cierre del día siguiente (se entra a la apertura tras ver el cierre del futuro).
  - (d) Estudio de eventos: días con movimiento extremo del futuro (|z|>=2) y estados de racha fuerte (z>=3): retorno anómalo posterior.
  - (e) "Catch-up": si la cesta se movió MENOS de lo que su relación histórica implicaba, ¿se pone al día después?
Corte IS/OOS 2013. Advertencia de horario: el cierre del futuro puede incluir minutos posteriores al cierre de las acciones.

Uso: python -m scripts.study_commodity_stocks
"""
import warnings

import numpy as np
import pandas as pd

from screener.events import build_events
from screener.futures import BASKETS, FUTURES, load_futures, load_stocks, load_stocks_open

warnings.filterwarnings("ignore")
SPLIT = pd.Timestamp("2013-01-01")


def nw_ols(y, X, lags):
    """MCO con errores Newey-West. Devuelve beta y t (la constante es la primera columna)."""
    m = np.isfinite(y) & np.isfinite(X).all(axis=1)
    y, X = y[m], X[m]
    n, k = X.shape
    if n < 100:
        return np.full(k, np.nan), np.full(k, np.nan), n
    XtXi = np.linalg.inv(X.T @ X)
    b = XtXi @ X.T @ y
    u = y - X @ b
    S = (X * u[:, None]).T @ (X * u[:, None])
    for L in range(1, lags + 1):
        w = 1 - L / (lags + 1)
        G = (X[L:] * u[L:, None]).T @ (X[:-L] * u[:-L, None])
        S += w * (G + G.T)
    V = XtXi @ S @ XtXi
    return b, b / np.sqrt(np.diag(V)), n


def main():
    fut = load_futures()
    tickers = sorted({t for b in BASKETS for t in b[3]} | {"SPY"})
    close = load_stocks(tickers)
    opn = load_stocks_open(tickers)
    spy_c, spy_o = close["SPY"], opn["SPY"]
    rm = spy_c.pct_change()
    rm_oc = spy_c / spy_o - 1
    rows = []
    print(f"{'futuro → cesta':<44} {'signo':>5} | {'contemp.':>13} | {'próx.día c-c':>13} | {'próx.día apert→cierre':>19} | {'3d acum':>8} | {'5d acum':>8} | t IS / OOS (próx.día c-c)")
    for (f, bname, sign, tks) in BASKETS:
        if f not in fut.columns:
            continue
        have = [t for t in tks if t in close.columns]
        if len(have) < 2:
            continue
        idx = close.index.intersection(fut.index)
        rf = fut[f].reindex(idx).pct_change()
        rb = close[have].reindex(idx).pct_change().where(close[have].reindex(idx).notna().sum(axis=1) >= 2).mean(axis=1)
        rb_oc = (close[have].reindex(idx) / opn[have].reindex(idx) - 1).mean(axis=1)
        m = rm.reindex(idx)
        cov = rb.rolling(250).cov(m).shift(1)
        var = m.rolling(250).var().shift(1)
        beta = (cov / var).clip(-1, 3)
        e = rb - beta * m
        e_oc = rb_oc - beta * rm_oc.reindex(idx)
        sig_f = rf.rolling(60).std().shift(1)
        zf = rf / sig_f
        d = pd.DataFrame({"rf": rf, "zf": zf, "e": e, "m": m, "e1": e.shift(-1), "eoc1": e_oc.shift(-1),
                          "e3": e.rolling(3).sum().shift(-3), "e5": e.rolling(5).sum().shift(-5)}).dropna(subset=["rf", "e", "m"])
        d["const"] = 1.0

        def reg(ycol, lags, sub=d):
            X = sub[["const", "rf", "e", "m"]].values
            b, t, n = nw_ols(sub[ycol].values, X, lags)
            return b[1], t[1], n

        # contemporánea
        Xc = d[["const", "rf"]].values
        bc, tc, nc = nw_ols(d["e"].values, Xc, 5)
        r2 = np.corrcoef(d["rf"], d["e"])[0, 1] ** 2
        b1, t1, n1 = reg("e1", 5)
        bo, to, no = reg("eoc1", 5)
        b3, t3, _ = reg("e3", 7)
        b5, t5, _ = reg("e5", 9)
        _, tis, _ = reg("e1", 5, d[d.index < SPLIT])
        _, tos, _ = reg("e1", 5, d[d.index >= SPLIT])
        label = f"{FUTURES[f]} → {bname}"
        print(f"{label:<44} {sign:+5d} | β {bc[1]:+.2f} R²{r2:4.0%} | β {b1 * 100:+.3f} t{t1:+5.1f} | β {bo * 100:+.3f} t{to:+5.1f}      | t{t3:+5.1f}   | t{t5:+5.1f}   | {tis:+5.1f} / {tos:+5.1f}")
        rows.append(dict(label=label, sign=sign, t1=t1, to=to, t3=t3, t5=t5, tis=tis, tos=tos, f=f, bname=bname, d=d))

    ntests = len(rows) * 3
    tvals = np.array([[r["t1"], r["to"], r["t3"]] for r in rows]).ravel()
    print(f"\nPredicciones testeadas: {ntests} (por par: día siguiente c-c, apertura→cierre, 3 días) | |t|>=2: {(np.abs(tvals) >= 2).sum()} (por azar ~{ntests * 0.05:.0f}) | |t|>=3: {(np.abs(tvals) >= 3).sum()}")
    same_sign = [(r["label"], r["t1"]) for r in rows if np.sign(r["tis"]) == np.sign(r["tos"]) and abs(r["t1"]) >= 2]
    print("Pares con |t|>=2 en el día siguiente y mismo signo en IS y OOS: " + (", ".join(f"{a} (t={b:+.1f})" for a, b in same_sign) or "ninguno"))

    # ---------------- estudio de eventos ----------------
    print("\n" + "=" * 130)
    print("ESTUDIO DE EVENTOS: retorno anómalo de la cesta tras un movimiento extremo del futuro (en la dirección esperada: + = la cesta sigue al futuro)")
    print("=" * 130)
    print(f"{'futuro → cesta':<44} | {'día extremo |z|>=2':>34} | {'racha fuerte del futuro (z>=3, k>=2)':>44}")
    for r in rows:
        d, sign = r["d"], r["sign"]
        big = d[d["zf"].abs() >= 2].dropna(subset=["e1"])
        s = np.sign(big["zf"]) * sign
        v1, v3, v5 = (s * big["e1"]), (s * big["e3"]), (s * big["e5"])
        eo = (s * big["eoc1"]).dropna()
        ev = build_events(fut[[r["f"]]])
        strong = ev[(ev["k"] >= 2) & (ev["z"] >= 3)]
        sd = strong.set_index("date")
        sd = sd[~sd.index.duplicated()]
        common = d.index.intersection(sd.index)
        sgn = np.where(sd.loc[common, "dir"] == "up", 1, -1) * sign
        vs = pd.Series(sgn, index=common) * d.loc[common, "e1"]
        t = lambda x: x.mean() / (x.std() / np.sqrt(len(x))) if len(x) > 20 and x.std() > 0 else np.nan
        print(f"{r['label']:<44} | n={len(big):4} 1d {v1.mean():+.3%} (t{t(v1):+4.1f}) 5d {v5.mean():+.2%} (t{t(v5):+4.1f}) ap→cierre {eo.mean():+.3%} | n={vs.notna().sum():4} 1d {vs.mean():+.3%} (t{t(vs.dropna()):+4.1f})")

    # ---------------- catch-up ----------------
    print("\n" + "=" * 130)
    print("CATCH-UP: si la cesta se movió MENOS de lo que su relación histórica con el futuro implicaba, ¿se pone al día al día siguiente?")
    print("=" * 130)
    for r in rows:
        d = r["d"].copy()
        train = d[d.index < SPLIT]
        bc = np.polyfit(train["rf"].dropna(), train.loc[train["rf"].notna(), "e"], 1)[0] if len(train) > 200 else np.nan
        d["gap"] = bc * d["rf"] - d["e"]
        big = d[(d["zf"].abs() >= 1.5) & d["e1"].notna()]
        if len(big) < 80:
            continue
        b, t, n = nw_ols(big["e1"].values, np.column_stack([np.ones(len(big)), big["gap"].values]), 5)
        top = big[big["gap"].abs() >= big["gap"].abs().quantile(0.75)]
        aligned = np.sign(top["gap"]) * top["e1"]
        print(f"{r['label']:<44} | coef. gap→retorno día siguiente {b[1]:+.3f} (t{t[1]:+4.1f}, n={n}) | cuartil de mayor desfase: retorno a favor del ajuste {aligned.mean():+.3%} (n={len(top)})")


if __name__ == "__main__":
    main()

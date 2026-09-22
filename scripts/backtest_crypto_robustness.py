"""Pruebas de robustez de la estrategia de rebote tras caídas fuertes (45 criptos, diario UTC).

Estrategia base: racha >=2 días de caída y caída acumulada >= 25%; compra al cierre, vende al
cierre siguiente; peso min(10%, 1/n); costo 0.15%/lado.

Pruebas: (1) contra entradas aleatorias, (2) walk-forward con selección anual del umbral,
(3) estrés de costos/tamaño, (4) Monte Carlo a 1 año con 1000 EUR, (5) régimen y concentración.

Uso:  python -m scripts.backtest_crypto_robustness
"""
import warnings

import numpy as np
import pandas as pd

import scripts.backtest_sp500_crash_rebound as sp
from scripts.backtest_crypto_crash_rebound import SPLIT, load
from scripts.backtest_crypto_extended import load_new

warnings.filterwarnings("ignore")
THR, KMIN, COST, ANN = 0.25, 2, 0.0015, 365
rng = np.random.default_rng(7)


def cagr_of(d):
    yrs = (d.index[-1] - d.index[0]).days / 365.25
    return (1 + d).prod() ** (1 / yrs) - 1


def sharpe_of(d):
    return d.mean() / d.std() * np.sqrt(ANN) if d.std() > 0 else np.nan


def maxdd_of(d):
    eq = (1 + d).cumprod()
    return (eq / eq.cummax() - 1).min()


def main():
    c0, o0 = load()
    c1, o1 = load_new()
    close = pd.concat([c0, c1], axis=1).sort_index()
    open_ = pd.concat([o0, o1], axis=1).sort_index()
    T, N = close.shape
    sig = sp.signal_matrix(close, THR, KMIN)
    daily, expo, tr = sp.run(close, open_, sig, COST, "close")
    print(f"BASE: racha>={KMIN}, caída>={THR:.0%}, costo {COST:.2%}/lado | CAGR {cagr_of(daily):+.1%} | Sharpe {sharpe_of(daily):.2f} | "
          f"maxDD {maxdd_of(daily):.1%} | trades {len(tr)} | neto/trade {tr.mean():+.2%}")

    # ---------- (1) prueba contra azar ----------
    print("\n=== (1) Contra entradas aleatorias (2000 simulaciones; mismo nº de posiciones por día y mismo tamaño) ===")
    net = ((close.shift(-1) / close - 1) - 2 * COST).values
    avail = ~np.isnan(net)
    sigv = sig.values
    days = np.where(sigv.any(axis=1) & avail.any(axis=1))[0]
    ns = {t: int((sigv[t] & avail[t]).sum()) for t in days}
    actual_daily = np.zeros(T)
    for t in days:
        n = ns[t]
        actual_daily[t] = np.nansum(net[t][sigv[t]]) * min(sp.MAX_W, 1 / n)
    yrs = (close.index[-1] - close.index[0]).days / 365.25
    cg = lambda arr: np.prod(1 + arr) ** (1 / yrs) - 1
    actual_cagr = cg(actual_daily)
    avail_n = avail.sum(axis=1)
    null1, null2 = [], []
    days_list = list(days)
    for _ in range(2000):
        # null1: mismos días de señal, monedas aleatorias entre las disponibles
        a = np.zeros(T)
        for t in days_list:
            n = ns[t]
            pick = rng.choice(np.where(avail[t])[0], size=n, replace=False)
            a[t] = net[t][pick].sum() * min(sp.MAX_W, 1 / n)
        null1.append(cg(a))
        # null2: días aleatorios (con suficientes monedas) y monedas aleatorias
        b = np.zeros(T)
        pool = rng.permutation(np.where(avail_n >= 1)[0])
        used = set()
        for t in days_list:
            n = ns[t]
            for cand in pool:
                if cand not in used and avail_n[cand] >= n:
                    used.add(cand)
                    pick = rng.choice(np.where(avail[cand])[0], size=n, replace=False)
                    b[cand] = net[cand][pick].sum() * min(sp.MAX_W, 1 / n)
                    break
        null2.append(cg(b))
    null1, null2 = np.array(null1), np.array(null2)
    print(f"Real: CAGR {actual_cagr:+.1%}")
    print(f"Null 1 (mismos días, monedas al azar):   media {null1.mean():+.1%} | p95 {np.percentile(null1,95):+.1%} | p-valor (real>=azar) {(null1>=actual_cagr).mean():.3f}")
    print(f"Null 2 (días y monedas al azar):         media {null2.mean():+.1%} | p95 {np.percentile(null2,95):+.1%} | p-valor {(null2>=actual_cagr).mean():.3f}")

    # ---------- (2) walk-forward con selección anual ----------
    print("\n=== (2) Walk-forward: cada año se elige el umbral (15/20/25/30%) con el mejor Sharpe de los años ANTERIORES ===")
    cfgs = {}
    for thr in (0.15, 0.20, 0.25, 0.30):
        d, _, _ = sp.run(close, open_, sp.signal_matrix(close, thr, KMIN), COST, "close")
        cfgs[thr] = d
    parts, chosen = [], []
    for y in range(2020, close.index[-1].year + 1):
        prior = {k: v[v.index < f"{y}-01-01"] for k, v in cfgs.items()}
        best = max(prior, key=lambda k: sharpe_of(prior[k]) if prior[k].std() > 0 else -9)
        chosen.append(f"{y}:{best:.0%}")
        parts.append(cfgs[best][cfgs[best].index.year == y])
    wf = pd.concat(parts)
    btc = close["BTC"].pct_change().fillna(0).reindex(wf.index)
    print("Umbral elegido cada año: " + ", ".join(chosen))
    print(f"Walk-forward 2020-2026: CAGR {cagr_of(wf):+.1%} | Sharpe {sharpe_of(wf):.2f} | maxDD {maxdd_of(wf):.1%}")
    for thr, d in cfgs.items():
        x = d.reindex(wf.index)
        print(f"  fijo {thr:.0%} en el mismo periodo:  CAGR {cagr_of(x):+.1%} | Sharpe {sharpe_of(x):.2f} | maxDD {maxdd_of(x):.1%}")
    print(f"  BTC comprar y mantener:       CAGR {cagr_of(btc):+.1%} | Sharpe {sharpe_of(btc):.2f} | maxDD {maxdd_of(btc):.1%}")

    # ---------- (3) estrés de costos y tamaño ----------
    print("\n=== (3) Estrés de costos y tamaño de posición (base 25%) ===")
    for cost in (0.0015, 0.0030, 0.0050, 0.0100):
        d, _, t_ = sp.run(close, open_, sig, cost, "close")
        print(f"  costo {cost:.2%}/lado: CAGR {cagr_of(d):+6.1%} | Sharpe {sharpe_of(d):5.2f} | maxDD {maxdd_of(d):6.1%} | neto/trade {t_.mean():+.2%}")
    for w in (0.05, 0.10, 0.20):
        sp.MAX_W = w
        d, _, t_ = sp.run(close, open_, sig, COST, "close")
        print(f"  peso máx por posición {w:.0%}: CAGR {cagr_of(d):+6.1%} | maxDD {maxdd_of(d):6.1%} | peor día {d.min():+.1%}")
    sp.MAX_W = 0.10

    # ---------- (4) Monte Carlo a 1 año ----------
    print("\n=== (4) Monte Carlo: 1 año con 1000 EUR (bootstrap por bloques de 10 días; solo retornos 2022-2026, el periodo más duro) ===")
    pool_d = daily[daily.index >= SPLIT].values
    finals, dds = [], []
    for _ in range(5000):
        path, need = [], 365
        while len(path) < need:
            s = rng.integers(0, len(pool_d) - 10)
            path.extend(pool_d[s:s + 10])
        p = np.array(path[:need])
        eq = np.cumprod(1 + p)
        finals.append(eq[-1] - 1)
        dds.append((eq / np.maximum.accumulate(eq) - 1).min())
    finals, dds = np.array(finals), np.array(dds)
    print(f"Retorno a 1 año: p5 {np.percentile(finals,5):+.1%} | mediana {np.median(finals):+.1%} | p95 {np.percentile(finals,95):+.1%} | P(pérdida) {(finals<0).mean():.0%}")
    print(f"Max drawdown en el año: mediana {np.median(dds):.1%} | p95 (peor 5%) {np.percentile(dds,5):.1%} | P(DD>20%) {(dds<-0.20).mean():.0%} | P(DD>50%) {(dds<-0.50).mean():.1%}")
    print(f"En euros (1000 EUR): peor 5% {1000*np.percentile(finals,5):+.0f} | mediana {1000*np.median(finals):+.0f} | mejor 5% {1000*np.percentile(finals,95):+.0f}")

    # ---------- (5) régimen y concentración ----------
    print("\n=== (5) Régimen de mercado y concentración ===")
    sma = close["BTC"].rolling(200).mean()
    bull = (close["BTC"] > sma)
    t2 = tr.rename("net").reset_index()
    t2.columns = ["date", "coin", "net"]
    t2["bull"] = t2["date"].map(bull)
    for lab, g in (("BTC > SMA200 (alcista)", t2[t2["bull"] == True]), ("BTC < SMA200 (bajista)", t2[t2["bull"] == False])):
        print(f"  {lab}: n={len(g)} | neto/trade {g['net'].mean():+.2%} | ganadoras {(g['net']>0).mean():.0%}")
    top = t2.groupby("coin")["net"].agg(["sum", "count"]).sort_values("sum", ascending=False)
    print(f"  Top 5 monedas por suma de retornos: " + ", ".join(f"{c}({r['count']:.0f} tr)" for c, r in top.head(5).iterrows()) + f" -> {top['sum'].head(5).sum()/top['sum'].sum():.0%} del total")
    by_year = daily.groupby(daily.index.year).apply(lambda x: (1 + x).prod() - 1)
    print("  Retorno por año: " + " | ".join(f"{y}:{v:+.0%}" for y, v in by_year.items()))
    print(f"  Año más rentable aporta {by_year.max():+.0%}; años negativos: {(by_year<0).sum()}/{len(by_year)}")


if __name__ == "__main__":
    main()

"""Amplía el backtest de rebote tras caídas a 45 monedas y examina la sensibilidad de los umbrales.

Rigor anti-overfitting:
  - Las 15 monedas NUEVAS se evalúan aparte (no se usaron para diseñar nada).
  - Se muestra la rejilla completa umbral x racha mínima, no solo la mejor celda.
  - La "mejor" celda se elige SOLO con 2017-2021 y se mide en 2022-2026.

Uso:  python -m scripts.backtest_crypto_extended
"""
import warnings

import numpy as np
import pandas as pd

from scripts.backtest_crypto_crash_rebound import COINS, SPLIT, fetch, load
from scripts.backtest_sp500_crash_rebound import CACHE, run, signal_matrix

warnings.filterwarnings("ignore")
# incluye monedas que se hundieron (LUNC, FTT) para reducir el sesgo de supervivencia
NEW = ["EOS", "XMR", "NEO", "IOTA", "XTZ", "THETA", "MANA", "SAND", "AXS", "GRT", "RUNE", "EGLD", "FTM", "LUNC", "FTT"]
COST = 0.0015
ANN = 365


def load_new():
    fc, fo = CACHE / "crypto_new_close.pkl", CACHE / "crypto_new_open.pkl"
    if fc.exists() and fo.exists():
        return pd.read_pickle(fc), pd.read_pickle(fo)
    o, c, ok = {}, {}, []
    for coin in NEW:
        try:
            o[coin], c[coin] = fetch(coin + "USDT")
            ok.append(coin)
        except Exception as e:
            print("  no disponible:", coin, str(e)[:60])
    close, open_ = pd.DataFrame(c), pd.DataFrame(o)
    close.to_pickle(fc)
    open_.to_pickle(fo)
    return close, open_


def metrics(d, mask=None):
    x = d if mask is None else d[mask]
    x = x[x.index >= x.index[0]]
    if len(x) < 30 or x.std() == 0:
        return dict(cagr=np.nan, sharpe=np.nan, dd=np.nan)
    eq = (1 + x).cumprod()
    yrs = max((x.index[-1] - x.index[0]).days / 365.25, 1e-9)
    return dict(cagr=eq.iloc[-1] ** (1 / yrs) - 1, sharpe=x.mean() / x.std() * np.sqrt(ANN), dd=(eq / eq.cummax() - 1).min())


def main():
    c0, o0 = load()
    c1, o1 = load_new()
    print(f"Monedas nuevas disponibles: {list(c1.columns)} ({c1.shape[1]}/{len(NEW)})")
    close = pd.concat([c0, c1], axis=1).sort_index()
    open_ = pd.concat([o0, o1], axis=1).sort_index()
    print(f"Total monedas: {close.shape[1]} | días: {close.shape[0]}")
    print("Historia de las nuevas: " + ", ".join(f"{c}:{c1[c].first_valid_index().year}-{c1[c].last_valid_index().year}" for c in c1.columns))

    btc = close["BTC"].pct_change().fillna(0)
    eqw = close.pct_change().mean(axis=1).fillna(0)
    print(f"\nReferencia BTC:   IS CAGR {metrics(btc, btc.index < SPLIT)['cagr']:+.0%} | OOS CAGR {metrics(btc, btc.index >= SPLIT)['cagr']:+.0%}")
    print(f"Referencia cesta: IS CAGR {metrics(eqw, eqw.index < SPLIT)['cagr']:+.0%} | OOS CAGR {metrics(eqw, eqw.index >= SPLIT)['cagr']:+.0%}")

    def line(label, d, e, tr):
        m_all, m_is, m_os = metrics(d), metrics(d, d.index < SPLIT), metrics(d, d.index >= SPLIT)
        print(f"{label:34} CAGR {m_all['cagr']:+6.1%} Sharpe {m_all['sharpe']:5.2f} DD {m_all['dd']:6.1%} | IS {m_is['cagr']:+6.1%} OOS {m_os['cagr']:+6.1%} | inv {(e>0).mean():4.0%} n={len(tr):5} neto/trade {tr.mean():+.2%}")

    print("\n=== Reglas pre-declaradas (racha>=2), 45 monedas ===")
    for thr in (0.15, 0.20, 0.30):
        sig = signal_matrix(close, thr, 2)
        d, e, tr = run(close, open_, sig, COST, "close")
        line(f"45 monedas, caída >= {thr:.0%}", d, e, tr)
    print("\n=== Solo las 15 monedas NUEVAS (prueba fuera de universo) ===")
    for thr in (0.15, 0.20, 0.30):
        sig = signal_matrix(c1, thr, 2)
        d, e, tr = run(c1, o1, sig, COST, "close")
        if len(tr):
            line(f"15 nuevas, caída >= {thr:.0%}", d, e, tr)
    print("\n=== Solo LUNC + FTT (monedas que se hundieron), regla >=20% ===")
    for coin in ("LUNC", "FTT"):
        if coin in c1:
            sig = signal_matrix(c1[[coin]], 0.20, 2)
            d, e, tr = run(c1[[coin]], o1[[coin]], sig, COST, "close")
            if len(tr):
                print(f"  {coin}: {len(tr)} señales, neto medio/trade {tr.mean():+.2%}, ganadoras {(tr>0).mean():.0%}, peor {tr.min():+.1%}, mejor {tr.max():+.1%}")

    print("\n=== Rejilla completa (45 monedas): umbral x racha mínima  [IS Sharpe | OOS Sharpe | OOS CAGR | OOS maxDD | n trades] ===")
    grid = []
    for kmin in (1, 2, 3):
        for thr in (0.10, 0.15, 0.20, 0.25, 0.30, 0.40):
            sig = signal_matrix(close, thr, kmin)
            d, e, tr = run(close, open_, sig, COST, "close")
            mi, mo = metrics(d, d.index < SPLIT), metrics(d, d.index >= SPLIT)
            grid.append(dict(k=kmin, thr=thr, sis=mi["sharpe"], sos=mo["sharpe"], cos=mo["cagr"], dos=mo["dd"], n=len(tr)))
            print(f"  racha>={kmin} caída>={thr:>4.0%}: IS {mi['sharpe']:5.2f} | OOS {mo['sharpe']:5.2f} | OOS CAGR {mo['cagr']:+6.1%} | OOS DD {mo['dd']:6.1%} | n={len(tr)}")
    g = pd.DataFrame(grid).dropna()
    best = g.sort_values("sis", ascending=False).iloc[0]
    print(f"\nMejor celda según Sharpe IS (2017-2021): racha>={int(best['k'])}, caída>={best['thr']:.0%} -> IS {best['sis']:.2f}, OOS Sharpe {best['sos']:.2f}, OOS CAGR {best['cos']:+.1%}, OOS DD {best['dos']:.1%}")
    print(f"Media de OOS Sharpe en toda la rejilla: {g['sos'].mean():.2f} | celdas con OOS Sharpe > 0.5: {(g['sos']>0.5).sum()}/{len(g)}")
    print(f"Correlación IS Sharpe vs OOS Sharpe entre celdas: {g['sis'].corr(g['sos']):+.2f}")


if __name__ == "__main__":
    main()

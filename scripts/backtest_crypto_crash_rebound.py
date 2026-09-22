"""Backtest de cartera: rebote tras caídas fuertes en las 30 criptos principales (Binance, diario UTC).

Mismas reglas que scripts/backtest_sp500_crash_rebound.py, fijadas antes de ver resultados:
  - Señal al cierre diario (00:00 UTC) de t: >=2 días seguidos de caída con caída acumulada >= THR.
    Umbrales pre-declarados 15/20/30% (cripto es ~2-3x más volátil que acciones).
  - Compra al cierre de t, vende al cierre de t+1. Sin apalancamiento. Peso = min(10%, 1/n_señales).
  - El mercado cripto no cierra: entrar al cierre diario es ejecutable (sin hueco de apertura).

LIMITACIÓN: usa las 30 monedas grandes de HOY (sesgo de supervivencia: faltan las que se hundieron
y desaparecieron, p.ej. LUNA/FTT), lo que favorece esta estrategia.

Uso:
    python -m scripts.backtest_crypto_crash_rebound
"""
import time
import warnings

import numpy as np
import pandas as pd
import requests

from scripts.backtest_sp500_crash_rebound import CACHE, run, signal_matrix, stats

warnings.filterwarnings("ignore")
COINS = ["BTC", "ETH", "BNB", "XRP", "ADA", "DOGE", "SOL", "TRX", "LINK", "DOT", "LTC", "BCH", "AVAX",
         "XLM", "ATOM", "ETC", "UNI", "FIL", "NEAR", "APT", "ARB", "OP", "HBAR", "ICP", "VET", "AAVE",
         "ALGO", "SHIB", "TON", "SUI"]
SPLIT = pd.Timestamp("2022-01-01")
ANN = 365


def fetch(sym):
    rows, cursor = [], int(pd.Timestamp("2017-08-01", tz="UTC").timestamp() * 1000)
    while True:
        r = requests.get("https://api.binance.com/api/v3/klines",
                         params={"symbol": sym, "interval": "1d", "startTime": cursor, "limit": 1000}, timeout=30)
        r.raise_for_status()
        b = r.json()
        if not b:
            break
        rows += b
        cursor = b[-1][0] + 86_400_000
        if len(b) < 1000:
            break
        time.sleep(0.15)
    df = pd.DataFrame(rows).iloc[:-1]  # sin el día en curso
    idx = pd.to_datetime(df[0], unit="ms")
    return pd.Series(df[1].astype(float).values, idx), pd.Series(df[4].astype(float).values, idx)


def load():
    fc, fo = CACHE / "crypto_close.pkl", CACHE / "crypto_open.pkl"
    if fc.exists() and fo.exists():
        return pd.read_pickle(fc), pd.read_pickle(fo)
    o, c = {}, {}
    for coin in COINS:
        try:
            o[coin], c[coin] = fetch(coin + "USDT")
        except Exception as e:
            print("omitida", coin, e)
    close, open_ = pd.DataFrame(c), pd.DataFrame(o)
    close.to_pickle(fc)
    open_.to_pickle(fo)
    return close, open_


def main():
    close, open_ = load()
    print(f"Monedas: {close.shape[1]} | días: {close.shape[0]} ({close.index[0].date()} -> {close.index[-1].date()})")
    btc_r = close["BTC"].pct_change().fillna(0)
    eqw_r = close.pct_change().mean(axis=1).fillna(0)
    print("\n--- Referencias (comprar y mantener) ---")
    for lab, r in [("BTC", btc_r), ("Cesta equiponderada (rebalanceo diario)", eqw_r)]:
        eq = (1 + r).cumprod()
        yrs = (eq.index[-1] - eq.index[0]).days / 365.25
        print(f"{lab:38} ret total {eq.iloc[-1]-1:+9.1%} | CAGR {eq.iloc[-1]**(1/yrs)-1:+6.1%} | maxDD {(eq/eq.cummax()-1).min():6.1%} | Sharpe {r.mean()/r.std()*np.sqrt(ANN):5.2f}")

    results = {}
    for thr in (0.15, 0.20, 0.30):
        sig = signal_matrix(close, thr)
        print(f"\n=== Caída acumulada >= {thr:.0%} (2+ días) | señales: {int(sig.values.sum()):,} en {int((sig.sum(axis=1)>0).sum())} días ===")
        for cost, entry, lab in [(0.0015, "close", "Entrada cierre t, costo 0.15%/lado"),
                                  (0.0030, "close", "Entrada cierre t, costo 0.30%/lado (estrés)"),
                                  (0.0015, "open", "Entrada apertura t+1, costo 0.15%/lado")]:
            d, e, tr = run(close, open_, sig, cost, entry)
            stats(d, e, tr, lab, ann=ANN)
            results[(thr, entry, cost)] = (d, e, tr)

    for thr in (0.15, 0.20):
        d, e, tr = results[(thr, "close", 0.0015)]
        print(f"\n--- Detalle variante >={thr:.0%}, entrada al cierre, 0.15%/lado ---")
        for lab, m in [("IS  2017-2021", d.index < SPLIT), ("OOS 2022-2026", d.index >= SPLIT)]:
            x = d[m]
            yrs = (x.index[-1] - x.index[0]).days / 365.25
            eq = (1 + x).cumprod()
            print(f"{lab}: ret {eq.iloc[-1]-1:+.1%} | CAGR {eq.iloc[-1]**(1/yrs)-1:+.1%} | maxDD {(eq/eq.cummax()-1).min():.1%} | BTC mismo periodo {(1+btc_r[m]).prod()-1:+.1%} | cesta {(1+eqw_r[m]).prod()-1:+.1%}")
        ann_s = d.groupby(d.index.year).apply(lambda x: (1 + x).prod() - 1)
        ann_b = btc_r.groupby(btc_r.index.year).apply(lambda x: (1 + x).prod() - 1)
        print("Por año (estrategia/BTC): " + " | ".join(f"{y}: {ann_s[y]:+.0%}/{ann_b[y]:+.0%}" for y in ann_s.index))
        nocovid = d[~((d.index >= "2020-03-01") & (d.index <= "2020-04-15"))]
        print(f"Robustez sin mar-abr 2020: {(1+nocovid).prod()-1:+.1%} | sin los 5 mejores días: {(1+d.drop(d.nlargest(5).index)).prod()-1:+.1%} | sin FTX (nov-2022): {(1+d[~((d.index>='2022-11-01')&(d.index<='2022-11-30'))]).prod()-1:+.1%}")
        print(f"Peor día cartera: {d.min():+.2%} ({d.idxmin().date()}) | mejor: {d.max():+.2%} | peor trade: {tr.min():+.1%} | percentil 1: {tr.quantile(0.01):+.1%}")


if __name__ == "__main__":
    main()

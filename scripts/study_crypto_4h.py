"""¿Funciona la regla de rebote tras caída fuerte con velas de 4 horas? (más eventos por moneda => menos dependencia de pocos días)

Misma definición que en diario: racha >=2 velas de caída con magnitud z>=3/4/5 (σ de las 60 velas previas). Se compra al cierre de la vela
y se mantiene 1 vela (4 h) o 6 velas (24 h). Costo 0.15%/lado. Corte IS/OOS: 2022-01-01. Cripto 24/7 => sin huecos de mercado.

Uso: python -m scripts.study_crypto_4h
"""
import time
import warnings

import numpy as np
import pandas as pd
import requests

from screener.backtest import perf
from screener.events import build_events
from screener.universe import CACHE, COST, CRYPTO
from scripts.study_trend_pullback import hold_portfolio

warnings.filterwarnings("ignore")
SPLIT = pd.Timestamp("2022-01-01")
COST_C = COST["crypto"]
BARS_PER_YEAR = 365 * 6


def fetch4h(sym):
    rows, cursor = [], int(pd.Timestamp("2018-01-01", tz="UTC").timestamp() * 1000)
    while True:
        r = requests.get("https://api.binance.com/api/v3/klines", params=dict(symbol=sym, interval="4h", startTime=cursor, limit=1000), timeout=30)
        r.raise_for_status()
        b = r.json()
        if not b:
            break
        rows += b
        if len(b) < 1000:
            break
        cursor = b[-1][0] + 4 * 3_600_000
        time.sleep(0.1)
    df = pd.DataFrame(rows).iloc[:-1]
    return pd.Series(df[4].astype(float).values, pd.to_datetime(df[0], unit="ms"))


def load4h():
    f = CACHE / "scr_crypto_4h_close.pkl"
    if f.exists():
        return pd.read_pickle(f)
    out = {}
    for c in CRYPTO:
        try:
            out[c] = fetch4h(c + "USDT")
        except Exception:
            pass
    df = pd.DataFrame(out)
    df.to_pickle(f)
    return df


def line(label, d):
    p, pi, po = perf(d, BARS_PER_YEAR), perf(d[d.index < SPLIT], BARS_PER_YEAR), perf(d[d.index >= SPLIT], BARS_PER_YEAR)
    print(f"  {label:<40} CAGR {p['cagr']:+6.1%} Sharpe {p['sharpe']:5.2f} DD {p['dd']:6.1%} | IS {pi['cagr']:+6.1%} ({pi['sharpe']:5.2f}) | OOS {po['cagr']:+6.1%} ({po['sharpe']:5.2f}, DD {po['dd']:5.1%})")


def main():
    close = load4h()
    last_ok = close.apply(lambda s: s.last_valid_index())
    close = close.loc[:, last_ok >= last_ok.max() - pd.Timedelta(days=15)]
    print(f"Velas de 4 h: {close.shape[1]} monedas | {len(close):,} velas | {close.index[0].date()} -> {close.index[-1].date()}")
    ev = build_events(close)
    e = ev[ev["next"].notna() & (ev["dir"] == "down") & (ev["k"] >= 2)].copy()
    e["net"] = e["next"] - 2 * COST_C
    print(f"Eventos de caída (2+ velas): {len(e):,}")
    print("\nP(sube en la vela siguiente) por magnitud (racha>=2 velas):   [ todo | IS | OOS ]")
    for zb in range(0, 5):
        g = e[e["zb"] == zb]
        if len(g) < 50:
            continue
        gi, go = g[g["date"] < SPLIT], g[g["date"] >= SPLIT]
        print(f"  z {zb}{'+' if zb == 4 else '-' + str(zb + 1)}σ: n={len(g):6} P={(g['next'] > 0).mean():5.1%} neto/op {g['net'].mean():+.3%} | IS {len(gi):5}/{(gi['next'] > 0).mean():4.0%} {gi['net'].mean():+.2%} | OOS {len(go):5}/{(go['next'] > 0).mean():4.0%} {go['net'].mean():+.2%}")
    print("\nCartera (peso máx 10%, sin apalancamiento)   [total | IS | OOS]")
    for zmin in (3, 4, 5):
        sel = e[e["z"] >= zmin]
        for h, lab in ((1, "mantener 1 vela (4 h)"), (6, "mantener 6 velas (24 h)")):
            line(f"z>={zmin}, {lab} (n={len(sel)})", hold_portfolio(sel, close, COST_C, h))
    sel = e[e["z"] >= 3]
    line("Estrés costos 0.4%/lado: z>=3, 24 h", hold_portfolio(sel, close, 0.004, 6))
    btc = close["BTC"]
    dd90 = btc / btc.rolling(90 * 6).max() - 1
    strong = sel[sel["date"].map(dd90) <= -0.25]
    line(f"z>=3 con BTC en capitulación (n={len(strong)}), 24 h", hold_portfolio(strong, close, COST_C, 6))
    print(f"\nFechas distintas con señal z>=3: {sel['date'].dt.normalize().nunique()} días | operaciones por año ≈ {len(sel) / ((close.index[-1] - close.index[0]).days / 365):.0f}")


if __name__ == "__main__":
    main()

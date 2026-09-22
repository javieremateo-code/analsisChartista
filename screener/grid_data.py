"""Velas horarias completas (open/high/low/close) para el bot de grid: necesita el camino intrabar, no solo el
cierre, para saber si el precio realmente tocó cada línea de la rejilla. Distinto del resto del proyecto (que solo
guarda close+volumen) porque aquí el orden de los cruces dentro de la vela importa.
"""
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests

from .universe import CACHE

STEP_MS = 3_600_000


def fetch_ohlc_1h(sym, start):
    rows, cursor = [], int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
    while True:
        for attempt in range(4):
            try:
                r = requests.get("https://api.binance.com/api/v3/klines",
                                 params=dict(symbol=sym, interval="1h", startTime=cursor, limit=1000), timeout=30)
                b = r.json()
                if isinstance(b, list):
                    break
            except Exception:
                b = None
            time.sleep(1.5 * (attempt + 1))
        if not isinstance(b, list) or not b:
            break
        rows += b
        if len(b) < 1000:
            break
        cursor = b[-1][0] + STEP_MS
        time.sleep(0.08)
    if not rows:
        return None
    df = pd.DataFrame(rows).iloc[:-1]  # sin la vela en curso
    idx = pd.to_datetime(df[0], unit="ms")
    return pd.DataFrame({"open": df[1].astype(float).values, "high": df[2].astype(float).values,
                         "low": df[3].astype(float).values, "close": df[4].astype(float).values}, index=idx)


def load_ohlc_1h(coins, start="2020-01-01", refresh=False):
    """{moneda: DataFrame(open,high,low,close)} con caché por moneda en data/cache/grid_1h/."""
    d = CACHE / "grid_1h"
    d.mkdir(exist_ok=True)

    def one(c):
        f = d / f"{c}.pkl"
        if f.exists() and not refresh:
            return c, pd.read_pickle(f)
        try:
            df = fetch_ohlc_1h(c + "USDT", start)
        except Exception:
            df = None
        if df is not None:
            df.to_pickle(f)
        return c, df

    out = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        for c, df in ex.map(one, coins):
            if df is not None and len(df) > 500:
                out[c] = df
    return out

"""Datos adicionales de cripto para condicionar las señales: volumen diario (USDT) y funding rate de futuros perpetuos."""
import time

import pandas as pd
import requests

from .universe import CACHE, CRYPTO

FUT_SYMBOL = {"SHIB": "1000SHIBUSDT", "LUNC": "1000LUNCUSDT"}


def _klines_qvol(sym):
    rows, cursor = [], int(pd.Timestamp("2017-08-01", tz="UTC").timestamp() * 1000)
    while True:
        r = requests.get("https://api.binance.com/api/v3/klines",
                         params={"symbol": sym, "interval": "1d", "startTime": cursor, "limit": 1000}, timeout=30)
        r.raise_for_status()
        b = r.json()
        if not b:
            break
        rows += b
        if len(b) < 1000:
            break
        cursor = b[-1][0] + 86_400_000
        time.sleep(0.12)
    df = pd.DataFrame(rows).iloc[:-1]
    return pd.Series(df[7].astype(float).values, pd.to_datetime(df[0], unit="ms"))  # volumen en USDT


def load_qvol(refresh=False):
    f = CACHE / "scr_crypto_qvol.pkl"
    if f.exists() and not refresh:
        return pd.read_pickle(f)
    out = {}
    for c in CRYPTO:
        try:
            out[c] = _klines_qvol(c + "USDT")
        except Exception:
            pass
    df = pd.DataFrame(out)
    df.to_pickle(f)
    return df


def _funding(sym):
    rows, cursor = [], int(pd.Timestamp("2019-01-01", tz="UTC").timestamp() * 1000)
    while True:
        r = requests.get("https://fapi.binance.com/fapi/v1/fundingRate", params={"symbol": sym, "startTime": cursor, "limit": 1000}, timeout=30)
        r.raise_for_status()
        b = r.json()
        if not b:
            break
        rows += b
        if len(b) < 1000:
            break
        cursor = b[-1]["fundingTime"] + 1
        time.sleep(0.12)
    s = pd.Series({pd.to_datetime(x["fundingTime"], unit="ms"): float(x["fundingRate"]) for x in rows})
    return s.resample("D").sum()  # funding acumulado por día (3 pagos de 8h)


def load_funding(refresh=False):
    f = CACHE / "scr_crypto_funding.pkl"
    if f.exists() and not refresh:
        return pd.read_pickle(f)
    out = {}
    for c in CRYPTO:
        try:
            s = _funding(FUT_SYMBOL.get(c, c + "USDT"))
            if len(s) > 100:
                out[c] = s
        except Exception:
            pass
    df = pd.DataFrame(out)
    df.index = df.index.normalize()
    df.to_pickle(f)
    return df

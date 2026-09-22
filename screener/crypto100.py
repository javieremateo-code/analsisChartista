"""Universo de las 100 principales criptomonedas (par USDT en Binance spot) y descarga de velas 1d / 4h / 1h con caché.

Selección: ranking por capitalización (CoinGecko) si está disponible, y si no por volumen 24 h en Binance; sin stablecoins,
tokens envueltos/derivados de liquidez ni tokens apalancados. AVISO: es el top 100 de HOY (sesgo de supervivencia).
"""
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import requests

from .universe import CACHE

STABLE_OR_WRAPPED = {"USDT", "USDC", "DAI", "TUSD", "FDUSD", "USDE", "USDD", "USDP", "PYUSD", "BUSD", "USDS", "USD1", "USDG", "EURC", "EURI", "AEUR", "XUSD", "BFUSD",
                     "WBTC", "WETH", "STETH", "WSTETH", "WBETH", "WEETH", "RETH", "CBETH", "CBBTC", "BTCB", "JITOSOL", "BNSOL", "SUSDE", "SUSDS", "USDY", "BUIDL",
                     "LEO", "OKB", "HT", "CRO", "GT", "KCS", "BGB", "MNT", "FTT_", "TON_"}
UNIVERSE_F = CACHE / "scr_crypto100_universe.pkl"
START_MS = {"1d": "2017-08-01", "8h": "2018-01-01", "4h": "2018-01-01", "1h": "2019-01-01"}
STEP_MS = {"1d": 86_400_000, "8h": 8 * 3_600_000, "4h": 4 * 3_600_000, "1h": 3_600_000}


def _binance_usdt_symbols():
    info = requests.get("https://api.binance.com/api/v3/exchangeInfo", timeout=30).json()
    return {s["baseAsset"] for s in info["symbols"] if s["quoteAsset"] == "USDT" and s["status"] == "TRADING" and s.get("isSpotTradingAllowed")}


def get_universe(n=100, refresh=False):
    uf = UNIVERSE_F if n == 100 else CACHE / f"scr_crypto{n}_universe.pkl"
    if uf.exists() and not refresh:
        return pd.read_pickle(uf)
    avail = _binance_usdt_symbols()
    coins, source = [], "coingecko"
    try:
        r = requests.get("https://api.coingecko.com/api/v3/coins/markets", params=dict(vs_currency="usd", order="market_cap_desc", per_page=250, page=1), timeout=30)
        r.raise_for_status()
        for x in r.json():
            s = x["symbol"].upper()
            if s in avail and s not in STABLE_OR_WRAPPED and s not in coins:
                coins.append(s)
    except Exception:
        coins = []
    if len(coins) < n:  # respaldo: mayor volumen 24 h en Binance
        source = "binance-volumen"
        t = pd.DataFrame(requests.get("https://api.binance.com/api/v3/ticker/24hr", timeout=30).json())
        t = t[t["symbol"].str.endswith("USDT")]
        t["base"] = t["symbol"].str[:-4]
        t = t[~t["base"].str.endswith(("UP", "DOWN", "BULL", "BEAR")) & ~t["base"].isin(STABLE_OR_WRAPPED)]
        t["qv"] = t["quoteVolume"].astype(float)
        coins = list(dict.fromkeys(coins + t.sort_values("qv", ascending=False)["base"].tolist()))
    uni = coins[:n]
    pd.to_pickle(dict(coins=uni, source=source), uf)
    return dict(coins=uni, source=source)


def fetch_klines(sym, interval):
    rows, cursor = [], int(pd.Timestamp(START_MS[interval], tz="UTC").timestamp() * 1000)
    while True:
        for attempt in range(4):
            try:
                r = requests.get("https://api.binance.com/api/v3/klines", params=dict(symbol=sym, interval=interval, startTime=cursor, limit=1000), timeout=30)
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
        cursor = b[-1][0] + STEP_MS[interval]
        time.sleep(0.08)
    if not rows:
        return None
    df = pd.DataFrame(rows).iloc[:-1]  # sin la vela en curso
    idx = pd.to_datetime(df[0], unit="ms")
    return pd.DataFrame({"close": df[4].astype(float).values, "qvol": df[7].astype(float).values}, index=idx)


def load(interval, coins=None, workers=5, refresh=False):
    """Devuelve (close, qvol) como DataFrames (columnas = monedas). Reanudable: cachea cada moneda."""
    coins = coins or get_universe()["coins"]
    d = CACHE / f"crypto100_{interval}"
    d.mkdir(exist_ok=True)

    def one(c):
        f = d / f"{c}.pkl"
        if f.exists() and not refresh:
            return c, pd.read_pickle(f)
        try:
            df = fetch_klines(c + "USDT", interval)
        except Exception:
            df = None
        if df is not None:
            df.to_pickle(f)
        return c, df

    out = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, (c, df) in enumerate(ex.map(one, coins)):
            if df is not None and len(df) > 200:
                out[c] = df
            if (i + 1) % 20 == 0:
                print(f"  [{interval}] {i + 1}/{len(coins)} monedas", flush=True)
    close = pd.DataFrame({c: v["close"] for c, v in out.items()}).sort_index()
    qvol = pd.DataFrame({c: v["qvol"] for c, v in out.items()}).sort_index()
    return close, qvol


EXCLUDE = {"XAUT", "PAXG", "RLUSD", "U", "FRAX", "USDG"}  # oro tokenizado y estables que se colaron en el ranking
MIN_LIQUIDITY = 5e6  # volumen medio de 30 días en USDT/día para poder operar (con menos, el slippage no es fiable)


def clean_universe(close, qvol=None):
    """Quita stablecoins/oro tokenizado/símbolos no ASCII y monedas sin datos al día (deslistadas)."""
    keep = [c for c in close.columns if c not in EXCLUDE and c.isascii()]
    close = close[keep]
    last_ok = close.apply(lambda x: x.last_valid_index())
    keep = last_ok[last_ok >= last_ok.max() - pd.Timedelta(days=15)].index
    return (close[keep], qvol[keep]) if qvol is not None else close[keep]


def _recent_one(c, days):
    for attempt in range(3):
        try:
            b = requests.get("https://api.binance.com/api/v3/klines", params=dict(symbol=c + "USDT", interval="1d", limit=days + 1), timeout=30).json()
            if isinstance(b, list) and len(b) > 10:
                df = pd.DataFrame(b).iloc[:-1]  # sin la vela en curso
                idx = pd.to_datetime(df[0], unit="ms")
                return c, pd.DataFrame({"close": df[4].astype(float).values, "qvol": df[7].astype(float).values}, index=idx)
        except Exception:
            pass
        time.sleep(1 + attempt)
    return c, None


def load_recent_full(days=400, coins=None, workers=5):
    """Últimos ~`days` cierres y volúmenes diarios de las 100 principales (400 días: el modelo usa ventanas de hasta 250)."""
    coins = coins or get_universe()["coins"]
    out = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for c, df in ex.map(lambda x: _recent_one(x, days), coins):
            if df is not None:
                out[c] = df
    close = pd.DataFrame({c: v["close"] for c, v in out.items()}).sort_index()
    qvol = pd.DataFrame({c: v["qvol"] for c, v in out.items()}).sort_index()
    return clean_universe(close, qvol)


def load_recent(days=400, coins=None, workers=5):
    """(cierres, liquidez media 30 días por moneda) para el informe diario."""
    close, qvol = load_recent_full(days, coins, workers)
    return close, qvol.rolling(30, min_periods=15).mean().iloc[-1].to_dict()

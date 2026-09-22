"""Datos de mercado en vivo (API pública de Binance, sin claves): velas cerradas, cotizaciones y mínimos intradía."""
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests

BASE = "https://api.binance.com"
HOURS = {"1h": 1, "4h": 4, "1d": 24}


def _get(path, params, tries=4):
    for i in range(tries):
        try:
            r = requests.get(BASE + path, params=params, timeout=20)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        time.sleep(1.0 * (i + 1))
    return None


class BinanceFeed:
    def __init__(self, coins, workers=5):
        self.coins = list(coins)
        self.workers = workers

    def _klines(self, coin, interval, n):
        b = _get("/api/v3/klines", dict(symbol=coin + "USDT", interval=interval, limit=n))
        if not isinstance(b, list) or len(b) < 5:
            return coin, None
        df = pd.DataFrame(b)
        idx = pd.to_datetime(df[0], unit="ms")
        return coin, pd.DataFrame({"close": df[4].astype(float).values, "qvol": df[7].astype(float).values, "low": df[3].astype(float).values}, index=idx)

    def closes(self, interval, n=220, now=None):
        """(close, qvol) solo con velas CERRADAS a `now` (UTC, sin zona horaria)."""
        now = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="UTC").tz_localize(None)
        hrs = pd.Timedelta(hours=HOURS[interval])
        out = {}
        with ThreadPoolExecutor(max_workers=self.workers) as ex:
            for coin, df in ex.map(lambda c: self._klines(c, interval, n), self.coins):
                if df is not None:
                    out[coin] = df[df.index + hrs <= now]
        close = pd.DataFrame({c: v["close"] for c, v in out.items()}).sort_index()
        qvol = pd.DataFrame({c: v["qvol"] for c, v in out.items()}).sort_index()
        return close, qvol

    def quotes(self):
        """{moneda: {'bid':..., 'ask':...}} en una sola llamada."""
        b = _get("/api/v3/ticker/bookTicker", {})
        if not isinstance(b, list):
            return {}
        want = {c + "USDT": c for c in self.coins}
        return {want[x["symbol"]]: dict(bid=float(x["bidPrice"]), ask=float(x["askPrice"])) for x in b if x["symbol"] in want and float(x["bidPrice"]) > 0}

    def min_low(self, coin, start, end=None):
        """Mínimo intradía (velas de 1 h) entre `start` y ahora: para comprobar si se tocó un stop."""
        start = pd.Timestamp(start)
        b = _get("/api/v3/klines", dict(symbol=coin + "USDT", interval="1h", startTime=int(start.tz_localize("UTC").timestamp() * 1000), limit=1000))
        if not isinstance(b, list) or not b:
            return None
        return min(float(x[3]) for x in b)

"""Datos externos al cripto que pueden dar pistas: Nasdaq/S&P, VIX, dólar, bonos, oro (Yahoo) y funding de futuros (Binance).

Alineación temporal SIN lookahead: el día cripto d (UTC) termina a las 00:00 UTC de d+1; el cierre de EE.UU. del día d (≈21:00 UTC) ya es conocido.
Los fines de semana se arrastra el último valor disponible.
"""
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from .extra_data import _funding
from .universe import CACHE, _yf

US = {"SPY": "SPY", "QQQ": "QQQ", "VIX": "^VIX", "DXY": "UUP", "TNX": "^TNX", "GLD": "GLD"}


def us_levels(refresh=False):
    f = CACHE / "scr_us_levels.pkl"
    if f.exists() and not refresh:
        return pd.read_pickle(f)
    close, _ = _yf(list(US.values()), start="2017-01-01")
    close = close.rename(columns={v: k for k, v in US.items()})
    close.to_pickle(f)
    return close


def cross_asset_features(idx, refresh=False):
    """DataFrame indexado por días cripto (UTC) con variables de otros mercados, conocidas al cierre del día."""
    lv = us_levels(refresh).reindex(idx, method="ffill", limit=5)
    out = pd.DataFrame(index=idx)
    out["spy_ret1"] = lv["SPY"].pct_change(1)
    out["spy_ret5"] = lv["SPY"].pct_change(5)
    out["qqq_ret5"] = lv["QQQ"].pct_change(5)
    out["vix"] = lv["VIX"]
    out["vix_chg5"] = lv["VIX"].pct_change(5)
    out["dxy_ret5"] = lv["DXY"].pct_change(5)
    out["tnx_chg5"] = lv["TNX"].diff(5)
    out["gld_ret5"] = lv["GLD"].pct_change(5)
    return out


def _fund_one(coin):
    for sym in (coin + "USDT", "1000" + coin + "USDT"):
        try:
            s = _funding(sym)
            if len(s) > 100:
                return coin, s
        except Exception:
            pass
        time.sleep(0.1)
    return coin, None


def funding_100(coins, refresh=False):
    f = CACHE / "scr_funding100.pkl"
    if f.exists() and not refresh:
        return pd.read_pickle(f)
    out = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        for c, s in ex.map(_fund_one, coins):
            if s is not None:
                out[c] = s
    df = pd.DataFrame(out)
    df.index = df.index.normalize()
    df.to_pickle(f)
    return df

"""Tablas históricas de probabilidad por clase de activo: dada una racha (dirección, magnitud z),
¿con qué frecuencia y cuánto se mueve el activo en sentido contrario al día siguiente?"""
import math
import pickle

import numpy as np
import pandas as pd

from .events import build_events
from .universe import CACHE, SPLIT, load_history


def wilson_low(k, n, z=1.96):
    if n == 0:
        return float("nan")
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - h) / d


def build_stats(cls, close=None):
    if close is None:
        close, _ = load_history(cls)
    last_ok = close.apply(lambda s: s.last_valid_index())
    close = close.loc[:, last_ok >= last_ok.max() - pd.Timedelta(days=15)]  # sin activos inactivos
    ev = build_events(close)
    e = ev[ev["next"].notna()].copy()
    e["fav"] = np.where(e["dir"] == "down", e["next"], -e["next"])  # retorno a favor de la reversión
    e["rev"] = e["fav"] > 0
    split = pd.Timestamp(SPLIT[cls])
    base = {dr: float(e[(e["dir"] == dr) & (e["k"] >= 1)]["rev"].mean()) for dr in ("down", "up")}
    rows = []
    for (dr, zb), g in e[e["k"] >= 2].groupby(["dir", "zb"]):
        n, kk = len(g), int(g["rev"].sum())
        go = g[g["date"] >= split]
        rows.append(dict(dir=dr, zb=int(zb), n=n, p=kk / n, p_low=wilson_low(kk, n), mean=g["fav"].mean(),
                         median=g["fav"].median(), p5=g["fav"].quantile(0.05), worst=g["fav"].min(),
                         n_oos=len(go), p_oos=float(go["rev"].mean()) if len(go) else np.nan, base=base[dr]))
    cells = []
    for (dr, kc, zb), g in e.groupby(["dir", "kc", "zb"]):
        cells.append(dict(dir=dr, kc=int(kc), zb=int(zb), n=len(g), p=float(g["rev"].mean())))
    return dict(pooled=pd.DataFrame(rows), cells=pd.DataFrame(cells), base=base, built=str(pd.Timestamp.now().date()),
                history_end=str(close.index[-1].date()), n_assets=close.shape[1])


def get_stats(cls, refresh=False, close=None, tag=""):
    """Tablas históricas por clase. `close`/`tag` permiten usar otro universo (p.ej. las 100 principales criptos) con su propia caché."""
    f = CACHE / f"scr_stats_{cls}{tag}.pkl"
    if f.exists() and not refresh:
        return pickle.loads(f.read_bytes())
    st = build_stats(cls, close)
    f.write_bytes(pickle.dumps(st))
    return st

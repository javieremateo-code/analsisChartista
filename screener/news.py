"""Noticias/sentimiento a nivel de mercado.

Fuentes (gratuitas, con histórico diario):
  - GDELT DOC 2.0: nº diario de artículos que hablan de un tema (total) y de los que ADEMÁS contienen palabras de
    advertencia de corrección (crash, bubble, overvalued...). "Cuota de aviso" = advertencias / total.
    Limitación: es a nivel de MERCADO/tema, no por acción individual; el tono automático es ruidoso.
  - Fear & Greed de cripto (alternative.me, desde 2018-02) y VIX (yfinance): proxies de sentimiento, NO son noticias.

La descarga de GDELT es lenta (límite de 1 petición cada ≥5 s) y reanudable: guarda cada tramo en data/cache/gdelt.
"""
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from .universe import CACHE

GDELT_DIR = CACHE / "gdelt"
GDELT_DIR.mkdir(parents=True, exist_ok=True)
WARN = '(correction OR crash OR bubble OR overvalued OR selloff OR "sell-off" OR plunge OR overbought)'
TOPICS = {
    "crypto": '(bitcoin OR ethereum OR cryptocurrency OR crypto)',
    "stocks": '("stock market" OR "wall street" OR "S&P 500")',
    "forex": '(dollar OR forex OR "currency market")',
    "commodities": '(oil OR gold OR commodities)',
}


def _request(query, start, end, tries=8):
    for i in range(tries):
        time.sleep(7 + 6 * i)  # respeta el límite y aumenta la espera si nos frena
        try:
            r = requests.get("https://api.gdeltproject.org/api/v2/doc/doc",
                             params={"query": query, "mode": "timelinevolraw", "format": "json",
                                     "startdatetime": start, "enddatetime": end}, timeout=90)
            if r.status_code == 200 and r.text.startswith("{"):
                return r.json()
        except Exception:
            pass
    return None


def _parse(js):
    rows = []
    for series in js.get("timeline", []):
        if "Article Count" in series.get("series", ""):
            for p in series["data"]:
                rows.append((pd.to_datetime(p["date"][:8]), float(p["value"])))
    return pd.Series(dict(rows)).sort_index() if rows else pd.Series(dtype=float)


def fetch_series(topic, kind, start_year=2017, end=None):
    """kind: 'total' o 'warn'. Devuelve serie diaria de nº de artículos; reanuda desde caché por año."""
    end = end or pd.Timestamp.now().normalize()
    base = TOPICS[topic]
    query = base if kind == "total" else f"{base} {WARN}"
    parts = []
    for y in range(start_year, end.year + 1):
        f = GDELT_DIR / f"{topic}_{kind}_{y}.csv"
        if f.exists() and (y < end.year):
            parts.append(pd.read_csv(f, index_col=0, parse_dates=True).iloc[:, 0])
            continue
        s, e = f"{y}0101000000", (f"{y + 1}0101000000" if y < end.year else end.strftime("%Y%m%d000000"))
        js = _request(query, s, e)
        if js is None:
            print(f"  ! sin datos {topic}/{kind}/{y}")
            continue
        ser = _parse(js)
        ser.to_frame("v").to_csv(f)
        print(f"  ok {topic}/{kind}/{y}: {len(ser)} días")
        parts.append(ser)
    return pd.concat(parts).sort_index() if parts else pd.Series(dtype=float)


def warning_share(topic):
    tot = fetch_series(topic, "total")
    warn = fetch_series(topic, "warn")
    df = pd.concat([tot.rename("total"), warn.rename("warn")], axis=1).dropna()
    df = df[df["total"] > 0]
    df["share"] = df["warn"] / df["total"]
    base = df["share"].rolling(90, min_periods=30).mean().shift(1)
    sd = df["share"].rolling(90, min_periods=30).std().shift(1)
    df["z"] = (df["share"] - base) / sd
    return df


def fear_greed():
    d = requests.get("https://api.alternative.me/fng/?limit=0&format=json", timeout=30).json()["data"]
    df = pd.DataFrame(d)
    df.index = pd.to_datetime(df["timestamp"].astype(int), unit="s").dt.normalize()
    return df["value"].astype(float).sort_index().rename("fng")


def vix():
    import yfinance as yf
    h = yf.download("^VIX", start="2000-01-01", progress=False, auto_adjust=True)["Close"].squeeze().dropna()
    h.index = pd.to_datetime(h.index).tz_localize(None)
    return h.rename("vix")

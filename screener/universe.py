"""Universos de activos por clase y carga de precios diarios (con caché en data/cache)."""
import io
import time
import warnings
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

warnings.filterwarnings("ignore")
CACHE = Path(__file__).resolve().parent.parent / "data" / "cache"
CACHE.mkdir(parents=True, exist_ok=True)

CRYPTO = ["BTC", "ETH", "BNB", "XRP", "ADA", "DOGE", "SOL", "TRX", "LINK", "DOT", "LTC", "BCH", "AVAX",
          "XLM", "ATOM", "ETC", "UNI", "FIL", "NEAR", "APT", "ARB", "OP", "HBAR", "ICP", "VET", "AAVE",
          "ALGO", "SHIB", "TON", "SUI", "EOS", "XMR", "NEO", "IOTA", "XTZ", "THETA", "MANA", "SAND",
          "AXS", "GRT", "RUNE", "EGLD", "FTM", "LUNC", "FTT"]
FOREX = ["EURUSD", "USDJPY", "GBPUSD", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD", "EURGBP", "EURJPY", "GBPJPY",
         "AUDJPY", "CADJPY", "CHFJPY", "NZDJPY", "EURCHF", "EURAUD", "EURCAD", "EURNZD", "GBPCHF", "GBPAUD",
         "GBPCAD", "GBPNZD", "AUDCAD", "AUDCHF", "AUDNZD", "NZDCAD", "USDSEK", "USDNOK", "USDMXN", "USDZAR"]
# ETFs (no futuros continuos: los saltos de roll de contrato imitarían "caídas" y falsearían la señal)
COMMODITIES = {"GLD": "Oro", "SLV": "Plata", "PPLT": "Platino", "PALL": "Paladio", "CPER": "Cobre", "USO": "Petróleo WTI",
               "BNO": "Petróleo Brent", "UNG": "Gas natural", "UGA": "Gasolina", "DBA": "Agricultura (cesta)",
               "CORN": "Maíz", "WEAT": "Trigo", "SOYB": "Soja", "CANE": "Azúcar", "DBB": "Metales base",
               "DBE": "Energía (cesta)", "DBC": "Commodities (cesta)", "USCI": "Commodities (índice)"}
CLASSES = ("crypto", "forex", "commodities", "stocks")
# costo por lado (comisión+spread+slippage) y periodos/año, por clase
COST = {"crypto": 0.0015, "forex": 0.0002, "commodities": 0.0007, "stocks": 0.0005}
ANN = {"crypto": 365, "forex": 252, "commodities": 252, "stocks": 252}
SPLIT = {"crypto": "2022-01-01", "forex": "2015-01-01", "commodities": "2016-01-01", "stocks": "2013-01-01"}


def _binance(sym, limit=None):
    rows, cursor = [], int(pd.Timestamp("2017-08-01", tz="UTC").timestamp() * 1000)
    while True:
        params = {"symbol": sym, "interval": "1d", "limit": 1000}
        if limit:
            params = {"symbol": sym, "interval": "1d", "limit": limit}
        else:
            params["startTime"] = cursor
        r = requests.get("https://api.binance.com/api/v3/klines", params=params, timeout=30)
        r.raise_for_status()
        b = r.json()
        if not b:
            break
        rows += b
        if limit or len(b) < 1000:
            break
        cursor = b[-1][0] + 86_400_000
        time.sleep(0.15)
    df = pd.DataFrame(rows).iloc[:-1]  # sin el día en curso
    idx = pd.to_datetime(df[0], unit="ms")
    return pd.Series(df[1].astype(float).values, idx), pd.Series(df[4].astype(float).values, idx)


def _yf(tickers, start=None, period=None, retries=2):
    closes, opens = {}, {}
    pending = list(tickers)
    for attempt in range(retries + 1):
        if not pending:
            break
        if attempt:
            time.sleep(4)  # Yahoo limita/corta conexiones: se reintentan solo los que faltan
        for i in range(0, len(pending), 40):
            chunk = pending[i:i + 40]
            kw = dict(start=start) if start else dict(period=period)
            try:
                h = yf.download(chunk, interval='1d', auto_adjust=True, progress=False, group_by='ticker', threads=True, **kw)
            except Exception:
                continue
            for tk in chunk:
                try:
                    c, o = h[tk]['Close'].dropna(), h[tk]['Open'].dropna()
                    if len(c) > 5:
                        closes[tk], opens[tk] = c, o
                except Exception:
                    pass
        pending = [t for t in tickers if t not in closes]
    close, open_ = pd.DataFrame(closes), pd.DataFrame(opens)
    for df in (close, open_):
        df.index = pd.to_datetime(df.index).tz_localize(None)
    return close, open_


def sp500_tickers():
    html = requests.get("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
                        headers={"User-Agent": "Mozilla/5.0"}, timeout=30).text
    return pd.read_html(io.StringIO(html))[0]["Symbol"].str.replace(".", "-", regex=False).tolist()


def names(cls):
    if cls == "commodities":
        return dict(COMMODITIES)
    return {}


def load_history(cls, refresh=False):
    """Histórico diario completo (close, open) de una clase. Reutiliza cachés previas si existen."""
    fc, fo = CACHE / f"scr_{cls}_close.pkl", CACHE / f"scr_{cls}_open.pkl"
    if fc.exists() and not refresh:
        return pd.read_pickle(fc), pd.read_pickle(fo)
    if cls == "crypto":
        legacy = [CACHE / n for n in ("crypto_close.pkl", "crypto_new_close.pkl")]
        if all(p.exists() for p in legacy) and not refresh:
            close = pd.concat([pd.read_pickle(p) for p in legacy], axis=1).sort_index()
            open_ = pd.concat([pd.read_pickle(CACHE / n) for n in ("crypto_open.pkl", "crypto_new_open.pkl")], axis=1).sort_index()
        else:
            o, c = {}, {}
            for coin in CRYPTO:
                try:
                    o[coin], c[coin] = _binance(coin + "USDT")
                except Exception:
                    pass
            close, open_ = pd.DataFrame(c), pd.DataFrame(o)
    elif cls == "stocks":
        if (CACHE / "sp500_close.pkl").exists() and not refresh:
            close, open_ = pd.read_pickle(CACHE / "sp500_close.pkl"), pd.read_pickle(CACHE / "sp500_open.pkl")
        else:
            close, open_ = _yf(sp500_tickers(), start="2000-01-01")
    elif cls == "forex":
        close, open_ = _yf([p + "=X" for p in FOREX], start="2003-01-01")
        close.columns = [c.replace("=X", "") for c in close.columns]
        open_.columns = close.columns
    elif cls == "commodities":
        close, open_ = _yf(list(COMMODITIES), start="2005-01-01")
    else:
        raise ValueError(cls)
    close.to_pickle(fc)
    open_.to_pickle(fo)
    return close, open_


def load_recent(cls, days=200):
    """Últimos ~`days` días para el reporte diario (rápido). Devuelve solo closes."""
    if cls == "crypto":
        c = {}
        for coin in CRYPTO:
            try:
                c[coin] = _binance(coin + "USDT", limit=days + 1)[1]
            except Exception:
                pass
        return pd.DataFrame(c)
    if cls == "stocks":
        close, _ = _yf(sp500_tickers(), period="1y")
        return close
    if cls == "forex":
        close, _ = _yf([p + "=X" for p in FOREX], period="1y")
        close.columns = [c.replace("=X", "") for c in close.columns]
        return close
    close, _ = _yf(list(COMMODITIES), period="1y")
    return close

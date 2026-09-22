"""Descarga OHLC diario completo (no solo cierre) de una o varias acciones, para el bot de rejilla.

Uso: python -m scripts.fetch_stock_ohlc DOC FRT PPL
"""
import sys

import pandas as pd
import yfinance as yf

from screener.universe import CACHE

OUT = CACHE / "grid_stocks_daily"
OUT.mkdir(exist_ok=True)


def fetch(ticker, start="1995-01-01"):
    h = yf.download(ticker, start=start, interval="1d", auto_adjust=True, progress=False)
    if h.empty:
        return None
    df = pd.DataFrame({"open": h["Open"].squeeze(), "high": h["High"].squeeze(),
                       "low": h["Low"].squeeze(), "close": h["Close"].squeeze()})
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df.dropna()


if __name__ == "__main__":
    tickers = sys.argv[1:] or ["DOC"]
    for tk in tickers:
        df = fetch(tk)
        if df is None:
            print(f"{tk}: sin datos")
            continue
        df.to_pickle(OUT / f"{tk}.pkl")
        print(f"{tk}: {len(df):,} sesiones | {df.index[0].date()} -> {df.index[-1].date()}")

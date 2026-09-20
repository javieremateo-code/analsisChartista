"""Descarga y cachea velas OHLCV públicas de Binance (sin necesidad de API key).

Uso:
    python -m data.fetch_binance --symbol BTCUSDT --interval 15m --days 180
"""
import argparse
import time
from pathlib import Path

import pandas as pd
import requests

KLINES_URL = "https://api.binance.com/api/v3/klines"
MAX_LIMIT = 1000
CACHE_DIR = Path(__file__).parent / "cache"

COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trades",
    "taker_buy_base", "taker_buy_quote", "ignore",
]


def _interval_to_ms(interval: str) -> int:
    unit = interval[-1]
    value = int(interval[:-1])
    factor = {"m": 60_000, "h": 3_600_000, "d": 86_400_000}[unit]
    return value * factor


def fetch_klines(symbol: str, interval: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    step_ms = _interval_to_ms(interval) * MAX_LIMIT
    frames = []
    cursor = start_ms
    while cursor < end_ms:
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": cursor,
            "endTime": min(cursor + step_ms, end_ms),
            "limit": MAX_LIMIT,
        }
        resp = requests.get(KLINES_URL, params=params, timeout=30)
        resp.raise_for_status()
        rows = resp.json()
        if not rows:
            break
        frames.append(pd.DataFrame(rows, columns=COLUMNS))
        cursor = rows[-1][0] + _interval_to_ms(interval)
        time.sleep(0.2)  # respetar rate limits de la API pública

    if not frames:
        return pd.DataFrame(columns=COLUMNS)

    df = pd.concat(frames, ignore_index=True)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)
    return df[["open_time", "open", "high", "low", "close", "volume"]].drop_duplicates("open_time")


def fetch_recent(symbol: str, interval: str, limit: int = 300) -> pd.DataFrame:
    """Últimas `limit` velas cerradas, sin caché — para el runner de trading en vivo."""
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    resp = requests.get(KLINES_URL, params=params, timeout=30)
    resp.raise_for_status()
    df = pd.DataFrame(resp.json(), columns=COLUMNS)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)
    # La última vela puede estar todavía abierta: se descarta para no operar con datos incompletos.
    return df[["open_time", "open", "high", "low", "close", "volume"]].iloc[:-1]


def load_or_fetch(symbol: str, interval: str, days: int, refresh: bool = False) -> pd.DataFrame:
    CACHE_DIR.mkdir(exist_ok=True)
    cache_file = CACHE_DIR / f"{symbol}_{interval}_{days}d.parquet"
    if cache_file.exists() and not refresh:
        return pd.read_parquet(cache_file)

    end_ms = int(time.time() * 1000)
    start_ms = end_ms - days * 86_400_000
    df = fetch_klines(symbol, interval, start_ms, end_ms)
    df.to_parquet(cache_file, index=False)
    return df


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="15m")
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    data = load_or_fetch(args.symbol, args.interval, args.days, refresh=args.refresh)
    print(f"{len(data)} velas descargadas para {args.symbol} {args.interval}")
    print(data.tail())

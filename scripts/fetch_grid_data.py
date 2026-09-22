"""Descarga velas horarias completas (OHLC) de BTC y ETH desde 2020, para el backtest del bot de rejilla.

Uso: python -m scripts.fetch_grid_data
"""
from screener.grid_data import load_ohlc_1h

if __name__ == "__main__":
    data = load_ohlc_1h(["BTC", "ETH"], start="2020-01-01")
    for c, df in data.items():
        print(f"{c}: {len(df):,} velas | {df.index[0]} -> {df.index[-1]}")

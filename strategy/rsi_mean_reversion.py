"""Estrategia alternativa: reversión a la media con RSI de periodo corto.

Racional (hipótesis a validar, no una certeza):
  - El primer walk-forward del breakout Donchian dio profit_factor 0.54 en
    BTC/USDT 15m — evidencia de que ahí no hay continuación fuerte tras
    rupturas de canal. La hipótesis alternativa es que a este timeframe el
    precio se comporta más como reversión a la media dentro de un rango que
    como tendencia sostenida.
  - RSI de periodo muy corto (2) para detectar sobreventa/sobrecompra de
    plazo muy corto es la base del método de Larry Connors ("Short Term
    Trading Strategies That Work"), documentado con track record en
    equities — se prueba acá como hipótesis, no se asume que transfiere
    igual a cripto.
  - El filtro de tendencia (SMA larga) evita "agarrar el cuchillo cayendo":
    solo se opera reversión en la dirección del régimen dominante (largos
    en tendencia alcista, cortos en bajista).
  - Stop/target más ajustados que en el breakout (ATR x1 / x1.5): la
    expectativa acá es una reversión rápida, no una tendencia larga.
"""
from dataclasses import dataclass

import pandas as pd

from strategy.indicators import atr as _atr
from strategy.indicators import rsi as _rsi


@dataclass(frozen=True)
class StrategyParams:
    rsi_period: int = 2
    oversold: float = 10.0
    overbought: float = 90.0
    trend_sma_period: int = 200
    atr_period: int = 14
    stop_atr_mult: float = 1.0
    target_atr_mult: float = 1.5


def compute_signals(df: pd.DataFrame, params: StrategyParams = StrategyParams()) -> pd.DataFrame:
    """Misma interfaz de columnas que strategy.donchian_breakout.compute_signals,
    para poder enchufarla en el mismo motor de backtest sin cambios."""
    out = df.copy()

    trend_sma = out["close"].rolling(params.trend_sma_period).mean().shift(1)
    rsi_series = _rsi(out["close"], params.rsi_period).shift(1)
    atr_series = _atr(out, params.atr_period).shift(1)

    out["trend_sma"] = trend_sma
    out["rsi"] = rsi_series
    out["atr"] = atr_series

    prev_close = out["close"].shift(1)
    out["long_entry"] = (rsi_series < params.oversold) & (prev_close > trend_sma)
    out["short_entry"] = (rsi_series > params.overbought) & (prev_close < trend_sma)

    out["long_stop"] = out["close"] - params.stop_atr_mult * atr_series
    out["long_target"] = out["close"] + params.target_atr_mult * atr_series
    out["short_stop"] = out["close"] + params.stop_atr_mult * atr_series
    out["short_target"] = out["close"] - params.target_atr_mult * atr_series

    return out

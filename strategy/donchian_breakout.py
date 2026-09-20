"""Estrategia base: ruptura de canal Donchian con filtro de tendencia y volatilidad.

Racional (documentado, no "porque sí"):
  - El breakout de canal (Donchian) es la regla clásica de trend-following
    (sistema Turtle Traders, décadas de uso documentado en futuros/FX). La idea:
    cuando el precio hace un nuevo máximo/mínimo de N periodos, hay una probabilidad
    razonable de continuación por desequilibrio de oferta/demanda reciente.
  - El filtro de tendencia (EMA larga) busca evitar operar breakouts en contra del
    régimen dominante, que es donde este tipo de sistema falla más seguido
    (mercados laterales generan falsos breakouts en ambas direcciones).
  - El stop/target se define en múltiplos de ATR (volatilidad reciente), no en
    puntos fijos, para que el riesgo por operación sea comparable entre distintos
    regímenes de volatilidad.

Son pocas condiciones objetivas (canal, EMA, ATR) a propósito: cada parámetro
adicional es una oportunidad más de overfitting en el backtest.
"""
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class StrategyParams:
    channel_period: int = 20      # periodos para el canal Donchian
    trend_ema_period: int = 200   # filtro de tendencia
    atr_period: int = 14
    stop_atr_mult: float = 1.5
    target_atr_mult: float = 3.0  # ratio riesgo:beneficio 1:2


def _atr(df: pd.DataFrame, period: int) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def compute_signals(df: pd.DataFrame, params: StrategyParams = StrategyParams()) -> pd.DataFrame:
    """Recibe OHLCV ordenado por tiempo ascendente y devuelve columnas de señal.

    Todas las columnas usan solo información disponible hasta la vela anterior
    (shift(1) en los canales) para evitar look-ahead bias.
    """
    out = df.copy()

    upper_channel = out["high"].rolling(params.channel_period).max().shift(1)
    lower_channel = out["low"].rolling(params.channel_period).min().shift(1)
    trend_ema = out["close"].ewm(span=params.trend_ema_period, adjust=False).mean().shift(1)
    atr = _atr(out, params.atr_period).shift(1)

    out["upper_channel"] = upper_channel
    out["lower_channel"] = lower_channel
    out["trend_ema"] = trend_ema
    out["atr"] = atr

    prev_close = out["close"].shift(1)
    out["long_entry"] = (out["close"] > upper_channel) & (prev_close > trend_ema)
    out["short_entry"] = (out["close"] < lower_channel) & (prev_close < trend_ema)

    out["long_stop"] = out["close"] - params.stop_atr_mult * atr
    out["long_target"] = out["close"] + params.target_atr_mult * atr
    out["short_stop"] = out["close"] + params.stop_atr_mult * atr
    out["short_target"] = out["close"] - params.target_atr_mult * atr

    return out

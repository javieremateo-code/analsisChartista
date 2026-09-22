"""Filtro de régimen (lateral vs tendencia) para gatear el bot de rejilla: mismo ratio de eficiencia de Kaufman
usado para elegir las acciones laterales (research/2026-09-22-bot-de-rejilla-en-acciones-laterales.md), pero
calculado de forma continua sobre una ventana móvil, para poder encender/apagar la rejilla según el régimen
ACTUAL del mercado en vez de una elección fija hecha una sola vez mirando hacia atrás.
"""
import pandas as pd


def rolling_efficiency_ratio(close: pd.Series, window: int) -> pd.Series:
    """0 = puro ruido/lateral, 1 = tendencia pura sin retrocesos, en la ventana de `window` barras."""
    diffs = close.diff().abs()
    total = diffs.rolling(window).sum()
    net = (close - close.shift(window)).abs()
    return net / total


def lateral_gate(close: pd.Series, window: int, threshold: float) -> pd.Series:
    """True = régimen lateral (ER por debajo del umbral): permite operar la rejilla. Antes de tener suficiente
    historia para calcular el ratio, se asume tendencia (False, la opción prudente: no abrir nada sin saber)."""
    er = rolling_efficiency_ratio(close, window)
    return (er <= threshold).fillna(False)

"""Tests del filtro de régimen (ratio de eficiencia móvil) con precios sintéticos."""
import numpy as np
import pandas as pd

from screener.regime import lateral_gate, rolling_efficiency_ratio


def test_efficiency_ratio_distinguishes_trend_from_noise():
    n = 300
    idx = pd.date_range("2024-01-01", periods=n, freq="h")
    trend = pd.Series(np.linspace(100, 200, n), index=idx)          # tendencia pura, sin retrocesos
    noise = pd.Series(100 + np.sin(np.arange(n) / 3) * 5, index=idx)  # oscila sin ir a ningún sitio

    er_trend = rolling_efficiency_ratio(trend, window=50).dropna()
    er_noise = rolling_efficiency_ratio(noise, window=50).dropna()
    assert (er_trend > 0.9).all()   # tendencia pura: ratio cerca de 1
    assert (er_noise < 0.3).mean() > 0.8  # ruido puro: ratio bajo la mayor parte del tiempo


def test_lateral_gate_flags_true_only_below_threshold_and_false_before_enough_history():
    n = 200
    idx = pd.date_range("2024-01-01", periods=n, freq="h")
    close = pd.Series(100 + np.sin(np.arange(n) / 3) * 5, index=idx)
    gate = lateral_gate(close, window=50, threshold=0.3)
    assert not gate.iloc[:49].any()  # sin historia suficiente todavía: por defecto NO se opera (opción prudente)
    assert gate.iloc[60:].mean() > 0.5  # con precio realmente lateral, la puerta pasa a estar abierta la mayor parte del tiempo

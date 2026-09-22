"""Capa de tendencia sobre BTC y ETH (exposición de mercado con control de la caída), pensada para usar el capital que las reglas de rebote dejan parado.

Señal por moneda = media de tres indicadores (precio > SMA100, SMA150, SMA200) evaluados al cierre diario: posición 0, 1/3, 2/3 o 1 durante el día siguiente.
Evidencia (2018-2026, costo 0.15% por cambio): BTC ensamble CAGR +43.6%, Sharpe 1.07, DD -48.6% (comprar y mantener: +33.3%, 0.78, -76.6%);
2022-2026: +27.4% / 0.92 / -29% frente a +12.7% / 0.49 / -67%. Correlación con las reglas de rebote: ~0. Riesgo: es beta de cripto; el peor día
de la capa al 100% fue -22.3% (12/3/2020) y el peor mes -29%; en mercados laterales pierde por cambios de posición (~25 por año).
"""
import numpy as np
import pandas as pd

WINDOWS = (100, 150, 200)
COINS = ("BTC", "ETH")


def trend_signal(px: pd.Series, windows=WINDOWS) -> float:
    """Fracción (0..1) de las medias móviles por debajo del último precio. NaN si no hay historia suficiente."""
    px = px.dropna()
    if len(px) < max(windows):
        return float("nan")
    return float(np.mean([px.iloc[-1] > px.iloc[-n:].mean() for n in windows]))


def trend_targets(close: pd.DataFrame, fraction: float, coins=COINS):
    """{moneda: dict(sig, sig_prev, target_w)}: peso objetivo sobre el capital total = fraction / nº de monedas x señal."""
    out = {}
    for c in coins:
        if c not in close:
            continue
        sig = trend_signal(close[c])
        prev = trend_signal(close[c].iloc[:-1])
        out[c] = dict(sig=sig, sig_prev=prev, target_w=(fraction / len(coins)) * (0.0 if np.isnan(sig) else sig))
    return out

"""Asignación de la cartera del día (compartida por el informe diario y el bot): pesos por riesgo, señal DÉBIL reducida,
filtro y tamaño por probabilidad de rebote (ML), top-N y tope de exposición."""
import numpy as np
import pandas as pd

from .ml_score import ML_HI, ML_MIN, size_multiplier
from .risk import position_weight


def allocate(buy: pd.DataFrame, prof, risk_override=None, ml_min=ML_MIN) -> pd.DataFrame:
    if buy.empty:
        return buy
    buy = buy.copy()
    if "ml" in buy:  # descarta las señales con P(rebote) baja (las que no tienen puntuación se conservan)
        buy = buy[~(buy["ml"].notna() & (buy["ml"] < ml_min))]
        if buy.empty:
            return buy
    buy["loss"] = (-buy["p5"]).clip(lower=1e-4)
    buy["w"] = [position_weight(prof, l, risk_override) for l in buy["loss"]]
    if "fuerza" in buy:
        buy.loc[buy["fuerza"] == "DÉBIL", "w"] *= prof.weak_size_factor
    if "ml" in buy:
        m = buy["ml"].map(lambda p: size_multiplier(p) if pd.notna(p) else 1.0)
        buy["w"] = np.minimum(prof.max_w * ML_HI, buy["w"] * m)
    buy["score"] = buy["ev"] / buy["loss"]
    buy = buy.sort_values("score", ascending=False).head(prof.max_positions)
    tot = buy["w"].sum()
    if tot > prof.max_exposure:
        buy["w"] *= prof.max_exposure / tot
    return buy[buy["w"] > 0]

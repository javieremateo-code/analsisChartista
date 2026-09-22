"""Modelo de probabilidad de rebote para la regla diaria (filtro y tamaño), entrenado SOLO con el pasado.

Una única implementación de las variables se usa en la investigación (walk-forward), en el informe diario y en el bot, para que el
backtest y el uso en vivo calculen exactamente lo mismo. Modelo: gradient boosting poco profundo (defaults fijados a priori, sin tuning).
Uso en la decisión (pre-declarado antes de ver resultados): descartar la señal si P(rebote) < 0.60; tamaño x clip(P/0.70, 0.6, 1.4).
Evidencia (replay día a día, walk-forward trimestral): CAGR +6.7% -> +8.9%, Sharpe 0.83 -> 0.94, 2022-26 +9.5% -> +13.0% (AUC 0.58: mejora modesta).
"""
import pickle

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

from .universe import CACHE

FEATS = ["fg", "fg_chg7", "btc_bull", "btc_dd", "btc_ret3", "n_sig_day", "frac_down", "mkt_ret", "sig_rel", "vr1", "vr3", "dist200", "pos30", "k", "z", "weekend", "liq"]
ENSEMBLE_N = 5  # nº de modelos del conjunto (bootstrap + semillas distintas). Adoptado: mejora CAGR/Sharpe/DD frente a 1 solo modelo (ver research/2026-09-22-cuarta-campana.md)
ML_MIN = 0.60   # umbral de descarte
ML_REF = 0.70   # probabilidad de referencia (≈ tasa base de rebote con z>=3)
ML_LO, ML_HI = 0.6, 1.4  # límites del multiplicador de tamaño
MODEL_F = CACHE / "scr_ml_daily.pkl"


def compute_features(close, qv, fg, ev, n_sig=None):
    """Añade las variables a `ev` (columnas asset, date, k, z). `fg`: serie diaria del Fear&Greed. `n_sig`: nº de monedas en caída fuerte ese
    día (si es None se calcula desde `ev`, que debe contener todos los eventos z>=2 de esa fecha)."""
    idx = close.index
    R = close.pct_change()
    sigma = R.rolling(60).std()
    mats = {"sig_rel": sigma / sigma.rolling(250).median(), "dist200": close / close.rolling(200).mean() - 1, "pos30": close / close.rolling(30).max() - 1,
            "vr1": qv / qv.rolling(20).mean().shift(1), "vr3": qv.rolling(3).mean() / qv.rolling(20).mean().shift(3), "liq": qv.rolling(30).mean()}
    btc = close["BTC"]
    fgs = fg.reindex(idx)
    day = pd.DataFrame({"btc_bull": (btc > btc.rolling(200).mean()).astype(float), "btc_dd": btc / btc.rolling(90).max() - 1, "btc_ret3": btc.pct_change(3),
                        "mkt_ret": R.mean(axis=1), "frac_down": (R < 0).sum(axis=1) / R.notna().sum(axis=1), "fg": fgs, "fg_chg7": fgs - fgs.shift(7)}, index=idx)
    out = ev.copy()
    pos, col = idx.get_indexer(out["date"]), close.columns.get_indexer(out["asset"])
    for k, m in mats.items():
        out[k] = m.values[pos, col]
    for k in day.columns:
        out[k] = day[k].values[pos]
    out["dd90"] = out["btc_dd"]
    if n_sig is None:
        n_sig = out["date"].map(out[out["z"] >= 2].groupby("date").size()).fillna(0).values
    out["n_sig_day"] = n_sig
    out["weekend"] = (pd.to_datetime(out["date"]).dt.dayofweek >= 5).astype(float)
    return out


def train(events_feats, cutoff=None, n_models=ENSEMBLE_N):
    """Conjunto de n_models árboles de boosting (semilla 0 con todos los datos; el resto con remuestreo bootstrap
    y semillas distintas), promediados en score(). Reduce la varianza del modelo único sin cambiar las variables."""
    tr = events_feats[events_feats["z"] >= 2]
    if cutoff is not None:
        tr = tr[tr["date"] < pd.Timestamp(cutoff) - pd.Timedelta(days=1)]
    rng = np.random.default_rng(0)
    models = []
    for seed in range(n_models):
        boot = tr if seed == 0 else tr.iloc[rng.choice(len(tr), size=len(tr), replace=True)]
        m = HistGradientBoostingClassifier(max_depth=3, max_iter=100, learning_rate=0.05, l2_regularization=1.0, random_state=seed)
        m.fit(boot[FEATS], (boot["next"] > 0).astype(int))
        models.append(m)
    return dict(models=models, feats=FEATS, n=len(tr), train_end=str(tr["date"].max().date()), built=str(pd.Timestamp.now().date()))


def get_model(refresh=False, max_age_days=45):
    """Modelo entrenado con todo el histórico disponible (top-100, liquidez >= 5 M). Se reentrena si tiene más de `max_age_days`."""
    if MODEL_F.exists() and not refresh:
        m = pickle.loads(MODEL_F.read_bytes())
        if (pd.Timestamp.now() - pd.Timestamp(m["built"])).days <= max_age_days:
            return m
    from . import crypto100
    from .events import build_events
    from .news import fear_greed
    close, qv = crypto100.clean_universe(*crypto100.load("1d"))
    ev = build_events(close)
    down = ev[(ev["dir"] == "down") & (ev["k"] >= 2) & ev["next"].notna()]
    feats = compute_features(close, qv, fear_greed(), down)
    feats = feats[feats["liq"] >= crypto100.MIN_LIQUIDITY]
    m = train(feats)
    MODEL_F.write_bytes(pickle.dumps(m))
    return m


def score(mdl, feats):
    X = feats[mdl["feats"]]
    return np.mean([m.predict_proba(X)[:, 1] for m in mdl["models"]], axis=0)


def size_multiplier(p):
    return float(np.clip(p / ML_REF, ML_LO, ML_HI))


def score_signals(df, close, qv, fg, mdl):
    """Añade la columna 'ml' a las filas verdict=='COMPRAR' de un DataFrame de decisiones (columnas activo, dir, dias, z, verdict)."""
    df = df.copy()
    df["ml"] = np.nan
    buy = df["verdict"] == "COMPRAR"
    if not buy.any() or mdl is None:
        return df
    n_sig = int(((df["dir"] == "BAJADA") & (df["dias"] >= 2) & (df["z"] >= 2)).sum())
    ev = pd.DataFrame({"asset": df.loc[buy, "activo"].values, "date": close.index[-1], "k": df.loc[buy, "dias"].values, "z": df.loc[buy, "z"].values})
    df.loc[buy, "ml"] = score(mdl, compute_features(close, qv, fg, ev, n_sig=n_sig))
    return df

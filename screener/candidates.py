"""Reglas CANDIDATAS (en observación): hallazgos prometedores pero NO validados.

Candidata 'codicia_mini_bajada' (solo cripto):
  tendencia alcista previa fuerte (>=3 días y >=2σ) + bajada pequeña (<2σ, <=3 días, deshace <66% de la subida)
  + Fear&Greed >= 75 (codicia extrema) -> comprar y mantener 5 días.
Por qué NO está validada: apoya en ~23 episodios independientes, la validación fuera de muestra descansa en 1-2 rallies
(p.ej. 2024) y F&G funciona en parte como filtro de mercado alcista. Debe probarse en paper trading antes de dinero real.
"""
import pickle

import numpy as np
import pandas as pd

from .context import build_context
from .news import fear_greed
from .universe import CACHE, COST, SPLIT, load_history

FG_THR = 75
HOLD = 5
NAME = "codicia_mini_bajada"


def build_candidate_stats():
    close, _ = load_history("crypto")
    last_ok = close.apply(lambda s: s.last_valid_index())
    close = close.loc[:, last_ok >= last_ok.max() - pd.Timedelta(days=15)]
    cost, split = COST["crypto"], pd.Timestamp(SPLIT["crypto"])
    ctx = build_context(close)
    a = ctx[(ctx["trend"] == "up") & (ctx["prev_k"] >= 3) & (ctx["prev_z"] >= 2) & (ctx["cur_z"] < 2)
            & (ctx["retr"] < 0.66) & (ctx["cur_k"] <= 3)].copy()
    a["fg"] = fear_greed().reindex(a["date"]).values
    sel = a[(a["fg"] >= FG_THR) & a[f"f{HOLD}"].notna()]
    net = sel[f"f{HOLD}"] - 2 * cost
    dates = sorted(sel["date"].unique())
    episodes, last = 0, None
    for d in dates:
        if last is None or (d - last).days > 10:
            episodes += 1
        last = d
    oos = sel[sel["date"] >= split]
    return dict(name=NAME, hold=HOLD, fg_thr=FG_THR, n=len(sel), n_dates=len(dates), episodes=episodes,
                mean=float(net.mean()), median=float(net.median()), p_win=float((net > 0).mean()),
                p5=float(net.quantile(0.05)), worst=float(net.min()), n_oos=len(oos),
                mean_oos=float((oos[f"f{HOLD}"] - 2 * cost).mean()) if len(oos) else np.nan)


def get_candidate_stats(refresh=False):
    f = CACHE / f"scr_candidate_{NAME}.pkl"
    if f.exists() and not refresh:
        return pickle.loads(f.read_bytes())
    st = build_candidate_stats()
    f.write_bytes(pickle.dumps(st))
    return st


def matches(state_row, fg_value) -> bool:
    """¿La situación actual del activo cumple la candidata? (usa el estado de screener.events.current_state)."""
    if fg_value is None or not np.isfinite(fg_value):
        return False
    return bool(state_row["dir"] == "down" and state_row["prev_dir"] == "up" and state_row["prev_k"] >= 3
                and state_row["prev_z"] >= 2 and state_row["z"] < 2 and state_row["k"] <= 3
                and state_row["retr"] < 0.66 and fg_value >= FG_THR)

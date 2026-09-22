"""Señales del bot: regla diaria (la misma que el informe) y regla extrema de 4 h. Funciones puras: no tocan red ni estado."""
import pickle
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from screener import crypto100
from screener.allocation import allocate
from screener.ml_score import score_signals
from screener.events import build_events, current_state
from screener.risk import position_weight
from screener.stats import wilson_low
from screener.universe import CACHE
from scripts.daily_report import CAPITULATION_DD, evaluate

Z4H = 6.0  # magnitud mínima de la regla de 4 h (elegida por el estudio: z>=6, mantener 1 vela: Sharpe 0.86, OOS 0.91)
MIN_P_LOW_4H = 0.58
MIN_N_4H = 100


@dataclass
class Signal:
    rule: str          # 'daily' | '4h'
    coin: str
    w: float           # peso sobre el equity
    ref: float         # precio de referencia (último cierre)
    hold_hours: int
    ev: float = 0.0
    meta: dict = field(default_factory=dict)


def daily_signals(c1d, qv, liquidity, stats_d, prof, cost, risk_override=None, model=None, fg=None, ml_min=0.60):
    state = current_state(c1d)
    btc_dd = float(c1d["BTC"].iloc[-1] / c1d["BTC"].iloc[-90:].max() - 1) if "BTC" in c1d else 0.0
    cap = btc_dd <= CAPITULATION_DD
    df = evaluate("crypto", state, stats_d, prof, True, cost, risk_override, cap, liquidity)
    if model is not None and fg is not None:
        try:
            df = score_signals(df, c1d, qv, fg, model)
        except Exception:
            df["ml"] = float("nan")  # sin modelo se opera como antes
    buy = allocate(df[df["verdict"] == "COMPRAR"], prof, risk_override, ml_min)
    out = []
    for _, r in buy.iterrows():
        out.append(Signal("daily", r["activo"], float(r["w"]), float(c1d[r["activo"]].iloc[-1]), 24, float(r["ev"]),
                          dict(z=float(r["z"]), k=int(r["dias"]), fuerza=r.get("fuerza", ""), btc_dd=btc_dd, p=float(r["p"]), ml=float(r.get("ml", float("nan"))))))
    return out


def build_stats_4h(close4h) -> dict:
    ev = build_events(close4h)
    e = ev[(ev["dir"] == "down") & (ev["k"] >= 2) & (ev["z"] >= Z4H) & ev["next"].notna()]
    n, kk = len(e), int((e["next"] > 0).sum())
    return dict(n=n, p=kk / n if n else float("nan"), p_low=wilson_low(kk, n), mean=float(e["next"].mean()) if n else float("nan"),
                p5=float(e["next"].quantile(0.05)) if n else float("nan"), z_min=Z4H, built=str(pd.Timestamp.now().date()))


def get_stats_4h(refresh=False) -> dict:
    f = CACHE / "scr_stats_4h100.pkl"
    if f.exists() and not refresh:
        return pickle.loads(f.read_bytes())
    st = build_stats_4h(crypto100.clean_universe(crypto100.load("4h")[0]))
    f.write_bytes(pickle.dumps(st))
    return st


def four_hour_signals(c4, liquidity, st4, prof, cost, risk_override=None):
    """Caída extrema (z>=6) de 2+ velas de 4 h: comprar al cierre de la vela y mantener 1 vela (4 h)."""
    if not st4 or st4["n"] < MIN_N_4H or st4["p_low"] < MIN_P_LOW_4H or st4["mean"] - 2 * cost <= 0:
        return []
    state = current_state(c4)
    if state.empty:
        return []
    sel = state[(state["dir"] == "down") & (state["k"] >= 2) & (state["z"] >= Z4H)]
    loss = max(-st4["p5"], 1e-4)
    out = []
    for _, r in sel.iterrows():
        if not liquidity.get(r["asset"], 0.0) >= crypto100.MIN_LIQUIDITY:
            continue
        w = position_weight(prof, loss, risk_override)
        out.append(Signal("4h", r["asset"], float(w), float(r["last_close"]), 4, float(st4["mean"] - 2 * cost),
                          dict(z=float(r["z"]), k=int(r["k"]), p=st4["p"])))
    out.sort(key=lambda s: -s.meta["z"])
    return out

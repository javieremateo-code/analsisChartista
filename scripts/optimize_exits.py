"""Palancas de ejecución sobre la regla diaria: objetivos de ganancia (take-profit) y entradas con orden límite, con velas de 1 h.

Para cada evento (z>=3, liquidez >= 5 M) se descargan las 24 velas horarias posteriores al cierre y se simulan:
  - TP: orden límite de venta a +x% (se ejecuta si el máximo horario lo toca; si no, salida a mercado a las 24 h).
  - LÍMITE: orden límite de compra a -d% del cierre, válida 24 h (si no se toca, no hay operación); salida a mercado a las 24 h.
  - Combinaciones. Costos: mercado 0.15%/lado (comisión 0.1% + slippage 0.05%); órdenes límite (maker) solo comisión 0.1%.
El resultado por evento alimenta el replay día a día (las decisiones siguen usando las estadísticas de mercado; solo cambia el P&L).

Uso: python -m scripts.optimize_exits
"""
import warnings
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

from scripts.backtest_execution import fetch_hours
from scripts.optimize_bot import add_walkforward_ml, load_events, report, run
from screener.risk import PROFILES
from screener.universe import CACHE

warnings.filterwarnings("ignore")
FEE, SLIP = 0.001, 0.0005
BASE_COST = 2 * (FEE + SLIP)  # ida y vuelta a mercado = 0.30%


def hourly_paths(ev):
    f = CACHE / "scr_hourly_events100.pkl"
    have = pd.read_pickle(f) if f.exists() else {}
    todo = [(a, d) for a, d in zip(ev["asset"], ev["date"]) if (a, d) not in have]
    if todo:
        print(f"Descargando velas de 1 h para {len(todo)} eventos...", flush=True)
        with ThreadPoolExecutor(max_workers=4) as ex:
            for k, v in ex.map(fetch_hours, todo):
                have[k] = v
        pd.to_pickle(have, f)
    return have


def variant_returns(o, h, l, c, tp=None, limit=None, maker_exit=False):
    """Devuelve (retorno_bruto_equivalente, ejecutada). Costos incluidos como ajuste sobre 0.30%."""
    entry = o[0]
    cost = BASE_COST
    start = 0
    if limit is not None:
        lp = entry * (1 - limit)
        hit = np.where(l <= lp)[0]
        if len(hit) == 0:
            return 0.0, False
        start = hit[0]
        entry = lp
        cost = FEE + (FEE + SLIP)  # entrada maker + salida a mercado
    exit_px = c[-1]
    if tp is not None:
        tpx = entry * (1 + tp)
        idx = np.where(h[start:] >= tpx)[0]
        if len(idx):
            exit_px = tpx
            cost = (FEE if limit is not None else FEE + SLIP) + FEE  # salida maker
    gross = exit_px / entry - 1
    return gross - cost + BASE_COST, True  # el replay resta 0.30%: se compensa para que el costo neto sea el correcto


def main():
    close, down = load_events()
    down = add_walkforward_ml(down)
    prof = PROFILES["balanceado"]
    main_ev = down[down["z"] >= 3]
    hp = hourly_paths(main_ev)
    ok = [(a, d) for a, d in zip(main_ev["asset"], main_ev["date"]) if hp.get((a, d)) is not None]
    print(f"Eventos z>=3 con velas horarias: {len(ok)}/{len(main_ev)}")
    variants = {"mercado 24 h (base)": dict()}
    for tp in (0.04, 0.06, 0.08, 0.12):
        variants[f"TP +{tp:.0%}"] = dict(tp=tp)
    for lim in (0.01, 0.02, 0.03):
        variants[f"límite -{lim:.0%}"] = dict(limit=lim)
        variants[f"límite -{lim:.0%} + TP +8%"] = dict(limit=lim, tp=0.08)
    print("\nPor evento (z>=3, liquidez>=5M): neto medio sobre TODAS las señales / ejecutadas / mediana / peor")
    cols = {}
    for name, kw in variants.items():
        vals, filled = [], []
        for a, d in ok:
            arr = hp[(a, d)]
            r, ex = variant_returns(arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3], **kw)
            vals.append(r - BASE_COST)  # ya neto de costos
            filled.append(ex)
        v, f = np.array(vals), np.array(filled)
        print(f"  {name:<28} neto/señal {v.mean():+.2%} | ejecutadas {f.mean():4.0%} | neto/ejecutada {v[f].mean() if f.any() else float('nan'):+.2%} | mediana {np.median(v[f]) if f.any() else float('nan'):+.2%} | peor {v.min():+.0%}")
        col = pd.Series({(a, d): (val + BASE_COST) for (a, d), val in zip(ok, vals)})
        cols[name] = col
    print("\nREPLAY día a día (perfil balanceado, 2020-2026; decisiones con las estadísticas de mercado, P&L de la variante)")
    base_res = None
    for name, col in cols.items():
        d2 = down.copy()
        d2["alt"] = [col.get((a, d), np.nan) for a, d in zip(d2["asset"], d2["date"])]
        res = report(f"{name}", *run(d2, prof, pnl_col="alt"))
        if base_res is None:
            base_res = res
    print("\nCon filtro+tamaño ML (mlboth) encima de las mejores variantes de ejecución:")
    for name in ("mercado 24 h (base)", "TP +8%", "límite -1%", "límite -2%"):
        d2 = down.copy()
        d2["alt"] = [cols[name].get((a, d), np.nan) for a, d in zip(d2["asset"], d2["date"])]
        report(f"{name} + ML", *run(d2, prof, mode="mlboth", ml_min=0.60, pnl_col="alt"))


if __name__ == "__main__":
    main()

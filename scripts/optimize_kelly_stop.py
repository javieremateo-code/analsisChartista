"""Quinta campaña: dimensionado por Kelly, stop de catástrofe ajustado a volatilidad, señal doble (diaria+4h) y estacionalidad semanal.

G1) Kelly fraccionario usando la probabilidad del modelo (ensemble) y el ratio ganancia/pérdida histórico (walk-forward),
    frente al dimensionado actual (riesgo por operación / pérdida p5).
G2) Stop de catástrofe proporcional a la volatilidad de cada moneda (múltiplo de su desviación diaria de 60d) en vez de -30% fijo.
G3) Señal doble: monedas donde el mismo día se activan la regla diaria Y hay una racha de 4h z>=6 reciente. ¿Rinden mejor?
G4) Estacionalidad: ¿el día de la semana de la señal cambia el resultado?

Uso: python -m scripts.optimize_kelly_stop [G1|G2|G3|G4]
"""
import sys
import warnings

import numpy as np
import pandas as pd

from screener import crypto100
from screener.backtest import perf
from screener.events import build_events
from screener.risk import PROFILES
from scripts.backtest_system import START, SPLIT_T, stats_before
from scripts.optimize_bot import add_walkforward_ml, load_events, report, run

warnings.filterwarnings("ignore")
COST_C = 0.0015


def run_kelly(down, prof, cost=COST_C, cap_thr=-0.25, kelly_mult=0.5, cap_w=None):
    """Igual que run() pero el tamaño = kelly_mult * (p - (1-p)/b), con b (ratio ganancia media/pérdida media)
    calculado SOLO con eventos anteriores (z>=2) en cada trimestre. p = probabilidad del modelo (ensemble)."""
    cap_w = cap_w if cap_w is not None else prof.max_w * 1.5
    start, end = START, down["date"].max()
    days = pd.date_range(start, end, freq="D")
    by_date = {k: v for k, v in down[down["date"] >= start].groupby("date")}
    refresh = set(pd.date_range(start, end, freq="QS")) | {start}
    stats, equity, peak, halted_forever, prev_pnl = {}, 1.0, 1.0, False, 0.0
    b_ratio = 1.5
    daily, ntr = {}, 0
    for day in days:
        if day in refresh:
            stats = stats_before(down, day)
            tr = down[(down["date"] < day) & (down["z"] >= 2) & down["next"].notna()]
            if len(tr) > 100:
                wins, losses = tr.loc[tr["next"] > 0, "next"], -tr.loc[tr["next"] <= 0, "next"]
                if len(wins) > 10 and len(losses) > 10 and losses.mean() > 0:
                    b_ratio = wins.mean() / losses.mean()
        equity *= 1 + prev_pnl
        peak = max(peak, equity)
        halted_forever = halted_forever or equity <= peak * 0.5
        halt = halted_forever or prev_pnl <= -prof.daily_loss_limit
        pnl = 0.0
        cand = by_date.get(day)
        if cand is not None and not halt:
            picks = []
            for r in cand.itertuples():
                s = stats.get(int(r.zb))
                if s is None or r.zb < prof.min_z or s["p_low"] < prof.min_p_low or s["n"] < prof.min_n or s["mean"] - 2 * cost <= 0:
                    continue
                strong = r.dd90 <= cap_thr
                if not strong and prof.weak_size_factor <= 0:
                    continue
                p = r.ml if pd.notna(r.ml) else s["p"]
                if p < 0.60:
                    continue
                f_kelly = p - (1 - p) / b_ratio
                if f_kelly <= 0:
                    continue
                w = min(cap_w, kelly_mult * f_kelly) * (1.0 if strong else prof.weak_size_factor)
                picks.append((f_kelly, w, r))
            picks.sort(key=lambda x: -x[0])
            picks = picks[:prof.max_positions]
            tot = sum(p[1] for p in picks)
            scale = min(1.0, prof.max_exposure / tot) if tot > 0 else 1.0
            for _, w, r in picks:
                pnl += w * scale * (r.next - 2 * cost)
                ntr += 1
        daily[day + pd.Timedelta(days=1)] = pnl
        prev_pnl = pnl
    return pd.Series(daily).sort_index(), ntr


def g1():
    close, down = load_events()
    down = add_walkforward_ml(down)
    prof = PROFILES["balanceado"]
    print("G1) DIMENSIONADO POR KELLY (probabilidad del modelo, ratio ganancia/pérdida walk-forward) — perfil balanceado")
    b = report("actual (riesgo/pérdida p5, tope 10-14%)", *run(down, prof, mode="mlboth", ml_min=0.60))
    for mult in (0.25, 0.5, 0.75, 1.0):
        r = report(f"Kelly x{mult:.2f} (tope {prof.max_w * 1.5:.0%})", *run_kelly(down, prof, kelly_mult=mult))
        ok = r["o_cagr"] > b["o_cagr"] and r["o_sh"] > b["o_sh"] and r["dd"] >= b["dd"] * 1.5 and r["x5"] >= b["x5"]
        print(f"     -> {'ADOPTABLE' if ok else 'no cumple'}")


def g2():
    close, down = load_events()
    down = add_walkforward_ml(down)
    prof = PROFILES["balanceado"]
    print("G2) STOP DE CATÁSTROFE AJUSTADO A VOLATILIDAD (múltiplo de la desviación diaria de 60d) frente al -30% fijo")
    sigma = close.pct_change().rolling(60).std()
    pos, col = close.index.get_indexer(down["date"]), close.columns.get_indexer(down["asset"])
    down["sigma60"] = sigma.values[pos, col]
    # Se necesitan datos horarios para saber si el stop se toca; se aproxima con el peor "next" observado como proxy conservador
    # y se compara el % de eventos que el stop fijo (-30%) vs el ajustado habría recortado, y su efecto sobre el peor caso.
    d3 = down[(down["z"] >= 3) & down["next"].notna() & down["sigma60"].notna()].copy()
    for mult in (5, 7, 10, 15):
        stop = -(mult * d3["sigma60"])
        stop = stop.clip(lower=-0.45, upper=-0.10)  # límites razonables
        hit = d3["next"] <= stop
        capped = np.where(hit, stop, d3["next"])
        print(f"   stop = {mult}x sigma diaria (mediana {stop.median():.1%}): eventos recortados {hit.mean():.1%} | "
              f"retorno medio con stop {capped.mean() - 0.003:+.3%} (sin stop {d3['next'].mean() - 0.003:+.3%}) | peor caso con stop {capped.min():+.1%} (sin stop {d3['next'].min():+.1%})")
    hit30 = d3["next"] <= -0.30
    capped30 = np.where(hit30, -0.30, d3["next"])
    print(f"   stop fijo -30%: eventos recortados {hit30.mean():.1%} | retorno medio {capped30.mean() - 0.003:+.3%} | peor caso {capped30.min():+.1%}")
    print("   Nota: es una aproximación con cierres diarios (sin ver el mínimo intradía real); el hallazgo de scripts/backtest_execution.py con velas horarias ya mostró que el -30% apenas cuesta retorno en 2022-26.")


def g3():
    close4, _ = crypto100.clean_universe(*crypto100.load("4h"))
    close1, down = load_events()
    ev4 = build_events(close4)
    e4 = ev4[(ev4["dir"] == "down") & (ev4["k"] >= 2) & (ev4["z"] >= 6)].copy()
    e4["day"] = e4["date"].dt.normalize()
    strong4h = set(zip(e4["asset"], e4["day"]))
    down = down.copy()
    down["double"] = [(a, d.normalize()) in strong4h or (a, (d - pd.Timedelta(days=1)).normalize()) in strong4h for a, d in zip(down["asset"], down["date"])]
    print(f"G3) SEÑAL DOBLE (diaria + racha extrema de 4h z>=6 el mismo día o la víspera) — {down['double'].sum()} de {len(down)} eventos")
    d3 = down[down["z"] >= 3]
    for lab, m in (("con señal doble", d3["double"]), ("solo diaria", ~d3["double"])):
        g = d3[m]
        gi, go = g[g["date"] < SPLIT_T], g[g["date"] >= SPLIT_T]
        print(f"   {lab:<16} n={len(g):4} P(sube)={( g['next']>0).mean():.0%} neto={g['next'].mean()-0.003:+.2%} | IS n={len(gi)} {(gi['next'].mean()-0.003 if len(gi) else float('nan')):+.2%} | OOS n={len(go)} {(go['next'].mean()-0.003 if len(go) else float('nan')):+.2%}")
    print("   Si 'con señal doble' es claramente mejor y tiene suficientes casos, se podría usar para subir el tamaño en esos casos (igual que ya hace el modelo con P alta).")


def g4():
    close, down = load_events()
    down = add_walkforward_ml(down)
    d3 = down[down["z"] >= 3].copy()
    d3["dow"] = d3["date"].dt.day_name()
    print("G4) ESTACIONALIDAD POR DÍA DE LA SEMANA (día en que se genera la señal, z>=3)")
    for dow, g in d3.groupby("dow"):
        gi, go = g[g["date"] < SPLIT_T], g[g["date"] >= SPLIT_T]
        print(f"   {dow:<10} n={len(g):4} P(sube)={(g['next']>0).mean():.0%} neto={g['next'].mean()-0.003:+.2%} | IS {(gi['next'].mean()-0.003 if len(gi) else float('nan')):+.2%} (n={len(gi)}) | OOS {(go['next'].mean()-0.003 if len(go) else float('nan')):+.2%} (n={len(go)})")
    print("   (con ~15-20 eventos por día de la semana, cualquier diferencia aquí es prácticamente ruido; se muestra solo para descartar un efecto obvio)")


def main():
    what = sys.argv[1:] or ["G1", "G2", "G3", "G4"]
    for w, fn in (("G1", g1), ("G2", g2), ("G3", g3), ("G4", g4)):
        if w in what:
            fn()
            print()


if __name__ == "__main__":
    main()

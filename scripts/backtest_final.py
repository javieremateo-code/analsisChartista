"""Cifras finales del sistema mejorado (cripto, top-100, liquidez >= 5 M): regla diaria con modelo de probabilidad para los 3 perfiles,
más la regla de 4 h (con y sin descuento por retraso) y el capital parado. Replay día a día sin lookahead, costo 0.15%/lado.

Uso: python -m scripts.backtest_final
"""
import numpy as np
import pandas as pd

from scripts.backtest_system import START, SPLIT_T, montecarlo
from scripts.optimize_bot import add_walkforward_ml, load_events, run
from scripts.study_trend_pullback import hold_portfolio
from screener import crypto100
from screener.backtest import perf
from screener.events import build_events
from screener.risk import PROFILES
from screener.trend import WINDOWS

COST = 0.0015
CASH = 0.03 / 365


def show(label, r, eur=1000):
    r = r[r.index >= START]
    p, po = perf(r, 365), perf(r[r.index >= SPLIT_T], 365)
    x5 = perf(r.drop(r.nlargest(5).index), 365)
    rng = np.random.default_rng(3)
    pool, fin, dds = r.values, [], []
    for _ in range(4000):
        path = []
        while len(path) < 365:
            s = rng.integers(0, len(pool) - 10)
            path.extend(pool[s:s + 10])
        eq = np.cumprod(1 + np.array(path[:365]))
        fin.append(eq[-1] - 1)
        dds.append((eq / np.maximum.accumulate(eq) - 1).min())
    fin, dds = np.array(fin), np.array(dds)
    print(f"  {label:<44} CAGR {p['cagr']:+6.1%} Sharpe {p['sharpe']:4.2f} DD {p['dd']:6.1%} | 2022+ {po['cagr']:+6.1%} ({po['sharpe']:.2f}) | sin 5 mejores días {x5['cagr']:+5.1%} | "
          f"1 año 1000 €: mediana {np.median(fin) * eur:+4.0f} €, peor 5% {np.percentile(fin, 5) * eur:+5.0f} €, P(pérdida) {(fin < 0).mean():3.0%}, P(DD>20%) {(dds < -0.2).mean():3.0%}")
    return r


def trend_sleeve(close, coins=("BTC", "ETH"), cost=COST):
    """Retorno diario de la capa de tendencia al 100% (media BTC/ETH); posición = media de señales SMA100/150/200 del día anterior."""
    rets = []
    for c in coins:
        px = close[c]
        sig = pd.concat([(px > px.rolling(n).mean()).astype(float) for n in WINDOWS], axis=1).mean(axis=1)
        pos = sig.shift(1).fillna(0.0)
        rets.append(pos * px.pct_change().fillna(0.0) - cost * pos.diff().abs().fillna(0.0))
    return sum(rets) / len(rets)


def main():
    close, down = load_events()
    down = add_walkforward_ml(down)
    print("REGLA DIARIA con modelo de probabilidad (filtro P>=0.60 + tamaño ∝ P), walk-forward trimestral")
    daily = {}
    for name, prof in PROFILES.items():
        s, n = run(down, prof, mode="mlboth", ml_min=0.60)
        s0, n0 = run(down, prof)
        daily[name] = s
        print(f" [{name}]  operaciones: {n} (sin modelo {n0})")
        show("sin modelo", s0)
        show("con modelo", s)
    c4 = crypto100.clean_universe(crypto100.load("4h")[0])
    e4 = build_events(c4)
    e4 = e4[(e4["dir"] == "down") & (e4["k"] >= 2) & (e4["z"] >= 6) & e4["next"].notna()]
    B = hold_portfolio(e4, c4, COST, 1)
    B = B.groupby(B.index.normalize()).sum()
    idx = pd.date_range(START, daily["balanceado"].index.max(), freq="D")
    A = daily["balanceado"].reindex(idx, fill_value=0.0)
    B = B.reindex(idx, fill_value=0.0)
    print("\nSISTEMA COMPLETO (perfil balanceado)")
    show("A) diaria con modelo", A)
    show("B) A + regla de 4 h (ejecución ideal)", A + B)
    show("C) A + 4 h con retraso (ganancia x0.55)", A + 0.55 * B)
    show("D) C + capital parado al 3%", A + 0.55 * B + CASH)
    show("E) B + capital parado al 3%", A + B + CASH)
    print("\nSISTEMA COMPLETO POR PERFIL: diaria+modelo + 4h (retraso x0.55) + capa de tendencia BTC/ETH (fracción del perfil) + resto del capital en caja al 3%")
    sleeve = trend_sleeve(close).reindex(idx, fill_value=0.0)
    for name, prof in PROFILES.items():
        Ap = daily[name].reindex(idx, fill_value=0.0)
        Bp = hold_portfolio(e4, c4, COST, 1, max_w=prof.max_w)
        Bp = Bp.groupby(Bp.index.normalize()).sum().reindex(idx, fill_value=0.0)
        f = prof.trend_fraction
        print(f" [{name}] capa de tendencia = {f:.0%} del capital")
        show("sin capa de tendencia", Ap + 0.55 * Bp + CASH)
        show("con capa de tendencia", Ap + 0.55 * Bp + (1 - f) * CASH + f * sleeve)
    print("\nLa capa de tendencia es exposición de mercado (correlación ~0 con las reglas de rebote, ~0.73 con BTC): sube el retorno pero también las caídas.")


if __name__ == "__main__":
    main()

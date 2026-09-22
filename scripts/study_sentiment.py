"""Variable 2: ¿había señales (noticias/sentimiento) que anticipaban un recorte durante la subida previa?

Señales de aviso, definidas ANTES de mirar resultados (binarias, medidas durante la tendencia previa):
  - NOTICIAS (GDELT, si está descargado): cuota de artículos con palabras de corrección (crash, bubble, overvalued...)
    sobre el total de artículos del tema, en z-score vs. los 90 días previos. Aviso = z medio durante la subida >= 1.
  - FEAR&GREED (solo cripto, desde 2018): aviso = índice >= 75 (codicia extrema) al final de la subida.
  - VIX (acciones/forex/commodities): aviso = VIX al final de la subida en el 20% inferior de su último año
    (complacencia, "nadie ve riesgo"). Contra-señal: VIX alto = miedo.
Se comparan, sobre dos tipos de situaciones (compra de mini-bajada en tendencia alcista = regla A; y caída fuerte
>=3σ = regla B), los retornos posteriores con aviso vs. sin aviso, dentro y fuera de muestra.

IMPORTANTE: son datos a nivel de MERCADO, no por activo individual, y F&G/VIX son sentimiento, no noticias.

Uso: python -m scripts.study_sentiment
"""
import warnings

import numpy as np
import pandas as pd

from screener.context import base_drift, build_context
from screener.news import CACHE, fear_greed, vix
from screener.universe import COST, SPLIT, load_history

warnings.filterwarnings("ignore")


def welch_t(a, b):
    if len(a) < 30 or len(b) < 30:
        return np.nan
    return (a.mean() - b.mean()) / np.sqrt(a.var() / len(a) + b.var() / len(b))


def by_date(g, col):
    return g.groupby("date")[col].mean()


def compare(sel, flag, base, cost, label, split):
    print(f"  {label}")
    print("     señal        |    n (fechas) | P(sube mañana) | neto 1d | neto 5d | neto 10d | exceso 5d vs deriva | t(aviso vs no) 5d | OOS n / neto 5d")
    for val, nm in ((True, "CON aviso"), (False, "SIN aviso")):
        g = sel[flag.reindex(sel.index) == val]
        if len(g) < 30:
            print(f"     {nm:12} | pocos casos ({len(g)})")
            continue
        go = g[g["date"] >= split]
        other = sel[flag.reindex(sel.index) == (not val)]
        t = welch_t(by_date(g, "f5"), by_date(other, "f5")) if val else np.nan
        print(f"     {nm:12} | {len(g):6} ({g['date'].nunique():4}) | {(g['f1'] > 0).mean():13.1%} | {g['f1'].mean() - 2 * cost:+7.3%} | {g['f5'].mean() - 2 * cost:+7.2%} | {g['f10'].mean() - 2 * cost:+7.2%} | "
              f"{g['f5'].mean() - base[5] - 2 * cost:+8.2%}          | {'' if val is False else f'{t:5.1f}':>8}          | {len(go)} / {go['f5'].mean() - 2 * cost if len(go) else float('nan'):+.2%}")


def main():
    fg, vx = None, None
    try:
        fg = fear_greed()
    except Exception as e:
        print("Fear&Greed no disponible:", e)
    try:
        vx = vix()
    except Exception as e:
        print("VIX no disponible:", e)

    for cls in ("crypto", "stocks", "forex", "commodities"):
        close, _ = load_history(cls)
        last_ok = close.apply(lambda s: s.last_valid_index())
        close = close.loc[:, last_ok >= last_ok.max() - pd.Timedelta(days=15)]
        cost, split = COST[cls], pd.Timestamp(SPLIT[cls])
        base = base_drift(close)
        ctx = build_context(close)
        ctx = ctx[(ctx["trend"] == "up") & (ctx["prev_k"] >= 3) & (ctx["prev_z"] >= 2)].reset_index(drop=True)
        A = ctx[(ctx["cur_z"] < 2) & (ctx["retr"] < 0.66) & (ctx["cur_k"] <= 3)]
        B = ctx[(ctx["cur_z"] >= 3) & (ctx["cur_k"] >= 2)]
        print("\n" + "#" * 110)
        print(f"##### {cls.upper()} | tendencias alcistas previas: {len(ctx):,} | regla A (mini-bajada): {len(A):,} | regla B (caída fuerte): {len(B):,}")

        flags = {}
        # fecha de fin de la subida previa = fecha del evento - cur_k días hábiles; para simplificar se mide en el día del evento
        if cls == "crypto" and fg is not None:
            fgv = fg.reindex(ctx["date"]).values
            flags["FEAR&GREED >= 75 (codicia extrema) en el momento de la bajada"] = pd.Series(fgv >= 75, index=ctx.index)
        if vx is not None and cls != "crypto":
            roll = vx.rolling(252, min_periods=126).apply(lambda x: (x[:-1] < x[-1]).mean(), raw=True)  # percentil del VIX en su último año
            pv = roll.reindex(ctx["date"], method="ffill").values
            flags["VIX en el 20% inferior de su último año (complacencia)"] = pd.Series(pv <= 0.20, index=ctx.index)
            flags["VIX en el 20% superior de su último año (miedo)"] = pd.Series(pv >= 0.80, index=ctx.index)
        nf = CACHE / f"news_{cls}.pkl"
        if nf.exists():
            nz = pd.read_pickle(nf)["z"]
            zz = nz.reindex(ctx["date"], method="ffill").values
            flags["NOTICIAS: cuota de avisos de corrección elevada (z >= 1)"] = pd.Series(zz >= 1, index=ctx.index)
        else:
            print("  (serie de noticias GDELT de esta clase aún no descargada)")

        for name, flag in flags.items():
            print(f"\n  >>> {name}  (aviso presente en {flag.mean():.0%} de las situaciones)")
            for rule, sel in (("Regla A: comprar la mini-bajada de la tendencia alcista", A), ("Regla B: comprar la caída fuerte (>=3σ)", B)):
                compare(sel, flag, base, cost, rule, split)


if __name__ == "__main__":
    main()

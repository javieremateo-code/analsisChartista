"""Variable 1: ¿compensa comprar tras la mini-bajada de una tendencia alcista (y mantener)? ¿Cuántos días sigue?

Para cada clase de activos (cripto, forex, commodities, acciones):
  1) Rejilla: magnitud del retroceso (σ) x cuánto de la tendencia previa deshizo (retr), sobre tendencias fuertes
     (>=3 días y >=2σ). Métricas: P(el día siguiente reanuda), retorno neto a 1/5/10 días, exceso sobre la deriva, t (por fecha).
  2) Cuántos días se reanuda la tendencia.
  3) Backtest de cartera de reglas pre-declaradas con distintos periodos de mantenimiento (1, 3, 5, 10 días).

Uso: python -m scripts.study_trend_pullback
"""
import warnings

import numpy as np
import pandas as pd

from screener.backtest import perf
from screener.context import HORIZONS, base_drift, build_context
from screener.universe import ANN, CLASSES, COST, SPLIT, load_history

warnings.filterwarnings("ignore")
ZB = [(0, 1, "<1σ"), (1, 2, "1-2σ"), (2, 3, "2-3σ"), (3, 99, "≥3σ")]
RB = [(0, 0.33, "<33%"), (0.33, 0.66, "33-66%"), (0.66, 1.0, "66-100%"), (1.0, 99, "≥100%")]


def tstat_by_date(sel, col):
    g = sel.groupby("date")[col].mean().dropna()
    return g.mean() / (g.std() / np.sqrt(len(g))) if len(g) > 10 and g.std() > 0 else np.nan


def hold_portfolio(sel, close, cost, h, max_w=0.10, side=1):
    """Cartera con mantenimiento de h días. side=+1 largo, side=-1 corto (sin funding/préstamo: optimista)."""
    idx = close.index
    R = np.nan_to_num(close.pct_change().values)
    pos = idx.get_indexer(sel["date"])
    col = close.columns.get_indexer(sel["asset"])
    ok0 = (pos >= 0) & (col >= 0)
    pos, col = pos[ok0], col[ok0]
    n_day = pd.Series(pos).groupby(pos).transform("size").values
    w = np.minimum(max_w, 1.0 / n_day) / h
    daily = np.zeros(len(idx))
    for j in range(1, h + 1):
        p = pos + j
        ok = p < len(idx)
        np.add.at(daily, p[ok], side * w[ok] * R[p[ok], col[ok]])
    np.add.at(daily, np.clip(pos + 1, 0, len(idx) - 1), -2 * cost * w)
    return pd.Series(daily, idx)


def main():
    for cls in CLASSES:
        close, _ = load_history(cls)
        last_ok = close.apply(lambda s: s.last_valid_index())
        close = close.loc[:, last_ok >= last_ok.max() - pd.Timedelta(days=15)]
        cost, ann, split = COST[cls], ANN[cls], pd.Timestamp(SPLIT[cls])
        ctx = build_context(close)
        base = base_drift(close)
        r_all = close.pct_change().values[1:]
        p_up = float((r_all[np.isfinite(r_all)] > 0).mean())
        print("\n" + "#" * 118)
        print(f"##### {cls.upper()} | {close.shape[1]} activos | {len(ctx):,} situaciones | costo {cost:.3%}/lado | OOS desde {split.date()}")
        print(f"Deriva incondicional (compra cualquier día): 1d {base[1]:+.3%} | 5d {base[5]:+.2%} | 10d {base[10]:+.2%} | P(día sube) {p_up:.1%}")

        up = ctx[(ctx["trend"] == "up") & (ctx["prev_k"] >= 3) & (ctx["prev_z"] >= 2)]
        print(f"\nTENDENCIA ALCISTA previa (>=3 días y >=2σ) seguida de bajada: {len(up):,} situaciones")
        print("Retroceso (σ) x % de la tendencia deshecha -> n | P(sube mañana) | neto 1d | neto 5d | neto 10d | exceso 1d | t(1d) | días que sigue (media)")
        for zlo, zhi, zl in ZB:
            for rlo, rhi, rl in RB:
                g = up[(up["cur_z"] >= zlo) & (up["cur_z"] < zhi) & (up["retr"] >= rlo) & (up["retr"] < rhi)]
                if len(g) < 100:
                    continue
                net = {h: g[f"f{h}"].mean() - 2 * cost for h in (1, 5, 10)}
                print(f"  retroceso {zl:>5} | deshecho {rl:>8}: n={len(g):6} | P={ (g['f1'] > 0).mean():5.1%} | {net[1]:+7.3%} | {net[5]:+7.2%} | {net[10]:+7.2%} | "
                      f"{g['f1'].mean() - base[1] - 2 * cost:+7.3%} | t={tstat_by_date(g.assign(x=g['f1'] - base[1] - 2 * cost), 'x'):5.1f} | {g['run_after'].mean():.2f}d")

        print("\nMismo análisis por longitud de la tendencia previa (retroceso < 2σ):")
        small = up[up["cur_z"] < 2]
        for klo, khi, kl in ((3, 4, "3 días"), (4, 6, "4-5 días"), (6, 99, "6+ días")):
            g = small[(small["prev_k"] >= klo) & (small["prev_k"] < khi)]
            if len(g) < 100:
                continue
            print(f"  tendencia {kl:>8}: n={len(g):6} | P(sube mañana) {(g['f1'] > 0).mean():5.1%} | neto 1d {g['f1'].mean() - 2 * cost:+.3%} | 5d {g['f5'].mean() - 2 * cost:+.2%} | 10d {g['f10'].mean() - 2 * cost:+.2%} | sigue {g['run_after'].mean():.2f}d | P(sigue>=3d) {(g['run_after'] >= 3).mean():.1%}")

        # ---- tendencia bajista previa seguida de rebote (venta en corto de la tendencia): solo informativo ----
        dn = ctx[(ctx["trend"] == "down") & (ctx["prev_k"] >= 3) & (ctx["prev_z"] >= 2) & (ctx["cur_z"] < 2) & (ctx["retr"] < 0.66)]
        if len(dn) >= 100:
            print(f"\nTENDENCIA BAJISTA previa + rebote pequeño (<2σ, <66%): n={len(dn):,} | corto 1d {dn['f1'].mean() - 2 * cost:+.3%} | 5d {dn['f5'].mean() - 2 * cost:+.2%} | 10d {dn['f10'].mean() - 2 * cost:+.2%} | P(sigue bajando mañana) {(dn['f1'] > 0).mean():.1%}")

        # ---- backtest de cartera con periodos de mantenimiento ----
        rules = {
            "A: comprar mini-bajada en tendencia alcista (cur<2σ, retr<66%, cur_k<=3)":
                up[(up["cur_z"] < 2) & (up["retr"] < 0.66) & (up["cur_k"] <= 3)],
            "B: caída fuerte (>=3σ, 2+ días) tras subida — regla validada": ctx[(ctx["trend"] == "up") & (ctx["cur_z"] >= 3) & (ctx["cur_k"] >= 2)],
            "B1: B y la caída borra >=100% de la subida previa": ctx[(ctx["trend"] == "up") & (ctx["cur_z"] >= 3) & (ctx["cur_k"] >= 2) & (ctx["retr"] >= 1)],
            "B2: B y la caída borra <100% (tendencia previa sigue viva)": ctx[(ctx["trend"] == "up") & (ctx["cur_z"] >= 3) & (ctx["cur_k"] >= 2) & (ctx["retr"] < 1)],
        }
        bh = close.pct_change().mean(axis=1).fillna(0)
        po = perf(bh[bh.index >= split], ann)
        print(f"\nBACKTEST de cartera (peso máx 10%, sin apalancamiento) — referencia cesta OOS: CAGR {po['cagr']:+.1%} Sharpe {po['sharpe']:.2f}")
        print("regla | mantener | n | neto/trade | P(gana) | CAGR total | Sharpe | maxDD | OOS CAGR | OOS Sharpe")
        for name, sel in rules.items():
            if len(sel) < 100:
                print(f"  {name}: pocos casos ({len(sel)})")
                continue
            for h in (1, 3, 5, 10):
                s2 = sel[sel[f"f{h}"].notna()]
                d = hold_portfolio(s2, close, cost, h)
                pt, po_ = perf(d, ann), perf(d[d.index >= split], ann)
                netv = s2[f"f{h}"] - 2 * cost
                print(f"  {name[:2]:>3} h={h:>2}d n={len(s2):6} | {netv.mean():+7.3%} | {(netv > 0).mean():4.0%} | CAGR {pt['cagr']:+6.1%} | Sharpe {pt['sharpe']:5.2f} | DD {pt['dd']:6.1%} | OOS {po_['cagr']:+6.1%} | {po_['sharpe']:5.2f}")
            print(f"      ({name})")


if __name__ == "__main__":
    main()

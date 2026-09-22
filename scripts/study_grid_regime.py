"""Bot de rejilla + filtro de régimen (opción 3): apaga las compras nuevas y el recentrado cuando el mercado
está en tendencia fuerte (ratio de eficiencia de Kaufman móvil por encima de un umbral), dejando siempre activo
el cortafuegos y las ventas de lo que ya se tenía. Objetivo: atacar directamente la causa del rechazo anterior
(el desgaste del recentrado durante tendencias sostenidas) en vez de depender de haber elegido un activo que se
quede quieto para siempre.

Disciplina anti-sobreajuste: la ventana y el umbral del filtro se eligen SOLO con datos anteriores a 2023 (mejor
Sharpe), y el resultado se evalúa después en 2023-2026, nunca al revés.

Uso: python -m scripts.study_grid_regime
"""
import numpy as np
import pandas as pd

from screener.grid import GridConfig, simulate_grid
from screener.grid_data import load_ohlc_1h
from screener.regime import lateral_gate

SPLIT = pd.Timestamp("2023-01-01")
WINDOWS = (24 * 7, 24 * 14, 24 * 21, 24 * 30)   # 7, 14, 21, 30 días en horas
THRESHOLDS = (0.08, 0.12, 0.18, 0.25)
BASE_CFG = dict(range_pct=0.12, n_grids=20, fee=0.001, stop_buffer=0.03, panic_slippage=0.005, recenter_days=21, pause_days=7)


def perf(equity, ann=24 * 365):
    if len(equity) < 10:
        return dict(ret=np.nan, cagr=np.nan, dd=np.nan, sharpe=np.nan)
    r = equity.pct_change().fillna(0.0)
    dd = (equity / equity.cummax() - 1).min()
    yrs = (equity.index[-1] - equity.index[0]).days / 365.25
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / yrs) - 1 if yrs > 0 else np.nan
    sharpe = r.mean() / r.std() * np.sqrt(ann) if r.std() > 0 else np.nan
    return dict(ret=equity.iloc[-1] / equity.iloc[0] - 1, cagr=cagr, dd=dd, sharpe=sharpe)


def line(label, equity):
    p = perf(equity)
    print(f"  {label:<34} ret total {p['ret']:+8.1%} | CAGR {p['cagr']:+7.1%} | Sharpe {p['sharpe']:5.2f} | DD máx {p['dd']:7.1%}")
    return p


def main():
    data = load_ohlc_1h(["BTC", "ETH"])
    for coin, df in data.items():
        print(f"\n{'=' * 100}\n{coin}: {len(df):,} velas | {df.index[0].date()} -> {df.index[-1].date()}\n{'=' * 100}")

        res_base = simulate_grid(df, 1000.0, GridConfig(**BASE_CFG))
        print("Referencia (rejilla SIN filtro de régimen, ya rechazada):")
        line("  sin filtro", res_base.equity)

        print("\nBarrido ventana x umbral (Sharpe dentro de muestra, hasta 2023):")
        results = {}
        for w in WINDOWS:
            for th in THRESHOLDS:
                gate = lateral_gate(df["close"], w, th)
                res = simulate_grid(df, 1000.0, GridConfig(**BASE_CFG), gate=gate)
                p_is = perf(res.equity[res.equity.index < SPLIT])
                p_os = perf(res.equity[res.equity.index >= SPLIT])
                p_all = perf(res.equity)
                pct_on = gate.mean()
                results[(w, th)] = dict(res=res, p_is=p_is, p_os=p_os, p_all=p_all, pct_on=pct_on)
                print(f"  ventana {w // 24:2d}d, umbral {th:.2f}: % tiempo abierto {pct_on:5.0%} | IS Sharpe {p_is['sharpe']:5.2f} CAGR {p_is['cagr']:+6.1%} | "
                      f"OOS Sharpe {p_os['sharpe']:5.2f} CAGR {p_os['cagr']:+6.1%} DD {p_os['dd']:6.1%} | total CAGR {p_all['cagr']:+6.1%} DD {p_all['dd']:6.1%}")

        best_key = max(results, key=lambda k: results[k]["p_is"]["sharpe"] if not np.isnan(results[k]["p_is"]["sharpe"]) else -9)
        w, th = best_key
        best = results[best_key]
        print(f"\nMejor combinación por Sharpe DENTRO de muestra: ventana {w // 24}d, umbral {th:.2f}")
        line("  Resultado completo (con esa combinación)", best["res"].equity)
        print(f"  Dentro de muestra:  CAGR {best['p_is']['cagr']:+.1%} Sharpe {best['p_is']['sharpe']:.2f} DD {best['p_is']['dd']:.1%}")
        print(f"  Fuera de muestra:   CAGR {best['p_os']['cagr']:+.1%} Sharpe {best['p_os']['sharpe']:.2f} DD {best['p_os']['dd']:.1%}")
        print(f"  Cortafuegos saltó {len(best['res'].stops)} veces | % del tiempo con la puerta abierta {best['pct_on']:.0%}")
        b = perf(res_base.equity[res_base.equity.index >= SPLIT])
        print(f"  [ref.] rejilla SIN filtro, mismo tramo OOS: CAGR {b['cagr']:+.1%} Sharpe {b['sharpe']:.2f} DD {b['dd']:.1%}")
        bh = df["close"] / df["close"].iloc[0] * 1000
        p_bh = perf(bh[bh.index >= SPLIT])
        print(f"  [ref.] comprar y mantener, mismo tramo OOS: CAGR {p_bh['cagr']:+.1%} Sharpe {p_bh['sharpe']:.2f} DD {p_bh['dd']:.1%}")

        ok = (best["p_os"]["cagr"] or -9) > 0 and (best["p_os"]["cagr"] or -9) > (b["cagr"] or -9) and (best["p_os"]["sharpe"] or -9) > (b["sharpe"] or -9)
        print(f"  Criterio (mejora sobre la rejilla sin filtro, positivo fuera de muestra): {'CUMPLE' if ok else 'NO CUMPLE'}")


if __name__ == "__main__":
    main()

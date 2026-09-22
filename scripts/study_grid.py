"""Backtest honesto del bot de rejilla: BTC y ETH, 2020-2026, con y sin cortafuegos, y desglose explícito por los
peores crashes históricos (marzo 2020, mayo 2021, LUNA mayo 2022, FTX noviembre 2022). Criterio de adopción fijado
antes de ver resultados: debe dar retorno neto positivo en el periodo completo, con cortafuegos activo, sin ninguna
caída superior al 25% en ningún crash individual, y el resultado debe sostenerse tanto en 2020-2022 como en 2023-2026.

Uso: python -m scripts.study_grid
"""
import numpy as np
import pandas as pd

from screener.grid import GridConfig, simulate_grid
from screener.grid_data import load_ohlc_1h

CRASHES = {
    "marzo 2020 (Covid)": ("2020-03-01", "2020-04-01"),
    "mayo 2021 (crash de China)": ("2021-05-10", "2021-05-25"),
    "mayo 2022 (LUNA/Terra)": ("2022-05-05", "2022-05-20"),
    "junio 2022 (Celsius/3AC)": ("2022-06-10", "2022-06-20"),
    "noviembre 2022 (FTX)": ("2022-11-06", "2022-11-16"),
}


def perf(equity):
    if len(equity) < 10:
        return dict(ret=np.nan, cagr=np.nan, dd=np.nan, sharpe=np.nan)
    r = equity.pct_change().fillna(0.0)
    dd = (equity / equity.cummax() - 1).min()
    yrs = (equity.index[-1] - equity.index[0]).days / 365.25
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / yrs) - 1 if yrs > 0 else np.nan
    sharpe = r.mean() / r.std() * np.sqrt(24 * 365) if r.std() > 0 else np.nan
    return dict(ret=equity.iloc[-1] / equity.iloc[0] - 1, cagr=cagr, dd=dd, sharpe=sharpe)


def line(label, equity):
    p = perf(equity)
    print(f"  {label:<38} ret total {p['ret']:+8.1%} | CAGR {p['cagr']:+7.1%} | Sharpe {p['sharpe']:5.2f} | DD máx {p['dd']:7.1%}")
    return p


def main():
    data = load_ohlc_1h(["BTC", "ETH"])
    for coin, df in data.items():
        print(f"\n{'=' * 100}\n{coin}: {len(df):,} velas horarias | {df.index[0].date()} -> {df.index[-1].date()}\n{'=' * 100}")
        bh = df["close"] / df["close"].iloc[0] * 1000

        print("\nComparación con y sin cortafuegos (range=12%, 20 grids, comisión 0.1%, recentrado cada 21 días):")
        cfg_stop = GridConfig(range_pct=0.12, n_grids=20, fee=0.001, stop_buffer=0.03, panic_slippage=0.005, recenter_days=21, pause_days=7)
        cfg_nostop = GridConfig(range_pct=0.12, n_grids=20, fee=0.001, stop_buffer=99.0, recenter_days=21, pause_days=7)  # cortafuegos desactivado (buffer imposible de alcanzar)
        res_stop = simulate_grid(df, 1000.0, cfg_stop)
        res_nostop = simulate_grid(df, 1000.0, cfg_nostop)
        line("Comprar y mantener", bh)
        line("Rejilla CON cortafuegos", res_stop.equity)
        line("Rejilla SIN cortafuegos (para ver el riesgo real)", res_nostop.equity)
        print(f"  Cortafuegos saltó {len(res_stop.stops)} veces en {(df.index[-1]-df.index[0]).days} días | operaciones totales: {len(res_stop.trades)} (compras: {(res_stop.trades['side']=='buy').sum()}, ventas: {(res_stop.trades['side']=='sell').sum()}, cortafuegos: {(res_stop.trades['side']=='stop').sum()}, recentrados: {(res_stop.trades['side']=='recenter').sum()})")

        print("\nDesglose por crash (equity CON cortafuegos, evolución durante la ventana +/- contexto):")
        for name, (a, b) in CRASHES.items():
            win = res_stop.equity[(res_stop.equity.index >= pd.Timestamp(a) - pd.Timedelta(days=3)) & (res_stop.equity.index <= pd.Timestamp(b) + pd.Timedelta(days=3))]
            if len(win) < 5:
                print(f"  {name:<28}: sin datos en ese rango")
                continue
            chg = win.iloc[-1] / win.iloc[0] - 1
            dd = (win / win.cummax() - 1).min()
            stops_here = [s for s in res_stop.stops if pd.Timestamp(a) - pd.Timedelta(days=3) <= s <= pd.Timestamp(b) + pd.Timedelta(days=3)]
            print(f"  {name:<28}: variación de la rejilla {chg:+7.2%} | caída máxima en la ventana {dd:7.2%} | cortafuegos saltó {len(stops_here)} vez/veces")

        print("\nDentro (2020-2022) vs fuera de muestra (2023-2026):")
        split = pd.Timestamp("2023-01-01")
        line("  2020-2022", res_stop.equity[res_stop.equity.index < split])
        line("  2023-2026", res_stop.equity[res_stop.equity.index >= split])

        print("\nSensibilidad al ancho del rango y al nº de grids:")
        for rp in (0.08, 0.12, 0.18, 0.25):
            r = simulate_grid(df, 1000.0, GridConfig(range_pct=rp, n_grids=20, fee=0.001, stop_buffer=0.03, panic_slippage=0.005, recenter_days=21, pause_days=7))
            line(f"  range_pct={rp:.0%}", r.equity)
        for ng in (10, 20, 40):
            r = simulate_grid(df, 1000.0, GridConfig(range_pct=0.12, n_grids=ng, fee=0.001, stop_buffer=0.03, panic_slippage=0.005, recenter_days=21, pause_days=7))
            line(f"  n_grids={ng}", r.equity)

        print("\nEstrés de comisiones (misma configuración base):")
        for fee in (0.0005, 0.001, 0.0015, 0.002):
            r = simulate_grid(df, 1000.0, GridConfig(range_pct=0.12, n_grids=20, fee=fee, stop_buffer=0.03, panic_slippage=0.005, recenter_days=21, pause_days=7))
            line(f"  comisión {fee:.2%}/operación", r.equity)


if __name__ == "__main__":
    main()

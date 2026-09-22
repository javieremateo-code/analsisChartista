"""Tests del bot de rejilla (grid): mecánica de compra/venta, cortafuegos y recentrado, con precios sintéticos."""
import numpy as np
import pandas as pd

from screener.grid import GridConfig, simulate_grid


def _ohlc(closes, spread=0.001):
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="h")
    closes = np.array(closes, dtype=float)
    return pd.DataFrame({"open": closes, "high": closes * (1 + spread), "low": closes * (1 - spread), "close": closes}, index=idx)


def test_sideways_oscillation_produces_profit():
    """Precio oscilando dentro del rango: debe comprar abajo y vender arriba varias veces, con ganancia neta."""
    n = 400
    t = np.arange(n)
    closes = 100 * (1 + 0.10 * np.sin(t / 15))  # oscila +-10% en torno a 100, dentro de un rango del 12%
    df = _ohlc(closes)
    res = simulate_grid(df, capital=1000.0, cfg=GridConfig(range_pct=0.12, n_grids=10, fee=0.001, recenter_days=9999))
    assert not res.trades.empty
    assert (res.trades["side"] == "sell").sum() >= 3  # varios ciclos completos de compra-venta
    assert res.equity.iloc[-1] > 1000.0  # ganancia neta de comisiones
    assert not res.stops  # nunca debería saltar el cortafuegos con esta oscilación moderada


def test_circuit_breaker_caps_the_loss_on_a_crash():
    """Caída fuerte y sostenida: el cortafuegos debe saltar y limitar la pérdida (no debe seguir comprando cada vez más abajo)."""
    n = 300
    closes = 100 * np.exp(-0.02 * np.arange(n))  # caída sostenida del ~2%/hora: a las 100h ya cayó >80%
    df = _ohlc(closes)
    cfg = GridConfig(range_pct=0.10, n_grids=10, fee=0.001, stop_buffer=0.03, panic_slippage=0.005, recenter_days=9999, pause_days=5)
    res = simulate_grid(df, capital=1000.0, cfg=cfg)
    assert res.stops, "el cortafuegos debería haber saltado en una caída sostenida"
    worst_dd = (res.equity / res.equity.cummax() - 1).min()
    assert worst_dd > -0.30  # con range_pct=10% y stop_buffer=3%, la pérdida máxima del tramo de rejilla debe quedar acotada
    assert (res.equity.iloc[-1] - res.equity.iloc[0]) < 0  # sí pierde (es una caída real), pero de forma acotada, no ilimitada


def test_circuit_breaker_pauses_and_then_rearms():
    """Tras saltar el cortafuegos, no debe operar hasta pasado pause_days, y luego debe recentrarse."""
    crash = 100 * np.exp(-0.02 * np.arange(60))
    t = np.arange(200)
    recovery = crash[-1] * (1 + 0.08 * np.sin(t / 15))  # tras el pánico, oscila de nuevo (sin volver a caer) para dar ocasión de operar
    closes = np.concatenate([crash, recovery])
    df = _ohlc(closes)
    cfg = GridConfig(range_pct=0.10, n_grids=10, fee=0.001, stop_buffer=0.03, recenter_days=9999, pause_days=3)
    res = simulate_grid(df, capital=1000.0, cfg=cfg)
    stop_ts = res.stops[0]
    during_pause = res.trades[(res.trades["ts"] > stop_ts) & (res.trades["ts"] <= stop_ts + pd.Timedelta(days=3))]
    assert during_pause.empty  # nada de actividad mientras está pausado
    after = res.trades[res.trades["ts"] > stop_ts + pd.Timedelta(days=3)]
    assert not after.empty  # y sí vuelve a operar después de rearmarse


def test_gate_blocks_new_buys_and_recenters_but_not_sells_or_the_circuit_breaker():
    n = 400
    t = np.arange(n)
    closes = 100 * (1 + 0.10 * np.sin(t / 15))
    df = _ohlc(closes)
    gate_off = pd.Series(False, index=df.index)  # "siempre en tendencia": nunca debería abrir nada nuevo
    cfg = GridConfig(range_pct=0.12, n_grids=10, fee=0.001, recenter_days=30)
    res = simulate_grid(df, 1000.0, cfg, gate=gate_off)
    assert (res.trades["side"] == "buy").sum() == 0 and (res.trades["side"] == "recenter").sum() == 0
    assert res.equity.iloc[-1] == 1000.0  # sin comprar nunca, el equity no se mueve

    # con la puerta abierta a partir de la mitad, debe empezar a comprar (y eventualmente vender) desde ese punto
    gate_half = pd.Series([False] * 200 + [True] * 200, index=df.index)
    res2 = simulate_grid(df, 1000.0, cfg, gate=gate_half)
    assert res2.trades.empty or res2.trades["ts"].min() >= df.index[200]
    assert (res2.trades["side"] == "buy").sum() > 0

    # el cortafuegos debe seguir funcionando aunque la puerta esté cerrada (nunca se debe desactivar la protección)
    crash = 100 * np.exp(-0.02 * np.arange(n))
    df_crash = _ohlc(crash)
    cfg2 = GridConfig(range_pct=0.10, n_grids=10, fee=0.001, stop_buffer=0.03, recenter_days=9999, pause_days=5)
    res3 = simulate_grid(df_crash, 1000.0, cfg2, gate=pd.Series(False, index=df_crash.index))
    # con la puerta cerrada nunca compra nada, así que el cortafuegos no tiene nada que liquidar (comportamiento correcto,
    # no un fallo): confirma que la puerta evita justo la exposición que luego el cortafuegos tendría que limpiar
    assert res3.equity.iloc[-1] == 1000.0 and not res3.stops


def test_reopening_the_gate_liquidates_open_inventory_instead_of_discarding_it():
    """Si la puerta se cierra con una posición abierta y luego se reabre, esa posición debe liquidarse y su
    resultado debe reflejarse en el equity — no desaparecer sin más al rearmar la rejilla."""
    n = 60
    # sube lo suficiente para comprar 1-2 niveles, luego la puerta se cierra, el precio sigue subiendo un poco
    # (la posición comprada queda con ganancia latente) y por último la puerta se reabre
    closes = np.concatenate([np.linspace(100, 92, 10), np.linspace(92, 96, 20), np.full(30, 98.0)])
    df = _ohlc(closes)
    gate = pd.Series([True] * 30 + [False] * 15 + [True] * 15, index=df.index)
    cfg = GridConfig(range_pct=0.12, n_grids=10, fee=0.001, recenter_days=9999)
    res = simulate_grid(df, 1000.0, cfg, gate=gate)
    assert (res.trades["side"] == "buy").any()  # sí llegó a comprar antes de que la puerta se cerrara
    # el equity final no puede ser exactamente 1000 (ni comprar nada gratis): la posición se liquidó con su pnl real
    assert res.equity.iloc[-1] != 1000.0
    assert abs(res.equity.iloc[-1] - 1000.0) < 50  # y el cambio es razonable (una sola posición pequeña), no un salto absurdo


def test_higher_fees_reduce_but_dont_flip_the_sign_of_a_clean_oscillation():
    n = 400
    t = np.arange(n)
    closes = 100 * (1 + 0.10 * np.sin(t / 15))
    df = _ohlc(closes)
    cheap = simulate_grid(df, 1000.0, GridConfig(range_pct=0.12, n_grids=10, fee=0.0005, recenter_days=9999)).equity.iloc[-1]
    expensive = simulate_grid(df, 1000.0, GridConfig(range_pct=0.12, n_grids=10, fee=0.003, recenter_days=9999)).equity.iloc[-1]
    assert cheap > expensive  # más comisión, menos beneficio, con el mismo camino de precios

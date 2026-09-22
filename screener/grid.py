"""Simulación de un bot de rejilla (grid trading) con cortafuegos obligatorio y recentrado periódico.

Mecánica (la misma que usan los grid bots reales, p.ej. el de Binance): se reparte el rango [low, high] en
`n_grids` intervalos con espaciado geométrico (% constante entre líneas). Cada intervalo tiene su propio capital
asignado. Cuando el precio TOCA la línea inferior de un intervalo vacío, se compra (orden límite, comisión maker);
cuando luego toca la línea superior, se vende, capturando el espaciado menos comisiones. Se usa el máximo y el
mínimo de cada vela horaria (no solo el cierre) para no perderse cruces intrabar.

Cortafuegos (obligatorio, no opcional): si el precio cae por debajo de `low * (1 - stop_buffer)`, se vende TODO
a mercado (con slippage de pánico) y la rejilla queda parada `pause_days` antes de recentrarse. Sin esto, un grid
es "recoger céntimos delante de una apisonadora": funciona bien hasta que el mercado rompe con fuerza en una
dirección y entonces pierde de golpe lo acumulado en semanas.
"""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class GridConfig:
    range_pct: float = 0.12       # medio ancho del rango alrededor del precio central (12% arriba y abajo)
    n_grids: int = 20             # nº de intervalos (a más, más operaciones pero más pequeñas cada una)
    fee: float = 0.001            # comisión por operación (orden límite; 0.1% = tier estándar de Binance)
    stop_buffer: float = 0.03     # el cortafuegos salta si el precio cae más allá de low*(1-stop_buffer)
    panic_slippage: float = 0.005  # deslizamiento extra al liquidar a mercado en el cortafuegos
    recenter_days: int = 21       # cada cuántos días se recentra la rejilla en torno al precio actual
    pause_days: int = 7           # días de pausa tras saltar el cortafuegos antes de volver a armar la rejilla
    capital_fraction: float = 1.0  # fracción del capital asignado a la rejilla que se reparte entre los intervalos


@dataclass
class GridResult:
    equity: pd.Series
    trades: pd.DataFrame
    stops: list = field(default_factory=list)  # fechas en las que saltó el cortafuegos


def _make_grid(center, cfg):
    low, high = center * (1 - cfg.range_pct), center * (1 + cfg.range_pct)
    lines = low * (high / low) ** (np.arange(cfg.n_grids + 1) / cfg.n_grids)
    return lines


def simulate_grid(ohlc: pd.DataFrame, capital: float, cfg: GridConfig = GridConfig()) -> GridResult:
    """ohlc: DataFrame horario con columnas open, high, low, close, ordenado por fecha."""
    equity = capital
    equity_series = {}
    trades = []
    stops = []
    lines = None
    holding = None   # array bool: holding[i] = True si se compró en la línea i y se espera vender en la i+1
    entry_px = None  # precio real de compra en cada intervalo (con comisión ya aplicada al coste)
    per_grid_cap = None
    active = True
    resume_at = None
    last_recenter = None
    last_price = None  # precio de referencia para exigir un cruce REAL (evita comprar de golpe líneas ya
                       # por debajo del precio del bar, o vender líneas ya por encima, al (re)armar)

    def arm(center, ts):
        nonlocal lines, holding, entry_px, per_grid_cap, last_recenter, active, last_price
        lines = _make_grid(center, cfg)
        holding = np.zeros(cfg.n_grids, dtype=bool)
        entry_px = np.zeros(cfg.n_grids)
        per_grid_cap = (equity * cfg.capital_fraction) / cfg.n_grids
        last_recenter = ts
        last_price = center
        active = True

    arm(ohlc["close"].iloc[0], ohlc.index[0])

    for ts, row in ohlc.iterrows():
        if not active:
            if resume_at is not None and ts >= resume_at:
                arm(row["close"], ts)
            equity_series[ts] = equity
            continue

        lo, hi = row["low"], row["high"]

        # cortafuegos: el precio ha roto el rango por abajo con margen -> liquidar todo a mercado y pausar
        if lo <= lines[0] * (1 - cfg.stop_buffer):
            panic_px = lines[0] * (1 - cfg.stop_buffer) * (1 - cfg.panic_slippage)
            for i in range(cfg.n_grids):
                if holding[i]:
                    qty = per_grid_cap / entry_px[i]
                    proceeds = qty * panic_px * (1 - cfg.fee)
                    pnl = proceeds - per_grid_cap
                    equity += pnl
                    trades.append(dict(ts=ts, side="stop", grid=i, price=panic_px, pnl=pnl))
                    holding[i] = False
            stops.append(ts)
            active = False
            resume_at = ts + pd.Timedelta(days=cfg.pause_days)
            equity_series[ts] = equity
            continue

        # recentrado periódico (si el rango sigue vivo pero ha pasado mucho tiempo, para no quedar descolgado)
        if (ts - last_recenter).days >= cfg.recenter_days:
            # se liquida el inventario abierto al precio de cierre (coste de recentrar, no un pánico)
            for i in range(cfg.n_grids):
                if holding[i]:
                    qty = per_grid_cap / entry_px[i]
                    proceeds = qty * row["close"] * (1 - cfg.fee)
                    pnl = proceeds - per_grid_cap
                    equity += pnl
                    trades.append(dict(ts=ts, side="recenter", grid=i, price=row["close"], pnl=pnl))
            arm(row["close"], ts)
            equity_series[ts] = equity
            continue

        # cruces REALES dentro de la vela: la línea debe haber quedado por el lado contrario antes de este bar
        # (si no, cualquier línea ya por debajo/encima del precio al (re)armar se "compraría"/"vendería" de golpe,
        # sin que el precio la haya cruzado de verdad — ver tests/test_grid.py)
        for i in range(cfg.n_grids):
            if not holding[i] and last_price > lines[i] and lo <= lines[i]:
                qty = (per_grid_cap * (1 - cfg.fee)) / lines[i]
                entry_px[i] = lines[i] / (1 - cfg.fee)  # coste efectivo por unidad incluyendo la comisión de entrada
                holding[i] = True
                trades.append(dict(ts=ts, side="buy", grid=i, price=lines[i], pnl=0.0))
            elif holding[i] and last_price < lines[i + 1] and hi >= lines[i + 1]:
                qty = per_grid_cap / entry_px[i]
                proceeds = qty * lines[i + 1] * (1 - cfg.fee)
                pnl = proceeds - per_grid_cap
                equity += pnl
                trades.append(dict(ts=ts, side="sell", grid=i, price=lines[i + 1], pnl=pnl))
                holding[i] = False
        last_price = row["close"]
        equity_series[ts] = equity

    return GridResult(pd.Series(equity_series), pd.DataFrame(trades), stops)

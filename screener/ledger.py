"""Registro de operaciones EN PAPEL (ledger) para medir en vivo si el sistema se comporta como el backtest.

El informe diario, con --record, asume que sigues sus recomendaciones: registra las compras al último cierre y, cuando toca,
las cierra al cierre siguiente (1 día; la candidata en observación, 5 días). Aplica el freno diario y el kill switch de drawdown.
Guarda el estado en state/ledger.json (editable a mano si no ejecutaste alguna operación). Es idempotente: ejecutar el informe
varias veces el mismo día no duplica operaciones.
"""
import json
from pathlib import Path

import pandas as pd

STATE = Path(__file__).resolve().parent.parent / "state" / "ledger.json"


def load(capital0: float, path: Path = None) -> dict:
    path = path or STATE  # se resuelve al llamar (así se puede redirigir STATE en pruebas)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return dict(capital0=capital0, equity=capital0, peak=capital0, killed=False, open=[], closed=[], last_record=None)


def save(led: dict, path: Path = None) -> None:
    path = path or STATE
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(led, indent=2, ensure_ascii=False), encoding="utf-8")


def open_position(led, cls, asset, rule, entry_date, entry_price, eur, hold_days, stop_price, paper_only=False) -> bool:
    key = f"{cls}:{asset}:{rule}:{entry_date}"
    if any(p["id"] == key for p in led["open"] + led["closed"]):
        return False  # ya registrada (idempotente)
    led["open"].append(dict(id=key, cls=cls, asset=asset, rule=rule, entry_date=str(entry_date), entry_price=float(entry_price), eur=float(eur),
                            hold_days=int(hold_days), stop_price=float(stop_price), paper_only=bool(paper_only)))
    return True


def due_positions(led, last_dates: dict, prices: dict):
    """Posiciones que toca cerrar hoy: han pasado >= hold_days desde la entrada y hay precio de cierre disponible."""
    out = []
    for p in led["open"]:
        last = last_dates.get(p["cls"])
        px = prices.get((p["cls"], p["asset"]))
        if last is None or px is None:
            continue
        if (pd.Timestamp(last) - pd.Timestamp(p["entry_date"])).days >= p["hold_days"]:
            out.append((p, float(px), float(px) / p["entry_price"] - 1))
    return out


def realized_pnl(pos, ret, cost) -> float:
    return pos["eur"] * (ret - 2 * cost)


def close_positions(led, due, exit_date, cost_by_cls) -> float:
    """Cierra las posiciones vencidas, actualiza equity y devuelve el P&L realizado (en €) de las que NO son solo-papel-de-observación."""
    total = 0.0
    for p, px, ret in due:
        pnl = realized_pnl(p, ret, cost_by_cls[p["cls"]])
        led["open"] = [q for q in led["open"] if q["id"] != p["id"]]
        led["closed"].append({**p, "exit_date": str(exit_date), "exit_price": px, "ret": ret, "pnl_eur": pnl})
        if not p.get("paper_only"):  # las de observación (candidata) no afectan al equity ni al freno
            led["equity"] += pnl
            total += pnl
    led["peak"] = max(led["peak"], led["equity"])
    return total


def check_kill(led, max_drawdown: float) -> bool:
    if led["equity"] <= led["peak"] * (1 - max_drawdown):
        led["killed"] = True
    return led["killed"]


def summary(led) -> dict:
    cl = led["closed"]
    n = len(cl)
    return dict(n=n, equity=led["equity"], ret=led["equity"] / led["capital0"] - 1,
                win=(sum(1 for c in cl if c["pnl_eur"] > 0) / n) if n else float("nan"),
                avg=(sum(c["ret"] for c in cl) / n) if n else float("nan"), n_open=len(led["open"]),
                dd=led["equity"] / led["peak"] - 1)

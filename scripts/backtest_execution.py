"""Realismo de ejecución de la regla de cripto con velas de 1 HORA sobre cada evento histórico.

La regla compra al cierre diario (00:00 UTC) y vende 24 h después. En la práctica el informe se ejecuta minutos u horas después.
Este script mide, sobre cada evento (caída >=z de 2+ días), qué pasa si:
  - se entra con retraso (0, 1, 2, 4, 8 horas tras el cierre) y se sale igualmente a las 24 h del cierre;
  - se añade un STOP de protección durante las 24 h (5, 8, 10, 15, 20%), con slippage adicional en el stop.
Costos por lado 0.15% (como el resto del proyecto).

Uso: python -m scripts.backtest_execution
"""
import warnings
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import requests

from screener.events import build_events
from screener.universe import CACHE, COST, SPLIT, load_history

warnings.filterwarnings("ignore")
CACHE_F = CACHE / "scr_hourly_events.pkl"
COST_C = COST["crypto"]
SPLIT_T = pd.Timestamp(SPLIT["crypto"])
STOP_SLIP = 0.003  # slippage adicional al ejecutarse un stop en una caída rápida


def fetch_hours(args):
    coin, date = args
    start = int((pd.Timestamp(date) + pd.Timedelta(days=1)).tz_localize("UTC").timestamp() * 1000)
    for _ in range(3):
        try:
            r = requests.get("https://api.binance.com/api/v3/klines", params=dict(symbol=coin + "USDT", interval="1h", startTime=start, limit=24), timeout=30)
            b = r.json()
            if isinstance(b, list) and len(b) == 24:
                return (coin, date), np.array([[float(x[1]), float(x[2]), float(x[3]), float(x[4])] for x in b])
            if isinstance(b, list):
                return (coin, date), None
        except Exception:
            pass
    return (coin, date), None


def load_events():
    close, _ = load_history("crypto")
    last_ok = close.apply(lambda s: s.last_valid_index())
    close = close.loc[:, last_ok >= last_ok.max() - pd.Timedelta(days=15)]
    ev = build_events(close)
    e = ev[(ev["dir"] == "down") & (ev["k"] >= 2) & (ev["z"] >= 2) & ev["next"].notna()].copy()
    e = e[e["date"] <= close.index[-3]]
    return e.reset_index(drop=True)


def get_hourly(e):
    have = pd.read_pickle(CACHE_F) if CACHE_F.exists() else {}
    todo = [(a, d) for a, d in zip(e["asset"], e["date"]) if (a, d) not in have]
    print(f"Eventos: {len(e)} | ya en caché: {len(e) - len(todo)} | a descargar: {len(todo)}", flush=True)
    if todo:
        with ThreadPoolExecutor(max_workers=4) as ex:
            for i, (k, v) in enumerate(ex.map(fetch_hours, todo)):
                have[k] = v
                if (i + 1) % 400 == 0:
                    print(f"  descargados {i + 1}/{len(todo)}", flush=True)
        pd.to_pickle(have, CACHE_F)
    return have


def evaluate(e, hourly, delay, stop=None):
    out = []
    for a, d, z in zip(e["asset"], e["date"], e["z"]):
        h = hourly.get((a, d))
        if h is None:
            out.append(np.nan)
            continue
        entry = h[delay, 0]
        exit_ = h[23, 3]
        gross = exit_ / entry - 1
        if stop is not None:
            low = h[delay:, 2].min()
            if low <= entry * (1 - stop):
                gross = -stop - STOP_SLIP
        out.append(gross - 2 * COST_C)
    return pd.Series(out, index=e.index)


def summary(x, label):
    x = x.dropna()
    if len(x) == 0:
        print(f"  {label}: sin datos")
        return
    print(f"  {label:<32} n={len(x):4} | neto medio {x.mean():+.2%} | mediana {x.median():+.2%} | P(gana) {(x > 0).mean():4.0%} | p5 {x.quantile(0.05):+.1%} | peor {x.min():+.1%}")


def main():
    e = load_events()
    hourly = get_hourly(e)
    ok = e[[hourly.get((a, d)) is not None for a, d in zip(e["asset"], e["date"])]]
    print(f"Con datos horarios completos: {len(ok)}/{len(e)}")
    for name, sub in (("REGLA PRINCIPAL z>=3", ok[ok["z"] >= 3]), ("AMPLIO z>=2 (perfil agresivo)", ok)):
        for period, s2 in (("todo", sub), ("IS 2017-21", sub[sub["date"] < SPLIT_T]), ("OOS 2022-26", sub[sub["date"] >= SPLIT_T])):
            print(f"\n=== {name} | {period} | {len(s2)} eventos ===")
            print(" Retraso de entrada (salida a las 24 h del cierre):")
            for delay in (0, 1, 2, 4, 8):
                summary(evaluate(s2, hourly, delay), f"entrada +{delay} h")
            print(" Stop de protección durante las 24 h (entrada inmediata):")
            summary(evaluate(s2, hourly, 0), "sin stop")
            for stop in (0.05, 0.08, 0.10, 0.15, 0.20):
                summary(evaluate(s2, hourly, 0, stop), f"stop -{stop:.0%}")
    # distribución horaria del rebote: ¿cuánto del retorno de 24 h ocurre en las primeras horas?
    sub = ok[ok["z"] >= 3]
    path = np.array([hourly[(a, d)][:, 3] / hourly[(a, d)][0, 0] - 1 for a, d in zip(sub["asset"], sub["date"])])
    print("\nRetorno medio acumulado desde el cierre (00:00 UTC) por hora, regla principal: " + " ".join(f"{h + 1}h:{path[:, h].mean():+.1%}" for h in (0, 1, 2, 3, 5, 7, 11, 15, 19, 23)))


if __name__ == "__main__":
    main()

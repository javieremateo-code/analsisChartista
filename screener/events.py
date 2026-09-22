"""Eventos de racha: para cada activo y día, racha actual de subida/bajada, movimiento acumulado y su
magnitud normalizada por volatilidad (z), y el retorno del día siguiente.

z = |movimiento acumulado| / (sigma_diaria_previa * sqrt(k)), con sigma = desviación típica de los
retornos diarios de los 60 días ANTERIORES al inicio de la racha (sin mirar el futuro). Permite comparar
un -25% en una cripto con un -1.5% en un par de divisas.
"""
import numpy as np
import pandas as pd

SIGMA_WINDOW = 60
ZB_MAX = 4


def _streaks(flag):
    s = np.zeros(len(flag), dtype=int)
    run = 0
    for i in range(len(flag)):
        run = run + 1 if flag[i] else 0
        s[i] = run
    return s


def build_events(close: pd.DataFrame, min_len: int = 300) -> pd.DataFrame:
    out = []
    for name in close.columns:
        s = close[name].dropna()
        if len(s) < min_len:
            continue
        v = s.values.astype(float)
        n = len(v)
        ret = np.full(n, np.nan)
        ret[1:] = v[1:] / v[:-1] - 1
        sigma = pd.Series(ret).rolling(SIGMA_WINDOW).std().shift(1).values
        nxt = np.full(n, np.nan)
        nxt[:-1] = ret[1:]
        r0 = np.nan_to_num(ret, nan=0.0)
        for direction in ("up", "down"):
            st = _streaks((r0 > 0) if direction == "up" else (r0 < 0))
            idx = np.where(st >= 1)[0]
            k = st[idx]
            start = idx - k
            cum = v[idx] / v[start] - 1
            sg = sigma[start + 1]
            with np.errstate(invalid="ignore", divide="ignore"):
                z = np.abs(cum) / (sg * np.sqrt(k))
            ok = np.isfinite(z) & (sg > 0)
            out.append(pd.DataFrame({"asset": name, "date": s.index[idx][ok], "dir": direction, "k": k[ok],
                                     "cum": cum[ok], "z": z[ok], "next": nxt[idx][ok]}))
    ev = pd.concat(out, ignore_index=True)
    ev["kc"] = ev["k"].clip(upper=5)
    ev["zb"] = np.floor(ev["z"]).clip(upper=ZB_MAX).astype(int)  # 4 = "4σ o más" (agrupa la cola, poco poblada)
    return ev


def current_state(close: pd.DataFrame) -> pd.DataFrame:
    """Estado actual (último cierre) de cada activo: dirección y longitud de racha, % acumulado, z, sigma diaria."""
    rows = []
    for name in close.columns:
        s = close[name].dropna()
        if len(s) < SIGMA_WINDOW + 10:
            continue
        v = s.values.astype(float)
        ret = np.full(len(v), np.nan)
        ret[1:] = v[1:] / v[:-1] - 1
        last = ret[-1]
        if not np.isfinite(last) or last == 0:
            continue
        direction = "up" if last > 0 else "down"
        k = 0
        for r in ret[::-1]:
            if np.isfinite(r) and ((r > 0) if direction == "up" else (r < 0)):
                k += 1
            else:
                break
        start = len(v) - 1 - k
        sg = pd.Series(ret).iloc[max(0, start - SIGMA_WINDOW + 1):start + 1].std()
        if not np.isfinite(sg) or sg <= 0:
            continue
        cum = v[-1] / v[start] - 1
        sigma_now = pd.Series(ret).iloc[-SIGMA_WINDOW:].std()

        # racha PREVIA (tendencia anterior, de signo contrario) y cuánto de ella ha deshecho la racha actual
        opposite = (lambda r: r < 0) if direction == "up" else (lambda r: r > 0)
        prev_k, j = 0, start
        while j >= 1 and np.isfinite(ret[j]) and opposite(ret[j]):
            prev_k += 1
            j -= 1
        prev_cum = prev_z = retr = np.nan
        if prev_k >= 1:
            ps = start - prev_k + 1
            sgp = pd.Series(ret).iloc[max(0, ps - SIGMA_WINDOW):ps].std()
            prev_cum = v[start] / v[j] - 1
            if np.isfinite(sgp) and sgp > 0:
                prev_z = abs(prev_cum) / (sgp * np.sqrt(prev_k))
            retr = abs(cum) / abs(prev_cum) if prev_cum != 0 else np.nan
        rows.append(dict(asset=name, date=s.index[-1], dir=direction, k=k, cum=cum, z=abs(cum) / (sg * np.sqrt(k)),
                         sigma=sigma_now, last_close=v[-1], prev_dir=("down" if direction == "up" else "up") if prev_k else "",
                         prev_k=prev_k, prev_cum=prev_cum, prev_z=prev_z, retr=retr))
    st = pd.DataFrame(rows)
    if len(st):
        st["kc"] = st["k"].clip(upper=5)
        st["zb"] = np.floor(st["z"]).clip(upper=ZB_MAX).astype(int)
    return st

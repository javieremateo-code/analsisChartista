"""Variable 1: contexto de tendencia previa.

Para cada día t se describe la racha ACTUAL (la mini-bajada o mini-subida) y la racha ANTERIOR de signo contrario
(la tendencia previa), y se miden los retornos posteriores en la dirección de esa tendencia previa:
  - trend: dirección de la tendencia previa ('up' = venía subiendo y ahora hay una bajada)
  - prev_k / prev_z: días y magnitud (σ) de la tendencia previa
  - cur_k / cur_z: días y magnitud (σ) de la racha actual (el retroceso)
  - retr: cuánto de la tendencia previa ha deshecho el retroceso (1.0 = lo borró entero)
  - f1..f10: retorno a 1,2,3,5,10 días, en la dirección de la tendencia previa (positivo = la tendencia se reanuda)
  - run_after: cuántos días seguidos se reanuda la tendencia a partir del día siguiente (0 = sigue el retroceso)
"""
import numpy as np
import pandas as pd

from .events import SIGMA_WINDOW

HORIZONS = (1, 2, 3, 5, 10)


def build_context(close: pd.DataFrame, min_len: int = 300, max_cur_k: int = 5) -> pd.DataFrame:
    out = []
    for name in close.columns:
        s = close[name].dropna()
        if len(s) < min_len:
            continue
        v = s.values.astype(float)
        n = len(v)
        ret = np.full(n, np.nan)
        ret[1:] = v[1:] / v[:-1] - 1
        sg = pd.Series(ret).rolling(SIGMA_WINDOW).std().shift(1).values
        sign = np.zeros(n, dtype=np.int8)
        sign[1:] = np.sign(np.nan_to_num(ret[1:]))
        rs = np.zeros(n, dtype=int)
        for i in range(1, n):
            rs[i] = rs[i - 1] if (sign[i] != 0 and i > 1 and sign[i] == sign[i - 1]) else i
        # racha consecutiva hacia delante (días seguidos de subida / bajada a partir de j)
        ahead_up = np.zeros(n + 1, dtype=int)
        ahead_dn = np.zeros(n + 1, dtype=int)
        for j in range(n - 1, 0, -1):
            ahead_up[j] = ahead_up[j + 1] + 1 if sign[j] > 0 else 0
            ahead_dn[j] = ahead_dn[j + 1] + 1 if sign[j] < 0 else 0
        i_all = np.arange(2, n)
        i_all = i_all[sign[i_all] != 0]
        e = rs[i_all] - 1                       # último día de la racha anterior
        valid = (e >= 2) & (sign[np.clip(e, 0, n - 1)] == -sign[i_all])
        i_all, e = i_all[valid], e[valid]
        ps = rs[e]                              # primer día de la racha anterior
        valid = ps >= 1
        i_all, e, ps = i_all[valid], e[valid], ps[valid]
        cur_k = i_all - rs[i_all] + 1
        keep = cur_k <= max_cur_k
        i_all, e, ps, cur_k = i_all[keep], e[keep], ps[keep], cur_k[keep]
        cs = rs[i_all]
        prev_k = cs - ps
        prev_cum = v[e] / v[ps - 1] - 1
        cur_cum = v[i_all] / v[cs - 1] - 1
        with np.errstate(invalid="ignore", divide="ignore"):
            z_prev = np.abs(prev_cum) / (sg[ps] * np.sqrt(prev_k))
            z_cur = np.abs(cur_cum) / (sg[cs] * np.sqrt(cur_k))
            retr = np.abs(cur_cum) / np.abs(prev_cum)
        tsign = sign[e].astype(int)             # +1 = tendencia previa alcista
        d = dict(asset=name, date=s.index[i_all], trend=np.where(tsign > 0, "up", "down"), prev_k=prev_k,
                 prev_z=z_prev, cur_k=cur_k, cur_z=z_cur, retr=retr)
        for h in HORIZONS:
            f = np.full(len(i_all), np.nan)
            ok = i_all + h < n
            f[ok] = (v[i_all[ok] + h] / v[i_all[ok]] - 1) * tsign[ok]
            d[f"f{h}"] = f
        nxt = np.clip(i_all + 1, 0, n)
        ra = np.where(tsign > 0, ahead_up[nxt], ahead_dn[nxt]).astype(float)
        ra[i_all + 1 >= n] = np.nan
        d["run_after"] = ra
        df = pd.DataFrame(d)
        ok = np.isfinite(df["prev_z"]) & np.isfinite(df["cur_z"]) & np.isfinite(df["retr"])
        out.append(df[ok])
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def base_drift(close: pd.DataFrame) -> dict:
    """Retorno medio incondicional a h días (comparación 'sin condición')."""
    return {h: float(np.nanmean((close.shift(-h) / close - 1).values)) for h in HORIZONS}

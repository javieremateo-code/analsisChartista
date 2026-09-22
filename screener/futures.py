"""Futuros de commodities (contratos continuos de Yahoo Finance) y cestas de acciones relacionadas.

AVISO de calidad de datos: el contrato continuo 'front-month' salta al renovar contrato (roll): la diferencia entre el
contrato que vence y el siguiente aparece como un salto de precio que NO es una ganancia/pérdida real. Se audita en
scripts/study_futures.py y se compara con ETFs.
"""
import warnings

import numpy as np
import pandas as pd
import yfinance as yf

from .universe import CACHE

warnings.filterwarnings("ignore")
FUTURES = {
    "CL=F": "Petróleo WTI", "BZ=F": "Petróleo Brent", "NG=F": "Gas natural", "HO=F": "Gasóleo calefacción", "RB=F": "Gasolina",
    "GC=F": "Oro", "SI=F": "Plata", "HG=F": "Cobre", "PL=F": "Platino", "PA=F": "Paladio",
    "ZC=F": "Maíz", "ZW=F": "Trigo", "ZS=F": "Soja", "ZM=F": "Harina de soja", "ZL=F": "Aceite de soja", "ZO=F": "Avena", "ZR=F": "Arroz",
    "KC=F": "Café", "SB=F": "Azúcar", "CC=F": "Cacao", "CT=F": "Algodón", "OJ=F": "Zumo de naranja",
    "LE=F": "Ganado vacuno", "GF=F": "Ganado de engorde", "HE=F": "Cerdo magro",
}
# (futuro, nombre de la cesta, signo esperado del efecto sobre las acciones, tickers)
BASKETS = [
    ("CL=F", "Petroleras (E&P)", +1, ["XOM", "CVX", "COP", "OXY", "EOG", "DVN", "FANG", "APA", "MRO", "HES", "PXD", "CTRA"]),
    ("CL=F", "Refinadoras", +1, ["MPC", "VLO", "PSX"]),
    ("CL=F", "Servicios petroleros", +1, ["SLB", "HAL", "BKR"]),
    ("CL=F", "Aerolíneas (consumidoras)", -1, ["DAL", "UAL", "LUV", "AAL", "ALK"]),
    ("NG=F", "Productoras de gas", +1, ["EQT", "RRC", "AR", "SWN", "CHK", "EXE", "CTRA"]),
    ("GC=F", "Mineras de oro", +1, ["NEM", "GOLD", "AEM", "KGC", "HMY", "AU", "GFI"]),
    ("GC=F", "Joyerías", +1, ["SIG", "MOV", "TIF", "FOSL", "BRLT"]),
    ("SI=F", "Mineras de plata", +1, ["PAAS", "HL", "CDE", "AG", "WPM"]),
    ("HG=F", "Mineras de cobre", +1, ["FCX", "SCCO", "TECK", "HBM"]),
    ("ZW=F", "Agroindustria / fertilizantes", +1, ["ADM", "BG", "DE", "CTVA", "MOS", "CF", "NTR"]),
    ("ZC=F", "Agroindustria / fertilizantes", +1, ["ADM", "BG", "DE", "CTVA", "MOS", "CF", "NTR"]),
    ("CC=F", "Chocolate (consumidoras)", -1, ["HSY", "MDLZ"]),
    ("KC=F", "Cafeterías (consumidoras)", -1, ["SBUX", "KDP", "JVA"]),
    ("CT=F", "Ropa/algodón (consumidoras)", -1, ["PVH", "HBI", "RL", "GIL", "VFC"]),
]


def load_futures(refresh=False):
    f = CACHE / "scr_futures_close.pkl"
    if f.exists() and not refresh:
        return pd.read_pickle(f)
    h = yf.download(list(FUTURES), start="2000-01-01", interval="1d", auto_adjust=False, progress=False, group_by="ticker", threads=True)
    out = {}
    for tk in FUTURES:
        try:
            s = h[tk]["Close"].dropna()
            s = s[s > 0]  # p.ej. el WTI llegó a cotizar en negativo (abril 2020): no se puede calcular retorno
            if len(s) > 500:
                out[tk] = s
        except Exception:
            pass
    df = pd.DataFrame(out)
    df.index = pd.to_datetime(df.index).tz_localize(None)
    df.to_pickle(f)
    return df


def load_stocks(tickers, refresh=False):
    f = CACHE / "scr_basket_stocks.pkl"
    have = pd.read_pickle(f) if (f.exists() and not refresh) else pd.DataFrame()
    need = [t for t in tickers if t not in have.columns]
    if need:
        h = yf.download(need, start="2000-01-01", interval="1d", auto_adjust=True, progress=False, group_by="ticker", threads=True)
        new = {}
        for tk in need:
            try:
                s = h[tk]["Close"].dropna() if len(need) > 1 else h["Close"].dropna()
                if len(s) > 250:
                    new[tk] = s
            except Exception:
                pass
        add = pd.DataFrame(new)
        add.index = pd.to_datetime(add.index).tz_localize(None)
        have = pd.concat([have, add], axis=1).sort_index()
        have.to_pickle(f)
    return have


def load_stocks_open(tickers, refresh=False):
    """Precios de apertura (para medir la reacción operable al día siguiente: entrar a la apertura tras ver el cierre del futuro)."""
    f = CACHE / "scr_basket_open.pkl"
    have = pd.read_pickle(f) if (f.exists() and not refresh) else pd.DataFrame()
    need = [t for t in tickers if t not in have.columns]
    if need:
        h = yf.download(need, start="2000-01-01", interval="1d", auto_adjust=True, progress=False, group_by="ticker", threads=True)
        new = {}
        for tk in need:
            try:
                s = h[tk]["Open"].dropna() if len(need) > 1 else h["Open"].dropna()
                if len(s) > 250:
                    new[tk] = s
            except Exception:
                pass
        add = pd.DataFrame(new)
        add.index = pd.to_datetime(add.index).tz_localize(None)
        have = pd.concat([have, add], axis=1).sort_index()
        have.to_pickle(f)
    return have

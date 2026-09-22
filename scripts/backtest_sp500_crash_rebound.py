"""Backtest de cartera: rebote tras caídas fuertes en acciones del S&P 500.

Reglas (fijadas ANTES de ver resultados; no se optimizan):
  - Señal al cierre del día t: la acción lleva >=2 días seguidos de caída y la
    caída acumulada de esa racha es >= THR (variantes pre-declaradas: 10/15/20%).
  - Entrada: al cierre de t (supuesto MOC) o, como sensibilidad realista, en la
    apertura de t+1. Salida: cierre de t+1. Sin apalancamiento.
  - Tamaño: cada posición pesa min(MAX_W, 1/n_señales) del capital del día.
  - Costos por lado configurables (ida y vuelta = 2x).

LIMITACIÓN CONOCIDA: usa los constituyentes ACTUALES del S&P 500 (sesgo de
supervivencia: faltan las acciones que cayeron y salieron del índice), lo que
favorece esta estrategia. Sin datos point-in-time no se puede corregir.

Uso:
    python -m scripts.backtest_sp500_crash_rebound
"""
import io
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import yfinance as yf

warnings.filterwarnings("ignore")
CACHE = Path(__file__).resolve().parent.parent / "data" / "cache"
CACHE.mkdir(parents=True, exist_ok=True)
MAX_W = 0.10
SPLIT = pd.Timestamp("2013-01-01")


def load_prices():
    f_close, f_open = CACHE / "sp500_close.pkl", CACHE / "sp500_open.pkl"
    if f_close.exists() and f_open.exists():
        return pd.read_pickle(f_close), pd.read_pickle(f_open)
    html = requests.get("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
                        headers={"User-Agent": "Mozilla/5.0"}, timeout=30).text
    tickers = pd.read_html(io.StringIO(html))[0]["Symbol"].str.replace(".", "-", regex=False).tolist()
    closes, opens = {}, {}
    for i in range(0, len(tickers), 50):
        chunk = tickers[i:i + 50]
        h = yf.download(chunk, start="2000-01-01", interval="1d", auto_adjust=True, progress=False,
                        group_by="ticker", threads=True)
        for tk in chunk:
            try:
                c, o = h[tk]["Close"].dropna(), h[tk]["Open"].dropna()
                if len(c) > 1000:
                    closes[tk], opens[tk] = c, o
            except Exception:
                pass
    close, open_ = pd.DataFrame(closes), pd.DataFrame(opens)
    for df in (close, open_):
        df.index = pd.to_datetime(df.index).tz_localize(None)
    close.to_pickle(f_close)
    open_.to_pickle(f_open)
    return close, open_


def signal_matrix(close: pd.DataFrame, thr: float, kmin: int = 2) -> pd.DataFrame:
    """True donde hay >=kmin días de caída seguidos con caída acumulada >= thr (info hasta el cierre de t)."""
    c = close.values
    n_days, n_st = c.shape
    streak = np.zeros(n_st, dtype=int)
    start = np.full(n_st, np.nan)
    sig = np.zeros((n_days, n_st), dtype=bool)
    for t in range(1, n_days):
        down = c[t] < c[t - 1]  # NaN compara False
        new = down & (streak == 0)
        start = np.where(new, c[t - 1], start)
        streak = np.where(down, streak + 1, 0)
        drop = 1 - c[t] / start
        sig[t] = (streak >= kmin) & (drop >= thr) & ~np.isnan(drop)
    return pd.DataFrame(sig, index=close.index, columns=close.columns)


def run(close, open_, sig, cost_side, entry="close"):
    """Devuelve retorno diario de la cartera (índice = día de salida) y log de trades."""
    nxt_close = close.shift(-1)
    if entry == "close":
        gross = nxt_close / close - 1
    else:  # entra en la apertura de t+1
        gross = nxt_close / open_.shift(-1) - 1
    net = gross - 2 * cost_side
    n = sig.sum(axis=1)
    w = np.minimum(MAX_W, 1.0 / n.replace(0, np.nan))
    contrib = (sig * net).mul(w, axis=0)
    daily = contrib.sum(axis=1, min_count=1).fillna(0.0)
    daily.index = close.index
    daily = daily.shift(1).fillna(0.0)  # el retorno se realiza al cierre de t+1
    exposure = (sig.mul(w, axis=0)).sum(axis=1).shift(1).fillna(0.0)
    trades = net.where(sig).stack()
    return daily, exposure, trades


def stats(daily, exposure, trades, label, ann=252):
    eq = (1 + daily).cumprod()
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = eq.iloc[-1] ** (1 / yrs) - 1
    dd = (eq / eq.cummax() - 1).min()
    sharpe = daily.mean() / daily.std() * np.sqrt(ann) if daily.std() > 0 else 0
    print(f"{label:34} ret total {eq.iloc[-1]-1:+9.1%} | CAGR {cagr:+6.1%} | maxDD {dd:6.1%} | Sharpe {sharpe:5.2f} | "
          f"invertido {(exposure>0).mean():4.0%} | trades {len(trades):6} | neto/trade {trades.mean():+.2%} | gan. {(trades>0).mean():.0%}")
    return eq


def main():
    close, open_ = load_prices()
    print(f"Acciones: {close.shape[1]} | días: {close.shape[0]} ({close.index[0].date()} -> {close.index[-1].date()})")
    spy = yf.download("SPY", start="2000-01-01", auto_adjust=True, progress=False)["Close"].squeeze()
    spy.index = pd.to_datetime(spy.index).tz_localize(None)
    spy_r = spy.pct_change().reindex(close.index).fillna(0)
    eqw_r = close.pct_change().mean(axis=1).fillna(0)

    def bh(r, label):
        eq = (1 + r).cumprod()
        yrs = (eq.index[-1] - eq.index[0]).days / 365.25
        dd = (eq / eq.cummax() - 1).min()
        print(f"{label:34} ret total {eq.iloc[-1]-1:+9.1%} | CAGR {eq.iloc[-1]**(1/yrs)-1:+6.1%} | maxDD {dd:6.1%} | Sharpe {r.mean()/r.std()*np.sqrt(252):5.2f}")
    print("\n--- Referencias (comprar y mantener) ---")
    bh(spy_r, "SPY")
    bh(eqw_r, "Cesta equiponderada 493 acciones")

    results = {}
    for thr in (0.10, 0.15, 0.20):
        sig = signal_matrix(close, thr)
        print(f"\n=== Caída acumulada >= {thr:.0%} (2+ días) | señales: {int(sig.values.sum()):,} en {int((sig.sum(axis=1)>0).sum())} días ===")
        for cost, entry, lab in [(0.0005, "close", "Entrada cierre t, costo 0.05%/lado"),
                                  (0.0015, "close", "Entrada cierre t, costo 0.15%/lado (estrés)"),
                                  (0.0005, "open", "Entrada apertura t+1, costo 0.05%/lado")]:
            d, e, tr = run(close, open_, sig, cost, entry)
            eq = stats(d, e, tr, lab)
            results[(thr, entry, cost)] = (d, e, tr)

    # detalle de la variante base (15%, cierre, 0.05%/lado)
    d, e, tr = results[(0.15, "close", 0.0005)]
    print("\n--- Detalle variante base (>=15%, entrada al cierre, 0.05%/lado) ---")
    for lab, m in [("IS  2000-2012", d.index < SPLIT), ("OOS 2013-2026", d.index >= SPLIT)]:
        x = d[m]
        yrs = (x.index[-1] - x.index[0]).days / 365.25
        eq = (1 + x).cumprod()
        print(f"{lab}: ret {eq.iloc[-1]-1:+.1%} | CAGR {eq.iloc[-1]**(1/yrs)-1:+.1%} | maxDD {(eq/eq.cummax()-1).min():.1%} | SPY mismo periodo {(1+spy_r[m]).prod()-1:+.1%}")
    ann = d.groupby(d.index.year).apply(lambda x: (1 + x).prod() - 1)
    annspy = spy_r.groupby(spy_r.index.year).apply(lambda x: (1 + x).prod() - 1)
    print("Por año  (estrategia | SPY):")
    print("  " + " | ".join(f"{y}: {ann[y]:+.0%}/{annspy[y]:+.0%}" for y in ann.index))
    # robustez: sin Covid (feb-abr 2020) y sin los 5 mejores días
    nocovid = d[~((d.index >= "2020-02-15") & (d.index <= "2020-05-01"))]
    top5 = d.drop(d.nlargest(5).index)
    for lab, x in [("Sin feb-abr 2020", nocovid), ("Sin los 5 mejores días", top5)]:
        print(f"Robustez {lab}: ret total {(1+x).prod()-1:+.1%}")
    print(f"Peor día de la cartera: {d.min():+.2%} ({d.idxmin().date()}) | mejor: {d.max():+.2%}")
    print(f"Peor trade individual: {tr.min():+.1%} | percentil 1: {tr.quantile(0.01):+.1%}")


if __name__ == "__main__":
    main()

"""Backtest del SISTEMA COMPLETO tal como lo ejecutaría el informe diario (cripto), sin mirar el futuro.

Para cada día se reproduce lo que habría hecho `daily_report`:
  - las tablas de probabilidad se recalculan cada trimestre SOLO con eventos anteriores (sin lookahead);
  - decisión por perfil (magnitud mínima, IC inferior de la probabilidad, nº de casos, esperanza neta > 0, filtro de capitulación de BTC);
  - tamaño = riesgo por operación / pérdida p5 histórica (con topes de peso, nº de posiciones y exposición del perfil);
  - freno diario (si las posiciones de ayer pierden >= límite, hoy no se abre nada) y kill switch de drawdown del 50%;
  - costos por lado, mantener 1 día (entrada al cierre diario UTC, salida 24 h después).
Además: la candidata en observación (Fear&Greed>=75 + mini-bajada, mantener 5 días), robustez (costos, universo, sin una moneda, umbral
de capitulación, sin el mejor día, sin FTX) y Monte Carlo de 1 año con 1000 EUR.

Uso: python -m scripts.backtest_system
"""
import warnings

import numpy as np
import pandas as pd

from screener.backtest import perf
from screener.context import build_context
from screener.events import build_events
from screener.news import fear_greed
from screener.risk import PROFILES
from screener.stats import wilson_low
from screener.universe import ANN, COST, load_history

warnings.filterwarnings("ignore")
START = pd.Timestamp("2020-01-01")
SPLIT_T = pd.Timestamp("2022-01-01")
KILL_DD = 0.50
COST_C = COST["crypto"]
ORIG30 = ["BTC", "ETH", "BNB", "XRP", "ADA", "DOGE", "SOL", "TRX", "LINK", "DOT", "LTC", "BCH", "AVAX", "XLM", "ATOM", "ETC", "UNI",
          "FIL", "NEAR", "APT", "ARB", "OP", "HBAR", "ICP", "VET", "AAVE", "ALGO", "SHIB", "TON", "SUI"]


def prepare():
    close, _ = load_history("crypto")
    last_ok = close.apply(lambda s: s.last_valid_index())
    close = close.loc[:, last_ok >= last_ok.max() - pd.Timedelta(days=15)]
    ev = build_events(close)
    down = ev[(ev["dir"] == "down") & (ev["k"] >= 2) & ev["next"].notna()].copy()
    btc = close["BTC"]
    dd90 = btc / btc.rolling(90).max() - 1
    down["dd90"] = down["date"].map(dd90)
    return close, down, dd90


def stats_before(down, cutoff):
    sub = down[down["date"] < cutoff - pd.Timedelta(days=1)]  # el retorno 'next' debe estar ya realizado
    rows = {}
    for zb, g in sub.groupby("zb"):
        n, kk = len(g), int((g["next"] > 0).sum())
        rows[int(zb)] = dict(n=n, p_low=wilson_low(kk, n), mean=g["next"].mean(), p5=g["next"].quantile(0.05))
    return rows


def run_profile(down, prof, cost=COST_C, cap_thr=-0.25, refresh="QS", coins=None, exclude=None, end=None, start=START, weak_factor=None):
    """Simula el informe día a día. Devuelve serie diaria de retornos de la cartera y el log de operaciones."""
    d = down if coins is None else down[down["asset"].isin(coins)]
    if exclude:
        d = d[d["asset"] != exclude]
    end = end or d["date"].max()
    days = pd.date_range(start, end, freq="D")
    by_date = {k: v for k, v in d[d["date"] >= start].groupby("date")}
    refresh_days = set(pd.date_range(start, end, freq=refresh)) | {start}
    wf = prof.weak_size_factor if weak_factor is None else weak_factor
    stats, equity, peak, halted_forever = {}, 1.0, 1.0, False
    daily, trades = {}, []
    prev_pnl = 0.0
    for day in days:
        if day in refresh_days:
            stats = stats_before(d, day)
        # el P&L de las posiciones abiertas ayer se realiza hoy (al cierre)
        equity *= 1 + prev_pnl
        peak = max(peak, equity)
        if equity <= peak * (1 - KILL_DD):
            halted_forever = True
        halt_today = halted_forever or (prev_pnl <= -prof.daily_loss_limit)
        pnl_today = 0.0
        cand = by_date.get(day)
        if cand is not None and not halt_today:
            picks = []
            for r in cand.itertuples():
                s = stats.get(int(r.zb))
                if s is None or r.zb < prof.min_z or s["p_low"] < prof.min_p_low or s["n"] < prof.min_n:
                    continue
                ev = s["mean"] - 2 * cost
                if ev <= 0:
                    continue
                strong = r.dd90 <= cap_thr
                if not strong and wf <= 0:
                    continue
                loss = max(-s["p5"], 1e-4)
                w = min(prof.max_w, prof.risk_per_trade / loss) * (1.0 if strong else wf)
                picks.append((ev / loss, w, r))
            picks.sort(key=lambda x: -x[0])
            picks = picks[:prof.max_positions]
            tot = sum(p[1] for p in picks)
            scale = min(1.0, prof.max_exposure / tot) if tot > 0 else 1.0
            for _, w, r in picks:
                w *= scale
                ret = r.next - 2 * cost
                pnl_today += w * ret
                trades.append(dict(entry=day, asset=r.asset, w=w, ret=ret, z=r.z))
        daily[day + pd.Timedelta(days=1)] = pnl_today  # se realiza al día siguiente
        prev_pnl = pnl_today
    s = pd.Series(daily).sort_index()
    return s, pd.DataFrame(trades)


def stats_line(label, s, tr, start=START, ann=365):
    s = s[s.index >= start]
    p, po = perf(s, ann), perf(s[s.index >= SPLIT_T], ann)
    inv = (s != 0).mean()
    n = len(tr)
    net = tr["ret"].mean() if n else float("nan")
    wr = (tr["ret"] > 0).mean() if n else float("nan")
    print(f"  {label:<38} CAGR {p['cagr']:+6.1%} Sharpe {p['sharpe']:5.2f} DD {p['dd']:6.1%} | OOS22+ CAGR {po['cagr']:+6.1%} Sharpe {po['sharpe']:5.2f} DD {po['dd']:6.1%} | "
          f"ops {n:4} días con posición {inv:4.0%} neto/op {net:+.2%} gana {wr:4.0%}")


def candidate_sleeve(close, prof, cost=COST_C, start=START):
    """Candidata: mini-bajada en tendencia alcista con Fear&Greed>=75; mantener 5 días; peso por riesgo (p5 conservador -20%)."""
    ctx = build_context(close)
    a = ctx[(ctx["trend"] == "up") & (ctx["prev_k"] >= 3) & (ctx["prev_z"] >= 2) & (ctx["cur_z"] < 2) & (ctx["retr"] < 0.66) & (ctx["cur_k"] <= 3)].copy()
    fg = fear_greed()
    a["fg"] = a["date"].map(fg)
    a = a[(a["fg"] >= 75) & (a["date"] >= start)]
    R = np.nan_to_num(close.pct_change().values)
    idx = close.index
    daily = np.zeros(len(idx))
    hold = 5
    for d, g in a.groupby("date"):
        pos = idx.get_loc(d)
        w = min(prof.max_w, prof.risk_per_trade / 0.20)
        tot = w * len(g)
        cap = prof.max_exposure / hold
        if tot > cap:
            w *= cap / tot
        for coin in g["asset"]:
            col = close.columns.get_loc(coin)
            for j in range(1, hold + 1):
                if pos + j < len(idx):
                    daily[pos + j] += w * R[pos + j, col]
            if pos + 1 < len(idx):
                daily[pos + 1] -= 2 * cost * w
    return pd.Series(daily, idx), len(a)


def montecarlo(daily, label, n=5000, seed=11):
    rng = np.random.default_rng(seed)
    pool = daily[daily.index >= START].values
    finals, dds = [], []
    for _ in range(n):
        path = []
        while len(path) < 365:
            s = rng.integers(0, len(pool) - 10)
            path.extend(pool[s:s + 10])
        eq = np.cumprod(1 + np.array(path[:365]))
        finals.append(eq[-1] - 1)
        dds.append((eq / np.maximum.accumulate(eq) - 1).min())
    f, dd = np.array(finals), np.array(dds)
    print(f"  {label:<14} 1 año con 1000 €: p5 {np.percentile(f, 5):+.1%} ({1000 * np.percentile(f, 5):+.0f} €) | mediana {np.median(f):+.1%} ({1000 * np.median(f):+.0f} €) | p95 {np.percentile(f, 95):+.1%} | P(pérdida) {(f < 0).mean():.0%} | DD mediana {np.median(dd):.1%} | P(DD>20%) {(dd < -0.2).mean():.0%} | P(DD>50%) {(dd < -0.5).mean():.1%}")


def main():
    close, down, dd90 = prepare()
    print(f"Cripto: {close.shape[1]} monedas | eventos de caída (2+ días): {len(down):,} | simulación desde {START.date()} (estadísticas iniciales con 2017-2019, refresco trimestral)")
    btc = close["BTC"].pct_change().fillna(0)
    basket = close.pct_change().mean(axis=1).fillna(0)
    for lab, r in (("BTC comprar y mantener", btc), ("Cesta 45 monedas equiponderada", basket)):
        r = r[r.index >= START]
        p, po = perf(r, 365), perf(r[r.index >= SPLIT_T], 365)
        print(f"  {lab:<38} CAGR {p['cagr']:+6.1%} Sharpe {p['sharpe']:5.2f} DD {p['dd']:6.1%} | OOS22+ CAGR {po['cagr']:+6.1%} Sharpe {po['sharpe']:5.2f} DD {po['dd']:6.1%}")

    print("\n=== 1) INFORME REPRODUCIDO DÍA A DÍA, por perfil (regla validada + filtro de capitulación) ===")
    res = {}
    for name, prof in PROFILES.items():
        s, tr = run_profile(down, prof)
        res[name] = (s, tr)
        stats_line(f"perfil {name}", s, tr)
    print("\n  Por año (retorno del año):")
    for name, (s, _) in res.items():
        yr = s[s.index >= START].groupby(s[s.index >= START].index.year).apply(lambda x: (1 + x).prod() - 1)
        print(f"   {name:<12}: " + " | ".join(f"{y}:{v:+.1%}" for y, v in yr.items()))
    yb = btc[btc.index >= START].groupby(btc[btc.index >= START].index.year).apply(lambda x: (1 + x).prod() - 1)
    print(f"   {'BTC':<12}: " + " | ".join(f"{y}:{v:+.0%}" for y, v in yb.items()))

    print("\n=== 2) CANDIDATA EN OBSERVACIÓN (Fear&Greed>=75 + mini-bajada, 5 días) y combinación ===")
    for name in ("balanceado",):
        prof = PROFILES[name]
        cs, n_ev = candidate_sleeve(close, prof)
        stats_line(f"candidata sola ({n_ev} eventos)", cs, pd.DataFrame({"ret": []}))
        comb = res[name][0].reindex(cs.index, fill_value=0).add(cs, fill_value=0)
        stats_line("regla validada + candidata", comb, res[name][1])

    print("\n=== 3) ROBUSTEZ (perfil balanceado) ===")
    prof = PROFILES["balanceado"]
    base_s, base_tr = res["balanceado"]
    for c in (0.0015, 0.003, 0.005, 0.01):
        s, tr = run_profile(down, prof, cost=c)
        stats_line(f"costo {c:.2%}/lado", s, tr)
    s, tr = run_profile(down, prof, coins=ORIG30)
    stats_line("solo las 30 monedas originales", s, tr)
    for thr in (-0.15, -0.20, -0.30):
        s, tr = run_profile(down, prof, cap_thr=thr)
        stats_line(f"capitulación si BTC <= {thr:.0%} de su máx", s, tr)
    s, tr = run_profile(down, prof, weak_factor=1.0)
    stats_line("SIN filtro de capitulación", s, tr)
    s, tr = run_profile(down, prof, refresh="YS")
    stats_line("tablas recalculadas 1 vez al año", s, tr)
    cagrs = {}
    for coin in close.columns:
        s, _ = run_profile(down, prof, exclude=coin)
        cagrs[coin] = perf(s[s.index >= START], 365)["cagr"]
    cs = pd.Series(cagrs).sort_values()
    print(f"  Sin una moneda (45 casos): CAGR mín {cs.iloc[0]:+.1%} (sin {cs.index[0]}) | máx {cs.iloc[-1]:+.1%} (sin {cs.index[-1]}) | base {perf(base_s[base_s.index >= START], 365)['cagr']:+.1%}")
    b = base_s[base_s.index >= START]
    for lab, x in (("sin los 5 mejores días", b.drop(b.nlargest(5).index)), ("sin nov-2022 (FTX)", b[~((b.index >= "2022-11-01") & (b.index < "2022-12-01"))]),
                   ("sin mar-2020 (Covid)", b[~((b.index >= "2020-03-01") & (b.index < "2020-04-01"))])):
        p = perf(x, 365)
        print(f"  {lab:<38} CAGR {p['cagr']:+6.1%} Sharpe {p['sharpe']:5.2f} DD {p['dd']:6.1%}")
    print(f"  Peor día de la cartera: {b.min():+.2%} ({b.idxmin().date()}) | mejor: {b.max():+.2%}")

    print("\n=== 4) MONTE CARLO (bloques de 10 días, 1 año, 1000 €; sobre retornos 2020-2026) ===")
    for name, (s, _) in res.items():
        montecarlo(s, name)


if __name__ == "__main__":
    main()

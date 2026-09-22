"""Reporte diario multi-mercado: racha actual de cada activo, probabilidad histórica de reversión,
riesgo y tamaño sugerido según tu perfil de riesgo.

Uso:
    python -m scripts.daily_report --risk balanceado --capital 1000
    python -m scripts.daily_report --risk agresivo --include-unvalidated
    python -m scripts.daily_report --refresh-stats          # recalcula las tablas históricas (lento)

HORARIO: ejecútalo cada día a las 00:05 UTC (cierre diario de Binance): 02:05 hora de Madrid en verano (CEST) y 01:05 en invierno (CET).
Las 4 clases ya han cerrado a esa hora. Con >2 h de retraso el edge se degrada (a las 8 h se pierde ~70%).
    python -m scripts.daily_report --risk balanceado --record     # --record: actualiza el registro en papel (state/ledger.json)
Solo se recomienda comprar en clases de activos con edge validado por backtest (screener/validation.json).
NO es asesoramiento financiero: son probabilidades históricas, no garantías.
"""
import argparse
import json
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from config import RISK
from screener.candidates import get_candidate_stats
from screener.candidates import matches as candidate_matches
from screener import crypto100
from screener.allocation import allocate
from screener.ml_score import get_model, score_signals
from screener import ledger as ledger_mod
from screener.events import current_state
from screener.news import fear_greed
from screener.risk import PROFILES, catastrophe_stop, position_weight
from screener.trend import trend_targets
from screener.stats import get_stats
from screener.universe import CACHE, CLASSES, COST, load_recent, names

warnings.filterwarnings("ignore")
CATASTROPHE_STOP = 0.30  # stop de catástrofe: en 2022-26 no cuesta retorno (+3.58% vs +3.59%) y recorta el peor caso de -59% a -31%
CAPITULATION_DD = -0.25  # BTC >=25% por debajo de su máximo de 90 días (umbral derivado de 2017-2021)
ROOT = Path(__file__).resolve().parent.parent
VALID = ROOT / "screener" / "validation.json"
REPORTS = ROOT / "reports"


def drop_partial(close, cls):
    """Quita la última barra si todavía puede estar incompleta (no aplica a cripto, que ya la excluye)."""
    now = datetime.now(timezone.utc)
    if cls != "crypto" and len(close) and close.index[-1].date() == now.date() and now.hour < 22:
        return close.iloc[:-1]
    return close


def madrid_offset_hours(dt_utc):
    """Desfase Madrid-UTC (CEST +2 entre el último domingo de marzo y el último domingo de octubre, 01:00 UTC; CET +1 el resto)."""
    def last_sunday(y, m):
        d = datetime(y, m + 1, 1, tzinfo=timezone.utc) - timedelta(days=1) if m < 12 else datetime(y, 12, 31, tzinfo=timezone.utc)
        return d - timedelta(days=(d.weekday() + 1) % 7)
    y = dt_utc.year
    start = last_sunday(y, 3).replace(hour=1)
    end = last_sunday(y, 10).replace(hour=1)
    return 2 if start <= dt_utc < end else 1


def timing_block(crypto_last_close):
    now = datetime.now(timezone.utc)
    off = madrid_offset_hours(now)
    since_close = (now - now.replace(hour=0, minute=0, second=0, microsecond=0)).total_seconds() / 3600
    local = (now + timedelta(hours=off)).strftime("%H:%M")
    lines = [f"Hora actual: {now.strftime('%Y-%m-%d %H:%M')} UTC = {local} Madrid ({'CEST' if off == 2 else 'CET'}). "
             f"Hora recomendada de ejecución: 00:05 UTC = {(datetime(2000, 1, 1, 0, 5) + timedelta(hours=off)).strftime('%H:%M')} Madrid."]
    warn = []
    if crypto_last_close is not None and pd.Timestamp(crypto_last_close).date() < (now.date() - timedelta(days=1)):
        warn.append(f"DATOS CRIPTO DESFASADOS: el último cierre disponible es {pd.Timestamp(crypto_last_close).date()}; esperado {(now.date() - timedelta(days=1))}. No operes con esto.")
    if since_close > 2:
        warn.append(f"Han pasado {since_close:.1f} h desde el cierre de las 00:00 UTC: cada hora de retraso resta edge (a +8 h se pierde ~70% del rendimiento medio de la señal).")
    return lines, warn


def crypto100_stats(refresh=False):
    """Tablas históricas de las ~91 criptos del top-100 (caché propia; se recalculan con --refresh-stats)."""
    if (CACHE / "scr_stats_crypto100.pkl").exists() and not refresh:
        return get_stats("crypto", tag="100")
    return get_stats("crypto", refresh=True, close=crypto100.clean_universe(crypto100.load("1d")[0]), tag="100")


def add_ml(df, close, qv, last_dates_hint=None):
    """Añade 'ml' (probabilidad de rebote) a las compras de cripto; si el modelo falla se opera sin él (como antes) y se avisa."""
    try:
        return score_signals(df, close, qv, fear_greed(), get_model())
    except Exception as e:
        print(f"  (aviso: modelo de probabilidad no disponible: {str(e)[:80]})")
        return df.assign(ml=np.nan)


def evaluate(cls, state, stats, prof, validated, cost, risk_override, capitulation=None, liquidity=None):
    pooled = stats["pooled"].set_index(["dir", "zb"])
    cells = stats["cells"].set_index(["dir", "kc", "zb"])
    rows = []
    for _, r in state.iterrows():
        pk = int(r.get("prev_k", 0) or 0)
        prev_txt = (f"{pk}d {'↑' if r.get('prev_dir') == 'up' else '↓'} {r['prev_cum'] * 100:+.0f}% (deshecho {r['retr']:.0%})"
                    if pk and np.isfinite(r.get("prev_cum", np.nan)) and np.isfinite(r.get("retr", np.nan)) else "-")
        row = dict(clase=cls, activo=r["asset"], dir="BAJADA" if r["dir"] == "down" else "SUBIDA", dias=int(r["k"]),
                   mov=r["cum"], z=r["z"], sigma=r["sigma"], tend_previa=prev_txt)
        key = (r["dir"], int(r["zb"]))
        if int(r["k"]) < 2 or key not in pooled.index:
            row.update(verdict="sin señal (racha < 2 días o magnitud rara)", p=np.nan, n=0, p_low=np.nan, ev=np.nan, p5=np.nan)
            rows.append(row)
            continue
        s = pooled.loc[key]
        row.update(p=s["p"], n=int(s["n"]), p_low=s["p_low"], ev=s["mean"] - 2 * cost, p5=s["p5"], worst=s["worst"],
                   p_oos=s["p_oos"], base=s["base"])
        ck = (r["dir"], int(r["kc"]), int(r["zb"]))
        if ck in cells.index and cells.loc[ck, "n"] >= 30:
            row["p_cell"], row["n_cell"] = cells.loc[ck, "p"], int(cells.loc[ck, "n"])
        why = []
        if r["dir"] == "up":
            why.append("subida: sin edge validado para cortos")
        if not validated:
            why.append("clase SIN edge validado")
        if r["zb"] < prof.min_z:
            why.append(f"magnitud < {prof.min_z}σ del perfil")
        if s["p_low"] < prof.min_p_low:
            why.append(f"prob. baja (IC inf {s['p_low']:.0%} < {prof.min_p_low:.0%})")
        if s["n"] < prof.min_n:
            why.append(f"pocos casos ({int(s['n'])} < {prof.min_n})")
        if row["ev"] <= 0:
            why.append("esperanza neta ≤ 0 tras costos")
        if liquidity is not None:  # cripto: solo se opera con liquidez suficiente (media 30 días, USDT/día)
            liq = liquidity.get(r["asset"], 0.0)
            row["liq_musdt"] = liq / 1e6
            if not liq >= crypto100.MIN_LIQUIDITY:
                why.append(f"liquidez baja ({liq / 1e6:.1f} M USDT/día < {crypto100.MIN_LIQUIDITY / 1e6:.0f} M)")
        if capitulation is not None:  # cripto: calidad de la señal según si BTC está en capitulación (>=25% bajo su máx. de 90d)
            row["fuerza"] = "FUERTE" if capitulation else "DÉBIL"
            if not capitulation and prof.weak_size_factor <= 0:
                why.append("BTC no está en capitulación (perfil exige señal FUERTE)")
        row["verdict"] = "COMPRAR" if not why else "no: " + "; ".join(why)
        rows.append(row)
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--risk", choices=list(PROFILES), default="balanceado")
    ap.add_argument("--risk-per-trade", type=float, default=None, help="sobrescribe el riesgo por operación (ej. 0.015 = 1.5%)")
    ap.add_argument("--capital", type=float, default=1000.0)
    ap.add_argument("--classes", nargs="+", default=list(CLASSES), choices=list(CLASSES))
    ap.add_argument("--refresh-stats", action="store_true")
    ap.add_argument("--include-unvalidated", action="store_true", help="permite recomendar también en clases sin edge validado (no aconsejado)")
    ap.add_argument("--record", action="store_true", help="actualiza el registro en papel (state/ledger.json): cierra lo que toca y anota las compras de hoy")
    ap.add_argument("--min-prob", type=float, default=0.60, help="probabilidad mínima de rebote del modelo (0.80 = ~21 operaciones/año y ~76%% de acierto histórico)")
    ap.add_argument("--leverage", type=float, default=1.0, help="apalancamiento de tamaño (1 a 2; solo CFD/futuros; límite ESMA 2:1 en CFD de cripto minorista)")
    ap.add_argument("--original-universe", action="store_true", help="usa las 45 criptos originales en vez del top-100 con filtro de liquidez")
    args = ap.parse_args()

    prof = PROFILES[args.risk]
    validation = json.loads(VALID.read_text()) if VALID.exists() else {}
    all_rows, observe, notes, status = [], [], [], []
    closes, last_dates = {}, {}
    fg_value = btc_dd = None
    liquidity = None
    for cls in args.classes:
        if cls == "crypto" and not args.original_universe:
            stats = crypto100_stats(args.refresh_stats)
            close, qv_full = crypto100.load_recent_full()
            liquidity = qv_full.rolling(30, min_periods=15).mean().iloc[-1].to_dict()
        else:
            stats = get_stats(cls, refresh=args.refresh_stats)
            close = drop_partial(load_recent(cls), cls)
        if close.empty:
            status.append(f"[{cls}] sin datos recientes")
            continue
        fresh = close.apply(lambda s: s.last_valid_index()) >= close.index.max() - pd.Timedelta(days=3)  # descarta activos deslistados/sin datos al día
        close = close.loc[:, fresh]
        closes[cls], last_dates[cls] = close, close.index[-1]
        state = current_state(close)
        stale = (close.index[-1] < pd.Timestamp.now() - pd.Timedelta(days=5))
        validated = bool(validation.get(cls, {}).get("validated")) or args.include_unvalidated
        capitulation = None
        if cls == "crypto" and "BTC" in close.columns:
            btc_dd = float(close["BTC"].iloc[-1] / close["BTC"].iloc[-90:].max() - 1)
            capitulation = btc_dd <= CAPITULATION_DD
        df = evaluate(cls, state, stats, prof, validated, COST[cls], args.risk_per_trade, capitulation, liquidity if cls == "crypto" else None)
        if cls == "crypto" and not args.original_universe:
            df = add_ml(df, close, qv_full, last_dates_hint=close.index[-1])
        df["nombre"] = df["activo"].map(names(cls)).fillna("")
        df["fecha"] = close.index[-1].date()
        all_rows.append(df)
        tag = "VALIDADA" if validation.get(cls, {}).get("validated") else "sin edge validado"
        expected = stats.get('n_assets') or len(close.columns)
        incomplete = len(close.columns) < 0.9 * expected
        status.append(f"[{cls:11}] {len(close.columns):3} activos{f' (⚠ DATOS INCOMPLETOS: {len(close.columns)}/{expected}; falló la descarga, reintenta)' if incomplete else ''} | último cierre {close.index[-1].date()}{' (¡DATOS ANTIGUOS!)' if stale else ''} | clase {tag}")
        if cls == "crypto":
            try:
                fg_series = fear_greed()
                fg_value = float(fg_series.reindex([pd.Timestamp(close.index[-1]).normalize()]).iloc[0])
                fg_value = fg_value if np.isfinite(fg_value) else float(fg_series.iloc[-1])
                for _, srow in state.iterrows():
                    if candidate_matches(srow, fg_value) and (liquidity is None or liquidity.get(srow["asset"], 0.0) >= crypto100.MIN_LIQUIDITY):
                        observe.append(srow)
            except Exception as e:
                notes.append(f"(Fear & Greed no disponible: {str(e)[:60]})")
    if not all_rows:
        print("Sin datos.")
        return
    df = pd.concat(all_rows, ignore_index=True)
    now = datetime.now(timezone.utc)
    prices = {(c, a): float(closes[c][a].dropna().iloc[-1]) for c in closes for a in closes[c].columns if closes[c][a].notna().any()}

    # ---- registro en papel: qué toca cerrar hoy y estado de riesgo ----
    led = ledger_mod.load(args.capital)
    use_ledger = ledger_mod.STATE.exists() or args.record
    due = ledger_mod.due_positions(led, last_dates, prices)
    equity_before = led["equity"]
    realized = sum(ledger_mod.realized_pnl(p, r, COST[p["cls"]]) for p, _, r in due if not p.get("paper_only"))
    equity_after = equity_before + realized
    killed = led["killed"] or equity_after <= max(led["peak"], equity_after) * (1 - RISK.max_drawdown_pct)
    day_pnl = realized / equity_before if equity_before else 0.0
    halted = killed or day_pnl <= -prof.daily_loss_limit
    capital_eff = equity_after if use_ledger else args.capital

    # ---- asignación de la cartera del día ----
    lev = min(max(args.leverage, 1.0), 2.0)
    buy = allocate(df[df["verdict"] == "COMPRAR"].copy(), prof, args.risk_per_trade, args.min_prob)
    if lev > 1 and not buy.empty:
        buy["w"] = buy["w"] * lev
    if buy.empty:
        buy = buy.assign(loss=[], w=[], score=[])
    if halted:
        buy = buy.iloc[0:0]
    buy["eur"] = buy["w"] * capital_eff
    buy["riesgo_eur"] = buy["eur"] * buy["loss"]
    buy["ev_eur"] = buy["eur"] * buy["ev"]
    # stop de catástrofe ajustado a la volatilidad de cada moneda (regla diaria; validado con velas horarias reales)
    if "crypto" in closes:
        sigma60_now = closes["crypto"].pct_change().rolling(60).std().iloc[-1]
        buy["stop_pct"] = buy.apply(lambda r: catastrophe_stop(sigma60_now.get(r["activo"])) if r["clase"] == "crypto" else CATASTROPHE_STOP, axis=1)
    else:
        buy["stop_pct"] = CATASTROPHE_STOP

    trend = trend_targets(closes["crypto"], prof.trend_fraction * lev) if ("crypto" in closes and prof.trend_fraction > 0) else {}

    # ------------------------------------------------------------------ SALIDA
    tlines, twarn = timing_block(last_dates.get("crypto"))
    W = 112
    print("=" * W)
    print(f"INFORME DIARIO — perfil {prof.name} | capital {capital_eff:,.0f} € | riesgo/operación {(args.risk_per_trade or prof.risk_per_trade):.2%} | "
          f"peso máx {prof.max_w:.0%} | máx {prof.max_positions} posiciones | exposición máx {prof.max_exposure:.0%} | freno diario {prof.daily_loss_limit:.0%}")
    print("=" * W)
    for l in tlines:
        print(l)
    if lev > 1:
        print(f"  ⚠ APALANCAMIENTO x{lev:.1f} (solo CFD/futuros): los importes son NOCIONAL; margen necesario ≈ importe / {lev:.1f}. Ganancias y pérdidas se multiplican x{lev:.1f}; "
              f"añade financiación diaria y riesgo de liquidación (no modelado). Límite ESMA en CFD de cripto para minoristas: 2:1.")
    for w in twarn:
        print("  ⚠ " + w)
    for l in status:
        print(l)
    if btc_dd is not None:
        print(f"Cripto: BTC a {btc_dd:+.1%} de su máximo de 90 días -> {'CAPITULACIÓN (señales FUERTES)' if btc_dd <= CAPITULATION_DD else 'sin capitulación (señales DÉBILES)'}"
              + (f" | Fear & Greed {fg_value:.0f}/100" if fg_value is not None else ""))
    for n in notes:
        print(n)

    print("\n" + "=" * W)
    print("RESUMEN — QUÉ HACER HOY")
    print("=" * W)
    if killed:
        print("  ⛔ KILL SWITCH ACTIVO: el capital cayó más del 50% desde su máximo. No abras posiciones nuevas hasta revisarlo.")
    elif halted:
        print(f"  ⛔ FRENO DIARIO: las posiciones que cierras hoy pierden {day_pnl:.1%} (límite {prof.daily_loss_limit:.0%}). Hoy no abras posiciones nuevas.")
    if due:
        print("  CERRAR HOY (vender a mercado): " + ", ".join(f"{p['asset']} ({r:+.1%})" for p, _, r in due))
    else:
        print("  CERRAR HOY: nada (no hay posiciones vencidas en el registro)" if use_ledger else "  CERRAR HOY: (sin registro en papel; usa --record para que el informe te recuerde qué vender)")
    if buy.empty and not halted:
        print("  COMPRAR HOY: NADA. Ninguna señal cumple los criterios: lo correcto es no operar (el mercado no da ventaja todos los días).")
    elif not buy.empty:
        print("  COMPRAR HOY: " + ", ".join(f"{r['activo']} {r['eur']:.0f} €" for _, r in buy.iterrows()) + f"  (total {buy['eur'].sum():.0f} € = {buy['w'].sum():.0%} del capital)")
    if trend:
        print("  CAPA DE TENDENCIA (%.0f%% del capital): " % (prof.trend_fraction * 100) + " | ".join(
            f"{c} señal {v['sig'] * 3:.0f}/3 -> objetivo {v['target_w'] * capital_eff:.0f} €" for c, v in trend.items()))
    if observe:
        print("  EN OBSERVACIÓN (solo papel): " + ", ".join(s["asset"] for s in observe))
    if use_ledger:
        sm = ledger_mod.summary(led)
        sm["equity"], sm["ret"] = equity_after, equity_after / led["capital0"] - 1  # ya incluye lo que se cierra hoy
        if sm["n"]:
            print(f"  Registro en papel: equity {sm['equity']:.2f} € ({sm['ret']:+.1%}) | operaciones cerradas {sm['n']} (gana {sm['win']:.0%}, retorno medio {sm['avg']:+.2%}) | abiertas {sm['n_open']}")
        else:
            print(f"  Registro en papel: equity {sm['equity']:.2f} € | aún sin operaciones cerradas | abiertas {sm['n_open']}")

    if due:
        print("\n" + "-" * W)
        print("CERRAR HOY — vender a mercado a las 00:05 UTC")
        for p, px, r in due:
            print(f"  {p['asset']:6} ({p['rule']}{', solo papel' if p.get('paper_only') else ''}): comprada el {p['entry_date']} a {p['entry_price']:.6g}, ahora {px:.6g} -> {r:+.2%} "
                  f"({ledger_mod.realized_pnl(p, r, COST[p['cls']]):+.2f} € tras costos)")

    print("\n" + "-" * W)
    print(f"COMPRAR HOY (perfil {prof.name}) — entrar a las 00:05 UTC a mercado, salir 24 h después")
    print("-" * W)
    if buy.empty:
        print("  Ninguna señal cumple los criterios hoy." + (" (freno/kill switch activo)" if halted else ""))
    else:
        out = pd.DataFrame({
            "clase": buy["clase"], "activo": buy["activo"], "racha": buy["dias"].astype(str) + "d bajada", "señal": buy["fuerza"] if "fuerza" in buy else "-",
            "caída": (buy["mov"] * 100).map("{:+.1f}%".format), "z(σ)": buy["z"].map("{:.1f}".format),
            "P(sube)": (buy["p"] * 100).map("{:.0f}%".format), "IC inf": (buy["p_low"] * 100).map("{:.0f}%".format),
            "P modelo": buy["ml"].map(lambda v: f"{v * 100:.0f}%" if pd.notna(v) else "-") if "ml" in buy else "-", "casos": buy["n"], "ret esp.": (buy["ev"] * 100).map("{:+.2f}%".format),
            "pérd. p5": (-buy["loss"] * 100).map("{:.1f}%".format), "peso": (buy["w"] * 100).map("{:.1f}%".format),
            "importe €": buy["eur"].map("{:.0f}".format), "riesgo €": buy["riesgo_eur"].map("{:.1f}".format),
            "esperado €": buy["ev_eur"].map("{:+.2f}".format)})
        print(out.to_string(index=False))
        print(f"\nExposición: {buy['w'].sum():.0%} ({buy['eur'].sum():.0f} €) | pérdida p5 conjunta si todas fallan: -{buy['riesgo_eur'].sum():.1f} € | ganancia esperada: {buy['ev_eur'].sum():+.2f} €")
        print("Órdenes (Binance spot, par /USDT):")
        for _, r in buy.iterrows():
            px = prices[(r["clase"], r["activo"])]
            exit_d = (pd.Timestamp(last_dates[r["clase"]]) + pd.Timedelta(days=2)).date()
            sp = r["stop_pct"]
            print(f"  • {r['activo']}: comprar {r['eur']:.0f} € a mercado (referencia {px:.6g}); orden STOP de catástrofe a {px * (1 - sp):.6g} (-{sp:.0%}, ajustado a la volatilidad de esta moneda); "
                  f"vender a mercado el {exit_d} a las 00:05 UTC.")
        print("Nota: 'pérd. p5' = pérdida superada solo el 5% de las veces en situaciones iguales; los peores casos históricos fueron -59% (por eso el stop de catástrofe y el tope de peso).")
        print("No pongas stops ajustados: en el histórico destruyen el edge (stop -5%: +1.7% vs +4.0% sin stop) porque el rebote llega tras caídas intradía.")

    if trend:
        print("\n" + "-" * W)
        print(f"CAPA DE TENDENCIA BTC/ETH — {prof.trend_fraction:.0%} del capital repartido entre las 2 monedas; señal = nº de medias (SMA100/150/200) por debajo del precio")
        print("-" * W)
        per = prof.trend_fraction * lev / len(trend)
        for c, v in trend.items():
            prev_w = per * (0.0 if v["sig_prev"] != v["sig_prev"] else v["sig_prev"])
            change = (v["target_w"] - prev_w) * capital_eff
            if abs(change) >= per * capital_eff / 6:
                action = f"{'COMPRAR' if change > 0 else 'VENDER'} {abs(change):.0f} € de {c}"
            else:
                action = "mantener"
            print(f"  {c}: señal hoy {v['sig'] * 3:.0f}/3 (ayer {v['sig_prev'] * 3:.0f}/3) | objetivo {v['target_w'] * 100:.1f}% = {v['target_w'] * capital_eff:.0f} € | {action}")
        print("  Es exposición de mercado (no una ventaja estadística como las reglas de rebote): backtest 2022-26 ≈ +23% anual con caídas de ~-30% si estuviera al 100% del capital.")
        print("  Se ejecuta a las 00:05 UTC junto con lo demás; cambia solo cuando cambia la señal (~25 cambios al año por moneda).")

    print("\n" + "=" * W)
    print("RACHAS ACTIVAS (2+ días, magnitud ≥ 2σ) — situación de cada mercado y probabilidad histórica de reversión (informativo)")
    print("=" * W)
    act = df[(df["dias"] >= 2) & (df["z"] >= 2)].sort_values(["clase", "z"], ascending=[True, False])
    for cls in args.classes:
        g = act[act["clase"] == cls].head(10)
        print(f"\n[{cls}] {'(clase VALIDADA)' if validation.get(cls, {}).get('validated') else '(sin edge validado: solo informativo)'}")
        if g.empty:
            print("  sin rachas relevantes hoy")
            continue
        t = pd.DataFrame({"activo": g["activo"] + g["nombre"].map(lambda s: f" ({s})" if s else ""), "racha": g["dias"].astype(str) + "d " + g["dir"].str.lower(),
                          "mov": (g["mov"] * 100).map("{:+.1f}%".format), "z": g["z"].map("{:.1f}".format),
                          "tendencia previa": g["tend_previa"],
                          "P(revierte)": (g["p"] * 100).map("{:.0f}%".format).replace("nan%", "-"), "casos": g["n"],
                          "IC inf": (g["p_low"] * 100).map("{:.0f}%".format).replace("nan%", "-"),
                          "ret esp.(a favor)": (g["ev"] * 100).map("{:+.2f}%".format).replace("nan%", "-"),
                          "veredicto": g["verdict"].str.slice(0, 60)})
        print(t.to_string(index=False))

    print("\n" + "=" * W)
    print("EN OBSERVACIÓN (candidata NO validada — solo papel, no la incluyas en dinero real)")
    print("=" * W)
    cst = get_candidate_stats()
    print(f"Regla '{cst['name']}' (cripto): tendencia alcista previa fuerte + bajada pequeña + Fear&Greed >= {cst['fg_thr']} -> comprar y mantener {cst['hold']} días.")
    print(f"Histórico: {cst['n']} situaciones en {cst['episodes']} episodios independientes | neto medio {cst['mean']:+.1%} ({cst['hold']}d) | mediana {cst['median']:+.1%} | "
          f"gana {cst['p_win']:.0%} | p5 {cst['p5']:+.1%} | peor {cst['worst']:+.1%} | fuera de muestra: {cst['n_oos']} casos, neto {cst['mean_oos']:+.1%}")
    obs_w = 0.0
    if observe:
        loss = max(-cst["p5"], 1e-4)
        obs_w = position_weight(prof, loss, args.risk_per_trade)
        for s in observe:
            print(f"  * {s['asset']}: {int(s['prev_k'])}d de subida ({s['prev_cum']*100:+.0f}%), bajada de {int(s['k'])}d ({s['cum']*100:+.1f}%, deshecho {s['retr']:.0%}) "
                  f"-> tamaño de papel {obs_w:.1%} ({obs_w * capital_eff:.0f} €), pérdida p5 {loss:.1%}. Mantener {cst['hold']} días.")
    else:
        print("  Hoy ningún activo cumple la candidata (o Fear & Greed < 75).")

    # ---- actualizar el registro en papel ----
    if args.record:
        ledger_mod.close_positions(led, due, pd.Timestamp(last_dates.get("crypto", now)).date(), COST)
        ledger_mod.check_kill(led, RISK.max_drawdown_pct)
        opened = 0
        if not led["killed"]:
            for _, r in buy.iterrows():
                px = prices[(r["clase"], r["activo"])]
                opened += ledger_mod.open_position(led, r["clase"], r["activo"], "caida_fuerte", pd.Timestamp(last_dates[r["clase"]]).date(), px, r["eur"], 1, px * (1 - r["stop_pct"]))
        for s in observe:
            px = prices[("crypto", s["asset"])]
            ledger_mod.open_position(led, "crypto", s["asset"], cst["name"], pd.Timestamp(last_dates["crypto"]).date(), px, obs_w * capital_eff, cst["hold"], px * (1 - CATASTROPHE_STOP), paper_only=True)
        led["last_record"] = now.strftime("%Y-%m-%d %H:%M UTC")
        ledger_mod.save(led)
        print(f"\nRegistro en papel actualizado ({ledger_mod.STATE}): {len(due)} cerradas, {opened} abiertas hoy.")

    REPORTS.mkdir(exist_ok=True)
    f = REPORTS / f"informe_{datetime.now().strftime('%Y-%m-%d')}_{prof.name}.csv"
    df.to_csv(f, index=False, encoding="utf-8-sig")
    print(f"\nInforme completo guardado en {f}")
    print("Aviso: probabilidades históricas, no garantías. Pasado ≠ futuro. El backtest honesto del sistema (replay día a día) da CAGR +4% a +11% según perfil; empieza en papel.")


if __name__ == "__main__":
    main()

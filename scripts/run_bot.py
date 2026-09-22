"""Bot automático (SIMULADO o TESTNET de Binance; no existe modo con dinero real).

Se despierta en cada cierre de vela de 4 h (00, 04, 08, 12, 16, 20 UTC): cierra lo que toca, aplica los frenos y abre las
posiciones que pidan la regla diaria (a las 00:00 UTC) y la regla extrema de 4 h. Estado en state/bot_state.json, log en logs/bot.log.

Uso:
    python -m scripts.run_bot --mode sim --risk balanceado --capital 1000     # bucle continuo (dejar abierto)
    python -m scripts.run_bot --once                                          # un solo ciclo ahora y salir
    python -m scripts.run_bot --status                                        # ver equity, posiciones y resultados vs backtest
    Para parar: Ctrl+C, o crear el archivo state/STOP.
Testnet: crea claves en https://testnet.binance.vision/ (sin permiso de retiros) y ponlas en .env:
    BINANCE_TESTNET_KEY=...   BINANCE_TESTNET_SECRET=...     y usa --mode testnet
"""
import argparse
import logging
import sys
import time
from pathlib import Path

import pandas as pd

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from bot.engine import Bot, BotConfig, DataNotReady
from bot.exchange import SimExchange, TestnetExchange
from bot.feed import BinanceFeed
from bot.state import STATE_DIR, BotState
from bot.strategy import get_stats_4h
from screener.ml_score import get_model
from screener.news import fear_greed
from screener import crypto100
from scripts.daily_report import crypto100_stats

ROOT = Path(__file__).resolve().parent.parent
BACKTEST = {"trend": "capa BTC/ETH sobre SMA100/150/200: 2022-26 CAGR ≈ +23% con caídas de ~-30% si estuviera al 100% del capital",
            "daily": "neto/operación ≈ +2.0%, gana ≈ 66% (perfil balanceado, replay 2020-26)",
            "4h": "neto/operación ≈ +1.2% a +1.7%, gana ≈ 63-71% (z>=6, 1 vela; retraso de 15 min lo reduce ~45%)"}


def utcnow():
    return pd.Timestamp.now(tz="UTC").tz_localize(None)


def setup_logging():
    (ROOT / "logs").mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("bot")
    log.setLevel(logging.INFO)
    if not log.handlers:
        for h in (logging.StreamHandler(sys.stdout), logging.FileHandler(ROOT / "logs" / "bot.log", encoding="utf-8")):
            h.setFormatter(fmt)
            log.addHandler(h)
    return log


def run_cycle(bot, log, retries=18, wait=10):
    for i in range(retries):
        try:
            return bot.cycle(utcnow())
        except DataNotReady as e:
            log.info("Esperando datos (%s)... intento %d/%d", e, i + 1, retries)
            time.sleep(wait)
        except Exception:
            log.exception("Error en el ciclo (el bot sigue vivo y reintenta en la próxima vela)")
            return None
    log.error("Sin datos tras %d intentos: se omite esta vela.", retries)


def print_status(bot):
    s = bot.summary()
    print(f"Equity {s['equity']:.2f} USDT ({s['ret']:+.2%}) | caída desde máximo {s['dd']:.1%} | abiertas {s['open']} | cerradas {s['closed']}" + (" | ⛔ KILL SWITCH" if s["killed"] else ""))
    for p in bot.st["positions"]:
        print(f"  ABIERTA {p['rule']:5} {p['coin']:7} {p['usdt']:8.2f} USDT a {p['entry_px']:.6g} | stop {p['stop_px']:.6g} | sale {p['exit_after']} | {p['mode']}")
    for rule, r in s["rules"].items():
        print(f"  {rule:5}: {r['n']} operaciones | retorno medio {r['ret']:+.2%} | gana {r['win']:.0%} | slippage entrada {r['slip_in']:+.1f} bps, salida {r['slip_out']:+.1f} bps")
        print(f"         backtest: {BACKTEST[rule]}")
    for coin, p in s["trend"].items():
        print(f"  TENDENCIA {coin}: {p['qty']:.6g} unidades (coste {p['cost']:.2f} USDT)")
    if not s["rules"]:
        print("  (aún sin operaciones cerradas)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["sim", "testnet"], default="sim")
    ap.add_argument("--risk", choices=["conservador", "balanceado", "agresivo"], default="balanceado")
    ap.add_argument("--capital", type=float, default=1000.0)
    ap.add_argument("--rules", default="daily,4h,trend", help="reglas activas separadas por coma: daily, 4h, trend")
    ap.add_argument("--state-file", default=None, help="ruta alternativa del estado (para pruebas)")
    ap.add_argument("--min-prob", type=float, default=0.60, help="probabilidad mínima de rebote del modelo (0.60 por defecto; 0.80 = menos operaciones y ~76%% de acierto en el histórico)")
    ap.add_argument("--leverage", type=float, default=1.0, help="SOLO simulación: apalancamiento de tamaño, entre 1 y 2 (límite ESMA CFD cripto minorista)")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()

    log = setup_logging()
    uni = crypto100.get_universe()["coins"]
    coins = [c for c in uni if c not in crypto100.EXCLUDE and c.isascii()]
    feed = BinanceFeed(coins)
    try:
        ex = TestnetExchange(feed) if args.mode == "testnet" else SimExchange(feed)
    except Exception as e:
        log.error("No se pudo iniciar el modo %s: %s", args.mode, e)
        return
    cfg = BotConfig(profile=args.risk, capital=args.capital, rules=tuple(r.strip() for r in args.rules.split(",")), ml_min=args.min_prob, leverage=args.leverage)
    if args.leverage > 1 and args.mode == "testnet":
        log.warning("El apalancamiento solo se simula en modo sim: en testnet spot no hay margen. Se ignora.")
        cfg = BotConfig(profile=args.risk, capital=args.capital, rules=cfg.rules, ml_min=args.min_prob, leverage=1.0)
    state = BotState(path=args.state_file, capital=args.capital)
    try:
        model = get_model()
    except Exception as e:
        log.warning("Modelo de probabilidad no disponible (%s): la regla diaria opera sin él.", e)
        model = None
    bot = Bot(cfg, feed, ex, state, crypto100_stats(), get_stats_4h(), log, model=model, fg_provider=fear_greed)
    if args.status:
        print_status(bot)
        return
    log.info("Bot iniciado | modo %s | perfil %s | capital %.0f | reglas %s | %d monedas | equity %.2f", args.mode, args.risk, args.capital, cfg.rules, len(coins), state["equity"])
    run_cycle(bot, log)  # ponerse al día: cerrar lo vencido y, si aún hay margen de retraso, abrir
    if args.once:
        print_status(bot)
        return
    stop = STATE_DIR / "STOP"
    try:
        while True:
            now = utcnow()
            wake = now.floor("4h") + pd.Timedelta(hours=4, seconds=10)
            while utcnow() < wake:
                if stop.exists():
                    log.info("Archivo STOP detectado: el bot se detiene.")
                    return
                time.sleep(min(30, max(1, (wake - utcnow()).total_seconds())))
            run_cycle(bot, log)
            if stop.exists():
                log.info("Archivo STOP detectado: el bot se detiene.")
                return
    except KeyboardInterrupt:
        log.info("Bot detenido por el usuario (Ctrl+C). Las posiciones abiertas quedan guardadas en el estado.")


if __name__ == "__main__":
    main()

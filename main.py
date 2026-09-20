"""Punto de entrada del bot de trading por noticias.

Uso:
    python main.py            # corre en bucle continuo
    python main.py --once     # un solo ciclo (útil para probar)
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from bot.config import Settings
from bot.engine import TradingBot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")


def _print_safety_banner(settings: Settings) -> None:
    if settings.alpaca_paper:
        mode = "PAPER (simulado, sin dinero real)"
    elif settings.live_trading_allowed:
        mode = "LIVE — DINERO REAL, órdenes ejecutándose en el mercado"
    else:
        mode = "LIVE bloqueado (falta confirmación) — el bot no ejecutará órdenes"
    logger.info("=" * 70)
    logger.info("MODO DE EJECUCIÓN: %s", mode)
    logger.info("=" * 70)


async def _main() -> None:
    parser = argparse.ArgumentParser(description="Bot de trading por noticias")
    parser.add_argument("--once", action="store_true", help="Ejecuta un solo ciclo y sale")
    args = parser.parse_args()

    settings = Settings()
    _print_safety_banner(settings)

    if not settings.alpaca_paper and not settings.live_trading_allowed:
        logger.warning(
            "ALPACA_PAPER=false pero LIVE_TRADING_CONFIRM no coincide con la frase requerida. "
            "El bot generará y registrará señales pero NO enviará órdenes reales. "
            "Ver .env.example para activar el trading en vivo de forma consciente."
        )

    bot = TradingBot(settings)
    try:
        if args.once:
            await bot.run_once()
        else:
            await bot.run_forever()
    finally:
        bot.storage.close()


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        sys.exit(0)

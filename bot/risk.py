"""Gestión de riesgo: límites duros que ninguna señal puede saltarse.

Este módulo es la última línea de defensa antes de enviar una orden real.
Todas las comprobaciones son conservadoras a propósito: ante la duda, no se opera.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from bot.config import RiskConfig
from bot.models import Signal
from bot.storage import Storage

logger = logging.getLogger(__name__)


@dataclass
class RiskDecision:
    allowed: bool
    reason: str
    notional_usd: float = 0.0


class RiskManager:
    def __init__(self, config: RiskConfig, storage: Storage):
        self._config = config
        self._storage = storage
        self._kill_switch = False

    def trip_kill_switch(self, reason: str) -> None:
        """Detiene todo nuevo trading hasta reinicio manual. Llamar ante errores graves."""
        logger.error("KILL SWITCH activado: %s", reason)
        self._kill_switch = True

    def evaluate(self, signal: Signal, account_equity: float) -> RiskDecision:
        if self._kill_switch:
            return RiskDecision(False, "kill switch activo")

        if signal.confidence < self._config.min_confidence:
            return RiskDecision(False, f"confianza {signal.confidence} < mínimo {self._config.min_confidence}")

        daily_loss = -self._storage.realized_pnl_today()
        if daily_loss >= self._config.max_daily_loss_usd:
            return RiskDecision(False, f"pérdida diaria {daily_loss:.2f} alcanzó el límite")

        if self._storage.trades_today_count() >= self._config.max_trades_per_day:
            return RiskDecision(False, "límite de operaciones diarias alcanzado")

        if self._storage.open_positions_count() >= self._config.max_open_positions:
            return RiskDecision(False, "límite de posiciones abiertas alcanzado")

        notional = self._position_size(signal, account_equity)
        if notional <= 0:
            return RiskDecision(False, "tamaño de posición calculado es cero")

        return RiskDecision(True, "ok", notional_usd=notional)

    def _position_size(self, signal: Signal, account_equity: float) -> float:
        by_cap = self._config.max_position_usd
        by_equity_pct = account_equity * self._config.max_position_pct_equity
        base = min(by_cap, by_equity_pct)
        # Escala el tamaño con la confianza de la señal (a menor confianza, menor apuesta).
        return round(base * signal.confidence, 2)

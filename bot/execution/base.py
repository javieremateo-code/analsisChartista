"""Interfaz común para brokers de ejecución."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from bot.models import Signal


@dataclass
class OrderResult:
    order_id: str
    status: str


class Broker(ABC):
    @abstractmethod
    def get_equity(self) -> float:
        """Patrimonio total de la cuenta en USD, usado para dimensionar posiciones."""
        raise NotImplementedError

    @abstractmethod
    def is_market_open(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def submit_signal_order(self, signal: Signal, notional_usd: float) -> OrderResult:
        """Envía una orden de mercado (con stop-loss/take-profit adjuntos) para la señal dada."""
        raise NotImplementedError

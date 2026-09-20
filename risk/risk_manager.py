"""Gestión de riesgo: tamaño de posición y circuit breakers.

Prioridad explícita del proyecto: el risk management manda por encima de la
señal de entrada. El RiskManager puede vetar una operación aunque la
estrategia diga "entrar".
"""
from dataclasses import dataclass, field
from datetime import date


@dataclass
class RiskManager:
    initial_capital: float
    max_daily_loss_pct: float
    max_drawdown_pct: float
    risk_per_trade_pct: float

    equity: float = field(init=False)
    peak_equity: float = field(init=False)
    _current_day: date | None = field(default=None, init=False)
    _day_start_equity: float = field(init=False)
    halted: bool = field(default=False, init=False)
    halt_reason: str = field(default="", init=False)

    def __post_init__(self) -> None:
        self.equity = self.initial_capital
        self.peak_equity = self.initial_capital
        self._day_start_equity = self.initial_capital

    def position_size(self, entry_price: float, stop_price: float) -> float:
        """Cantidad del activo a comprar/vender para arriesgar risk_per_trade_pct del capital."""
        if self.halted:
            return 0.0
        risk_amount = self.equity * self.risk_per_trade_pct
        stop_distance = abs(entry_price - stop_price)
        if stop_distance <= 0:
            return 0.0
        return risk_amount / stop_distance

    def can_trade(self) -> bool:
        return not self.halted

    def record_trade_result(self, pnl: float, as_of: date) -> None:
        self._roll_day(as_of)
        self.equity += pnl
        self.peak_equity = max(self.peak_equity, self.equity)
        self._check_circuit_breakers()

    def _roll_day(self, as_of: date) -> None:
        if self._current_day != as_of:
            self._current_day = as_of
            self._day_start_equity = self.equity

    def _check_circuit_breakers(self) -> None:
        daily_loss_pct = (self._day_start_equity - self.equity) / self._day_start_equity
        if daily_loss_pct >= self.max_daily_loss_pct:
            self.halted = True
            self.halt_reason = (
                f"Límite de pérdida diaria alcanzado: -{daily_loss_pct:.1%} "
                f"(límite {self.max_daily_loss_pct:.0%})"
            )
            return

        drawdown_pct = (self.peak_equity - self.equity) / self.peak_equity
        if drawdown_pct >= self.max_drawdown_pct:
            self.halted = True
            self.halt_reason = (
                f"Drawdown máximo alcanzado: -{drawdown_pct:.1%} "
                f"(límite {self.max_drawdown_pct:.0%})"
            )

    def reset_daily_halt_if_new_day(self, as_of: date) -> None:
        """Un halt por pérdida diaria se levanta al día siguiente; el de drawdown total, no."""
        if self.halted and "diaria" in self.halt_reason and self._current_day != as_of:
            self.halted = False
            self.halt_reason = ""
        self._roll_day(as_of)

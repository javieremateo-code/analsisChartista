"""Persistencia simple en disco del estado del risk manager y de la posición
abierta, para que el runner de paper/live trading sobreviva entre invocaciones
(pensado para correr por cron, no como proceso permanente)."""
import json
from datetime import date
from pathlib import Path
from typing import Optional

from risk.risk_manager import RiskManager

STATE_DIR = Path(__file__).parent / "state"
RISK_STATE_FILE = STATE_DIR / "risk_state.json"
POSITION_STATE_FILE = STATE_DIR / "position_state.json"


def load_risk_manager(default: RiskManager) -> RiskManager:
    if not RISK_STATE_FILE.exists():
        return default
    data = json.loads(RISK_STATE_FILE.read_text())
    rm = RiskManager(
        initial_capital=data["initial_capital"],
        max_daily_loss_pct=default.max_daily_loss_pct,
        max_drawdown_pct=default.max_drawdown_pct,
        risk_per_trade_pct=default.risk_per_trade_pct,
    )
    rm.equity = data["equity"]
    rm.peak_equity = data["peak_equity"]
    rm._current_day = date.fromisoformat(data["current_day"]) if data["current_day"] else None
    rm._day_start_equity = data["day_start_equity"]
    rm.halted = data["halted"]
    rm.halt_reason = data["halt_reason"]
    return rm


def save_risk_manager(rm: RiskManager) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    RISK_STATE_FILE.write_text(json.dumps({
        "initial_capital": rm.initial_capital,
        "equity": rm.equity,
        "peak_equity": rm.peak_equity,
        "current_day": rm._current_day.isoformat() if rm._current_day else None,
        "day_start_equity": rm._day_start_equity,
        "halted": rm.halted,
        "halt_reason": rm.halt_reason,
    }, indent=2))


def load_position() -> Optional[dict]:
    if not POSITION_STATE_FILE.exists():
        return None
    return json.loads(POSITION_STATE_FILE.read_text())


def save_position(position: Optional[dict]) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    if position is None:
        POSITION_STATE_FILE.unlink(missing_ok=True)
        return
    POSITION_STATE_FILE.write_text(json.dumps(position, indent=2, default=str))

"""Tests del registro en papel: aperturas idempotentes, cierres a su vencimiento, P&L con costos, freno y kill switch."""
import pandas as pd

from screener import ledger


def _led():
    return ledger.load(1000.0, path=ledger.STATE.parent / "no_existe.json")


def test_open_is_idempotent_and_due_only_after_hold_days():
    led = _led()
    assert ledger.open_position(led, "crypto", "SOL", "caida_fuerte", "2026-09-20", 100.0, 100.0, 1, 70.0)
    assert not ledger.open_position(led, "crypto", "SOL", "caida_fuerte", "2026-09-20", 100.0, 100.0, 1, 70.0)  # misma operación: no duplica
    assert len(led["open"]) == 1
    prices = {("crypto", "SOL"): 105.0}
    assert ledger.due_positions(led, {"crypto": pd.Timestamp("2026-09-20")}, prices) == []  # el mismo día no toca cerrar
    due = ledger.due_positions(led, {"crypto": pd.Timestamp("2026-09-21")}, prices)
    assert len(due) == 1 and abs(due[0][2] - 0.05) < 1e-12


def test_close_updates_equity_with_costs_and_kill_switch():
    led = _led()
    ledger.open_position(led, "crypto", "ADA", "caida_fuerte", "2026-09-20", 1.0, 200.0, 1, 0.7)
    due = ledger.due_positions(led, {"crypto": pd.Timestamp("2026-09-21")}, {("crypto", "ADA"): 1.10})
    pnl = ledger.close_positions(led, due, "2026-09-21", {"crypto": 0.0015})
    assert abs(pnl - 200.0 * (0.10 - 0.003)) < 1e-9  # ganancia bruta 10% menos 2 x 0.15% de costos
    assert abs(led["equity"] - (1000.0 + pnl)) < 1e-9 and not led["open"] and len(led["closed"]) == 1
    led["equity"] = 480.0  # pérdida acumulada > 50% desde el máximo
    assert ledger.check_kill(led, 0.50) and led["killed"]


def test_state_path_is_resolved_at_call_time(tmp_path, monkeypatch):
    """Redirigir ledger.STATE debe afectar a load/save (evita escribir en el registro real durante pruebas)."""
    target = tmp_path / "ledger.json"
    monkeypatch.setattr(ledger, "STATE", target)
    ledger.save(ledger.load(500.0))
    assert target.exists() and ledger.load(999.0)["capital0"] == 500.0


def test_paper_only_positions_are_kept_separate_flag():
    led = _led()
    ledger.open_position(led, "crypto", "LINK", "codicia_mini_bajada", "2026-09-20", 10.0, 50.0, 5, 7.0, paper_only=True)
    assert led["open"][0]["paper_only"] is True and led["open"][0]["hold_days"] == 5

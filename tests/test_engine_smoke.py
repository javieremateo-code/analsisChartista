"""Test de regresión: el motor de backtest + estrategia + risk manager deben
correr de punta a punta sin errores, y los circuit breakers deben respetarse.
No depende de red (usa datos sintéticos) porque debe poder correr en CI.
"""
import numpy as np
import pandas as pd

from backtest.engine import run_backtest, walk_forward_windows
from risk.risk_manager import RiskManager
from strategy.donchian_breakout import StrategyParams


def _synthetic_ohlcv(n: int = 6000, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    times = pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC")
    returns = rng.normal(loc=0.00002, scale=0.003, size=n)
    close = 40000 * np.exp(np.cumsum(returns))
    high = close * (1 + np.abs(rng.normal(0, 0.001, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.001, n)))
    open_ = close * (1 + rng.normal(0, 0.0005, n))
    volume = rng.uniform(10, 100, n)
    return pd.DataFrame({
        "open_time": times, "open": open_, "high": high, "low": low,
        "close": close, "volume": volume,
    })


def test_backtest_runs_end_to_end_and_respects_drawdown_limit():
    df = _synthetic_ohlcv()
    params = StrategyParams()
    risk_manager = RiskManager(
        initial_capital=1000.0, max_daily_loss_pct=0.10,
        max_drawdown_pct=0.50, risk_per_trade_pct=0.01,
    )

    oos_frames = [t for _, t in walk_forward_windows(df, train_days=20, test_days=7) if not t.empty]
    assert oos_frames, "walk_forward_windows no generó ventanas de test"

    oos_data = pd.concat(oos_frames).drop_duplicates("open_time").sort_values("open_time")
    trades, equity_curve = run_backtest(oos_data, params, risk_manager)

    assert len(equity_curve) >= 1
    assert equity_curve.iloc[0] == 1000.0
    if not trades.empty:
        assert (trades["quantity"] > 0).all()
    # el equity nunca puede superar el peak - max_drawdown_pct permitido (con margen)
    peak = equity_curve.cummax()
    worst_dd = ((equity_curve - peak) / peak).min()
    assert worst_dd >= -0.55, f"drawdown se fue muy por encima del límite configurado: {worst_dd:.2%}"


def test_risk_manager_halts_on_daily_loss_limit():
    rm = RiskManager(initial_capital=1000.0, max_daily_loss_pct=0.10,
                      max_drawdown_pct=0.50, risk_per_trade_pct=0.01)
    today = pd.Timestamp("2024-01-01").date()
    rm.record_trade_result(pnl=-50, as_of=today)
    assert not rm.halted
    rm.record_trade_result(pnl=-60, as_of=today)
    assert rm.halted
    assert "diaria" in rm.halt_reason


def test_risk_manager_daily_halt_resets_next_day_but_drawdown_halt_does_not():
    rm = RiskManager(initial_capital=1000.0, max_daily_loss_pct=0.10,
                      max_drawdown_pct=0.50, risk_per_trade_pct=0.01)
    day1 = pd.Timestamp("2024-01-01").date()
    day2 = pd.Timestamp("2024-01-02").date()

    rm.record_trade_result(pnl=-150, as_of=day1)  # -15% del día -> halt diario
    assert rm.halted
    rm.reset_daily_halt_if_new_day(day2)
    assert not rm.halted  # se levanta al día siguiente

    # Pérdidas de -9% acumuladas día a día (siempre bajo el límite diario del 10%)
    # hasta cruzar el drawdown total del 50% desde el peak inicial.
    day = day2
    for i in range(10):
        day = pd.Timestamp("2024-01-02") + pd.Timedelta(days=i)
        day = day.date()
        rm.reset_daily_halt_if_new_day(day)
        if rm.halted:
            break
        rm.record_trade_result(pnl=-0.09 * rm.equity, as_of=day)

    assert rm.halted
    assert "Drawdown máximo" in rm.halt_reason
    rm.reset_daily_halt_if_new_day((pd.Timestamp(day) + pd.Timedelta(days=1)).date())
    assert rm.halted  # el kill switch de drawdown total NO se levanta solo

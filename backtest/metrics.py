"""Métricas de evaluación sobre el log de operaciones y la curva de equity."""
import numpy as np
import pandas as pd


def max_drawdown(equity_curve: pd.Series) -> float:
    peak = equity_curve.cummax()
    drawdown = (equity_curve - peak) / peak
    return float(drawdown.min())


def win_rate(trades: pd.DataFrame) -> float:
    if trades.empty:
        return 0.0
    return float((trades["pnl"] > 0).mean())


def profit_factor(trades: pd.DataFrame) -> float:
    if trades.empty:
        return 0.0
    gross_profit = trades.loc[trades["pnl"] > 0, "pnl"].sum()
    gross_loss = -trades.loc[trades["pnl"] < 0, "pnl"].sum()
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return float(gross_profit / gross_loss)


def sharpe_ratio(equity_curve: pd.Series) -> float:
    """Sharpe anualizado a partir del tiempo real transcurrido entre puntos.

    equity_curve solo tiene un punto por CIERRE DE OPERACIÓN, no uno por vela
    (las operaciones duran un número variable de velas). Anualizar asumiendo
    la frecuencia de las velas del timeframe (ej. 15m) sobrestima muchísimo
    la frecuencia real de muestreo y produce un Sharpe sin sentido. Por eso
    la frecuencia de muestreo se deriva del propio índice temporal.
    """
    returns = equity_curve.pct_change().dropna()
    if returns.std() == 0 or returns.empty or len(equity_curve) < 2:
        return 0.0

    elapsed_days = (equity_curve.index[-1] - equity_curve.index[0]).total_seconds() / 86400
    if elapsed_days <= 0:
        return 0.0
    samples_per_year = len(returns) / (elapsed_days / 365.25)
    return float(returns.mean() / returns.std() * np.sqrt(samples_per_year))


def summarize(trades: pd.DataFrame, equity_curve: pd.Series) -> dict:
    return {
        "n_trades": len(trades),
        "win_rate": win_rate(trades),
        "profit_factor": profit_factor(trades),
        "max_drawdown_pct": max_drawdown(equity_curve),
        "sharpe_ratio": sharpe_ratio(equity_curve),
        "total_return_pct": float(equity_curve.iloc[-1] / equity_curve.iloc[0] - 1) if len(equity_curve) > 1 else 0.0,
    }

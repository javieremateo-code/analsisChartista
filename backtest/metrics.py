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


def sharpe_ratio(equity_curve: pd.Series, periods_per_year: int) -> float:
    returns = equity_curve.pct_change().dropna()
    if returns.std() == 0 or returns.empty:
        return 0.0
    return float(returns.mean() / returns.std() * np.sqrt(periods_per_year))


def summarize(trades: pd.DataFrame, equity_curve: pd.Series, periods_per_year: int) -> dict:
    return {
        "n_trades": len(trades),
        "win_rate": win_rate(trades),
        "profit_factor": profit_factor(trades),
        "max_drawdown_pct": max_drawdown(equity_curve),
        "sharpe_ratio": sharpe_ratio(equity_curve, periods_per_year),
        "total_return_pct": float(equity_curve.iloc[-1] / equity_curve.iloc[0] - 1) if len(equity_curve) > 1 else 0.0,
    }

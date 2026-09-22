"""Perfiles de riesgo (el "dial" del usuario) y dimensionado de posiciones.

El tamaño de cada posición se calcula con el riesgo REAL histórico de su situación: la pérdida del
percentil 5 del retorno a un día en esa misma situación (racha + magnitud). Peso = riesgo_por_operación / pérdida_p5,
limitado por el peso máximo del perfil.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Profile:
    name: str
    min_z: int             # magnitud mínima de la racha (desviaciones típicas)
    min_p_low: float       # cota inferior (IC95%) mínima de la probabilidad histórica de reversión
    min_n: int             # nº mínimo de casos históricos
    risk_per_trade: float  # % del capital que se arriesga (pérdida p5) por operación
    max_w: float           # peso máximo por posición
    max_positions: int
    max_exposure: float    # exposición total máxima (suma de pesos)
    daily_loss_limit: float  # si la cartera pierde esto en un día, parar hasta el día siguiente
    weak_size_factor: float  # cripto: factor de tamaño si BTC NO está en capitulación (0 = no operar, 1 = sin cambio)
    trend_fraction: float = 0.0  # fracción del capital en la capa de tendencia BTC/ETH (ver screener/trend.py)


PROFILES = {
    # Calibrados con el replay día a día (scripts/backtest_system.py, estadísticas sin lookahead, 2020-2026, cripto).
    # Todos usan caídas >=3σ y >=50 casos; el dial mueve la exigencia de capitulación de BTC (weak_size_factor) y el tamaño.
    # Replay reglas de rebote (top-100, liquidez>=5M, con modelo de conjunto): conservador +3.7% / 0.68 / -2.6% | balanceado +9.1% / 0.95 / -6.7% | agresivo +14.7% / 1.02 / -15.5%.
    # Sistema completo con 4h y capa de tendencia (fracción trend_fraction): conservador +16.0% / 1.86 / -5.2% | balanceado +27.6% / 1.79 / -9.8% | agresivo +42.0% / 1.60 / -21.5%.
    "conservador": Profile("conservador", 3, 0.58, 50, 0.005, 0.10, 5, 0.60, 0.05, 0.0, 0.10),
    "balanceado": Profile("balanceado", 3, 0.58, 50, 0.010, 0.10, 8, 1.00, 0.10, 0.5, 0.20),
    "agresivo": Profile("agresivo", 3, 0.54, 50, 0.030, 0.30, 12, 1.00, 0.15, 1.0, 0.35),
}


def position_weight(profile: Profile, loss_p5: float, risk_per_trade=None) -> float:
    risk = risk_per_trade if risk_per_trade is not None else profile.risk_per_trade
    loss = max(loss_p5, 1e-4)
    return min(profile.max_w, risk / loss)

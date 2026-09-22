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
    # max_w subido moderadamente (quinta campaña, research/2026-09-22-quinta-campana.md): el tope anterior (10/10/30%) dejaba
    # capital ocioso en días con pocas señales buenas. Se probó y se descartó Kelly completo (satura casi siempre el tope,
    # riesgo de sobreapuesta si el modelo se equivoca) en favor de un tope moderado con la MISMA heurística de siempre.
    # Replay reglas de rebote (top-100, liquidez>=5M, con modelo de conjunto y tope nuevo): conservador +3.8% / 0.68 / -3.0% | balanceado +10.2% / 0.98 / -8.1% | agresivo +15.4% / 1.04 / -15.8%.
    # Sistema completo con 4h y capa de tendencia (fracción trend_fraction): ver README (recalculado tras esta campaña).
    "conservador": Profile("conservador", 3, 0.58, 50, 0.005, 0.12, 5, 0.60, 0.05, 0.0, 0.10),
    "balanceado": Profile("balanceado", 3, 0.58, 50, 0.010, 0.13, 8, 1.00, 0.10, 0.5, 0.20),
    "agresivo": Profile("agresivo", 3, 0.54, 50, 0.030, 0.35, 12, 1.00, 0.15, 1.0, 0.35),
}


def position_weight(profile: Profile, loss_p5: float, risk_per_trade=None) -> float:
    risk = risk_per_trade if risk_per_trade is not None else profile.risk_per_trade
    loss = max(loss_p5, 1e-4)
    return min(profile.max_w, risk / loss)


# --- stop de catástrofe ajustado a la volatilidad de cada moneda (quinta campaña) ---
# Validado con velas horarias reales (scripts/backtest_execution.py + scr_hourly_events100.pkl): 6x la desviación típica
# diaria de 60d mejora el retorno medio frente al -30% fijo (+3.54% -> +4.16%) con un peor caso similar, y se sostiene OOS.
STOP_VOL_MULT = 6.0
STOP_MIN, STOP_MAX = 0.10, 0.45


def catastrophe_stop(sigma_daily: float, mult: float = STOP_VOL_MULT, lo: float = STOP_MIN, hi: float = STOP_MAX) -> float:
    """Distancia del stop de catástrofe (fracción positiva, p.ej. 0.30 = -30%) a partir de la volatilidad diaria de la moneda."""
    if sigma_daily is None or sigma_daily != sigma_daily or sigma_daily <= 0:  # NaN o sin dato: usar el máximo (conservador)
        return hi
    return min(hi, max(lo, mult * sigma_daily))

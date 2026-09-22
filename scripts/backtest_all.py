"""Reejecuta TODOS los backtests/estudios del proyecto y archiva cada salida en reports/backtests/.

Uso:
    python -m scripts.backtest_all             # todos (10-20 min; usa las cachés de datos)
    python -m scripts.backtest_all system      # solo los que contienen 'system'
"""
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "reports" / "backtests"
JOBS = [
    ("intradia_tecnico", "scripts.study_intraday_timeframes", "Donchian y RSI en BTC 15m/1h/4h (walk-forward, con y sin costos)"),
    ("clases_racha", "scripts.study_asset_classes", "Rebote/reversión tras rachas normalizadas por σ: cripto, forex, commodities ETF, acciones"),
    ("contexto_tendencia", "scripts.study_trend_pullback", "Tendencia previa + mini-bajada: ¿continúa la tendencia? (4 clases)"),
    ("sentimiento", "scripts.study_sentiment", "Fear&Greed / VIX / noticias sobre las reglas"),
    ("filtros_caida_cripto", "scripts.study_crash_filters", "18 variables sobre la regla de caída fuerte (univariante, ML, walk-forward)"),
    ("futuros", "scripts.study_futures", "Futuros de commodities: rachas + seguimiento de tendencia"),
    ("futuros_a_acciones", "scripts.study_commodity_stocks", "¿Predice el futuro a las acciones relacionadas?"),
    ("carry_funding", "scripts.backtest_funding_carry", "Carry de funding delta-neutral BTC/ETH"),
    ("cripto_cartera_45", "scripts.backtest_crypto_robustness", "Cartera cripto 45 monedas: azar, walk-forward, costos, Monte Carlo"),
    ("sistema_replay", "scripts.backtest_system", "SISTEMA COMPLETO reproducido día a día por perfil + robustez + Monte Carlo"),
    ("cripto_top100", "scripts.study_crypto100", "Top-100 criptos: regla diaria (perfiles, liquidez), 4 h y 1 h"),
    ("mejora_modelo", "scripts.optimize_bot", "Campaña de mejora: modelo ML (filtro/tamaño) y tamaños por magnitud"),
    ("mejora_ejecucion", "scripts.optimize_exits", "Take-profit y entradas con orden límite (velas de 1 h)"),
    ("mejora_ideas", "scripts.optimize_ideas", "Otros activos como pistas (S&P/VIX/funding), capa de tendencia BTC/ETH y factores entre monedas"),
    ("mejora_calidad_apalancamiento", "scripts.optimize_more", "Calidad frente a cantidad, universo de 200, filtros de otros activos en la tendencia y apalancamiento"),
    ("mejora_hold_riesgo_ensemble", "scripts.optimize_hold_risk", "Tiempo de mantenimiento, correlación entre señales simultáneas y conjunto de 5 modelos"),
    ("mejora_kelly_stop", "scripts.optimize_kelly_stop", "Dimensionado por Kelly, stop por volatilidad, señal doble y estacionalidad"),
    ("mejora_4h_costos", "scripts.optimize_4h_costs", "Modelo sobre la regla de 4 h y palanca de costos"),
    ("final_sistema", "scripts.backtest_final", "Cifras finales: 3 perfiles con modelo + regla de 4 h + capital parado"),
    ("cripto_4h", "scripts.study_crypto_4h", "Regla de rebote con velas de 4 h (z>=3/4/5, 1 y 6 velas)"),
    ("ejecucion_horaria", "scripts.backtest_execution", "Retraso de entrada y stops con velas de 1 hora"),
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    only = sys.argv[1:]
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    index = [f"Backtests reejecutados el {stamp}", ""]
    for key, mod, desc in JOBS:
        if only and not any(o in key or o in mod for o in only):
            continue
        t0 = time.time()
        f = OUT / f"{key}.txt"
        with open(f, "w", encoding="utf-8") as fh:
            r = subprocess.run([sys.executable, "-X", "utf8", "-m", mod], cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT, env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
        status = "OK" if r.returncode == 0 else f"ERROR (código {r.returncode})"
        line = f"{status:>10} | {time.time() - t0:5.0f}s | {key:<22} | {desc}  -> {f.relative_to(ROOT)}"
        print(line, flush=True)
        index.append(line)
    (OUT / "INDICE.txt").write_text("\n".join(index), encoding="utf-8")


if __name__ == "__main__":
    main()

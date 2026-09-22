# Sistema final: backtest completo y decisiones de diseño

**Estado**: sistema completo reproducido día a día (`scripts/backtest_system.py`), ejecución con velas de 1 hora (`scripts/backtest_execution.py`) y
todos los estudios previos reejecutados y archivados con `python -m scripts.backtest_all` (`reports/backtests/`).

## Ejecución (velas de 1 h sobre 2192 eventos)
- Regla principal (>=3σ, 510 eventos): neto a 24 h +4.03%; entrando +1 h +3.42%, +4 h +2.78%, +8 h +1.19% (OOS 2022-26: +3.59% -> +2.77% / +2.45% / +0.74%).
  El rebote se acumula durante el día (+2.3% a las 6 h, +3.5% a las 12 h, +4.3% a las 24 h) => ejecutar a las 00:05 UTC.
- Stops ajustados destruyen el edge (-5%: +1.71%; -10%: +2.45%). Un stop de catástrofe de -30% es casi gratuito en 2022-26 (+3.58% vs +3.59%) y recorta el peor caso de -59% a -31%
  (dentro de muestra cuesta más: en marzo-2020 el pánico intradía rebotó con fuerza).

## Replay del informe día a día (cripto, 2020-2026, estadísticas trimestrales sin lookahead, costo 0.15%/lado)
| Perfil | CAGR | Sharpe | DD máx | Ops | OOS 2022+ (CAGR / Sharpe) |
|---|---|---|---|---|---|
| conservador | +4.2% | 0.88 | -1.2% | 65 | +4.1% / 0.88 |
| balanceado | +6.6% | 0.89 | -8.2% | 252 | +7.5% / 0.90 |
| agresivo | +11.0% | 0.74 | -23.4% | 296 | +10.5% / 0.68 |
Referencias: BTC comprar y mantener +43.5% (DD -77%), OOS 2022+ +12.7% (DD -67%).
Calibración: con los umbrales originales (n>=100-150) el conservador no operaba nunca; se recalibró con este mismo replay (sesgo optimista).

Robustez (balanceado): costo 0.5%/lado +4.8%, 1%/lado +2.3%; 30 monedas originales +5.1%; sin una moneda +5.2% a +6.9%; sin nov-2022 +7.1%;
**sin los 5 mejores días +1.6%** (el edge depende de pocos días); filtro de capitulación: umbral -25%/-30% Sharpe 0.89, umbrales -15%/-20% Sharpe 0.54, sin filtro 0.67 (sensible al umbral).
Monte Carlo 1 año con 1000 EUR (mediana / peor 5% / P(pérdida)): conservador +23 / -3 / 16%; balanceado +49 / -11 / 10%; agresivo +112 / -161 / 19% (P(DD>20%)=13%).
Candidata Fear&Greed>=75: sola +16.1% (OOS +5.0%, Sharpe 0.52); combinada con la regla validada +23.7% (OOS +12.8%, Sharpe 0.95) — descubierta con estos datos: optimista.

## Cuadro de todo lo probado (salidas en reports/backtests/)
| Familia | Resultado | Veredicto |
|---|---|---|
| Donchian / RSI en BTC 15m-4h | PF sin costos 0.95-1.06; con costos 0.32-0.91 (retorno -26% a -100%) | descartada |
| Rebote tras caída fuerte, cripto | OOS Sharpe 0.63; replay por perfil arriba | validada, retorno modesto |
| Igual en forex / commodities ETF / acciones / futuros | OOS Sharpe 0.23 / 0.05 / 0.00 / 0.38 | sin edge |
| Continuación tras mini-bajada (tendencia previa) | acciones exceso -0.10%; cripto OOS -0.05% | descartada |
| Corto tras tendencia bajista + rebote (cripto) | OOS Sharpe 0.47 (0.22 con costos de corto), peor día +36% | descartada |
| Fear&Greed / VIX / capitulación como filtros | F&G y VIX no ayudan; capitulación de BTC reduce riesgo | integrada (etiqueta FUERTE/DÉBIL) |
| Seguimiento de tendencia en futuros | Sharpe 0.20-0.25 (long/short) | descartada |
| Futuros -> acciones relacionadas | efecto +-0.1-0.3% por evento ≈ costo | descartada |
| Funding carry BTC/ETH (modelo optimista) | CAGR +5.6% / +6.8%; 2025 +2.3%, 2026 +0.8% (decae) | alternativa defensiva, sin modelar riesgos |
| Noticias reales (GDELT) | no se pudo descargar histórico suficiente | pendiente |

**Decisión**: pendiente (del usuario). Siguiente paso recomendado: 8-12 semanas de registro en papel (`--record`) y comparar con el backtest antes de dinero real.

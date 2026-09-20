# analsisChartista — bot sistemático intradía (BTC/USDT, Binance)

Sistema de trading algorítmico con foco en **validación antes que velocidad**:
sin backtest honesto (walk-forward, costos reales) no hay razón para creer
que una estrategia va a funcionar en vivo, y sin gestión de riesgo, cualquier
estrategia eventualmente puede volar la cuenta.

## Aviso importante

Esto **no es un bot de HFT** ni pretende serlo — opera en velas de 15 minutos,
no en microsegundos. No hay garantía de rentabilidad: el objetivo del diseño
es sobrevivir y medir honestamente, no prometer resultados. Antes de operar
con dinero real, el sistema debe pasar el criterio de graduación descrito
más abajo.

## Configuración actual (`config.py`)

| Parámetro | Valor | Nota |
|---|---|---|
| Capital | 1000 € | |
| Límite de pérdida diaria | 10% | el bot se detiene solo por el resto del día |
| Drawdown máximo total | 50% | **alto** para un sistema serio (lo usual es 15-25%); mantenido por decisión explícita del usuario, pero recomendado bajarlo una vez haya datos de paper trading reales |
| Riesgo por operación | 1% del capital | tamaño de posición derivado de esto + distancia al stop |
| Mercado | BTC/USDT en Binance | 24/7, API pública gratuita |
| Timeframe | 15 minutos | intradía |
| Modo de ejecución | `paper` (Binance Spot Testnet) | cambiar a `live` requiere cumplir la graduación |

## Arquitectura

```
data/         descarga y caché de velas OHLCV (API pública de Binance, sin key)
strategy/     reglas de entrada/salida (Donchian breakout + filtro de tendencia + ATR)
backtest/     motor bar-by-bar con costos reales + validación walk-forward
risk/         tamaño de posición + circuit breakers (pérdida diaria, drawdown)
execution/    ejecución de órdenes vía ccxt (Binance testnet o real) + persistencia de estado
scripts/      entry points: walk-forward, paper trading
tests/        regresión (corre sin red, con datos sintéticos)
research/     bitácora de propuestas de mejora (ver más abajo)
```

## Estrategias

- **`donchian`** (baseline original): ruptura de canal Donchian (20 velas) +
  filtro de tendencia (EMA 200) + stop/target en múltiplos de ATR. Primer
  walk-forward real (BTC/USDT, ~1 año OOS): profit_factor 0.54, -47.5% de
  retorno, kill switch de drawdown activado. **No tiene edge en este mercado
  a este timeframe** — ver `research/2026-09-20-resultado-baseline-donchian.md`.
- **`rsi_mr`** (hipótesis alternativa): reversión a la media con RSI(2) corto
  + filtro de tendencia (SMA 200) + stop/target ajustados. Racional completo
  en `strategy/rsi_mean_reversion.py`. Todavía sin validar con datos reales.

Elegir estrategia al correr el walk-forward con `--strategy donchian|rsi_mr`
(ver más abajo). Cada una documenta su racional en su propio archivo — **esto
es exploración de hipótesis, no una afirmación de que alguna "funciona"**
hasta que el walk-forward lo confirme con datos reales.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # completar BINANCE_API_KEY/SECRET del testnet: https://testnet.binance.vision/
```

## Cómo correr la validación (walk-forward, out-of-sample)

```bash
.venv/bin/python -m scripts.run_walk_forward --days 365 --train-days 60 --test-days 14 --strategy donchian
.venv/bin/python -m scripts.run_walk_forward --days 365 --train-days 60 --test-days 14 --strategy rsi_mr
```

Reporta métricas (win rate, profit factor, drawdown, Sharpe) calculadas
**exclusivamente sobre datos out-of-sample** — nunca usados para ajustar nada
en esa ventana. Nota: en este sandbox de desarrollo la API de Binance está
bloqueada por política de red del entorno remoto; el pipeline está validado
con datos sintéticos (`tests/test_engine_smoke.py`) y debería funcionar sin
cambios en una máquina con salida a internet normal (tu propia PC o un VPS).

## Cómo correr paper trading

`scripts/run_paper_trading.py` está pensado para ejecutarse **por cron**, una
vez por vela cerrada (cada 15 min), no como proceso permanente — así el
estado (equity, posición abierta) persiste en disco entre corridas y no
depende de mantener un proceso vivo 24/7.

```cron
*/15 * * * * cd /ruta/al/proyecto && .venv/bin/python -m scripts.run_paper_trading >> paper.log 2>&1
```

## Criterio de graduación a capital real

No paso a `TRADING_MODE=live` de forma automática. Antes de considerarlo, el
sistema debería mostrar en paper trading:
- Mínimo ~4-6 semanas corriendo sin interrupciones.
- Un número de operaciones estadísticamente mínimo (orden de 50-100), no 5-10.
- El drawdown real observado, no solo el backtest, dentro de lo esperado.
- Ninguna vez que el bot se haya comportado de forma inesperada (bugs de
  ejecución, desconexiones no manejadas, etc.).

La decisión final de activar `live` es tuya, no automática.

## Proceso de mejora diaria (research)

Cada mejora propuesta:
1. Se basa en fuentes públicas de calidad (papers de finanzas cuantitativas,
   resultados observados del propio paper trading) — no en "feeds de bots
   ajenos", que no existen como fuente confiable (ver discusión en el chat).
2. Se documenta como una propuesta concreta en `research/` con la hipótesis,
   el respaldo, y el resultado esperado del backtest/walk-forward.
3. **Nunca se aplica automáticamente.** Vos revisás y aprobás antes de que
   cualquier cambio de lógica llegue a paper o live trading.
4. Todo cambio de estrategia pasa de nuevo por walk-forward antes de tocar
   paper trading.

## Limitaciones conocidas / próximos pasos

- El runner de paper trading no maneja reconexión ni reintentos de red —
  aceptable para un cron cada 15 min, pero hay que vigilar los logs al inicio.
- No hay todavía optimización de parámetros (a propósito, para no mezclar
  medir con ajustar); si se agrega, debe ir en una etapa de validación
  separada de la evaluación out-of-sample.
- El drawdown máximo del 50% está configurado así por decisión explícita,
  pero vale la pena revisarlo con datos reales de paper trading.

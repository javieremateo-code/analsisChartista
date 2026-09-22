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

## Programa diario multi-mercado (`scripts/daily_report.py`)

Cada día, para cripto (45), forex (30 pares), commodities (18 ETFs) y acciones (S&P 500), muestra la **racha actual**
(días y % acumulado, normalizado por volatilidad en σ), la **probabilidad histórica** de que el día siguiente vaya en
sentido contrario (con nº de casos e intervalo de confianza), el **riesgo** (pérdida p5 histórica de esa misma situación)
y un **tamaño sugerido** según tu perfil de riesgo.

```bash
python -m scripts.daily_report --risk balanceado --capital 1000      # conservador | balanceado | agresivo
python -m scripts.daily_report --risk agresivo --risk-per-trade 0.03 # ajuste fino del riesgo por operación
python -m scripts.daily_report --refresh-stats                       # recalcula tablas históricas (semanal)
python -m scripts.study_asset_classes                                # re-valida qué clases tienen edge
```

Ejecutar tras el cierre diario (cripto: tras 00:00 UTC). Solo recomienda **comprar tras caídas fuertes** en clases
con edge validado por backtest (`screener/validation.json`; hoy: solo cripto). El resto se muestra como información.
Si ninguna señal cumple los criterios, la recomendación es no operar.

### Variables de contexto y sentimiento (estudios `scripts/study_trend_pullback.py`, `scripts/study_sentiment.py`)
- **Tendencia previa + mini-bajada:** no hay continuación fiable de la tendencia tras un retroceso pequeño (acciones y forex ~0;
  cripto solo funcionó en el mercado alcista de 2017-21). Se muestra en el informe como columna "tendencia previa".
- **Sentimiento:** Fear & Greed (cripto) y VIX. El informe imprime el Fear & Greed y lista, en "EN OBSERVACIÓN", la candidata
  `codicia_mini_bajada` (no validada; solo paper trading).
- **Noticias reales (GDELT):** `python -m scripts.collect_news` (lento y reanudable, límite de velocidad de GDELT). Cuando exista
  `data/cache/news_<clase>.pkl`, `study_sentiment` incluye automáticamente la señal de noticias.

### Calidad de señal en cripto (capitulación de BTC)
Tras probar ~18 variables (sentimiento, régimen, amplitud, volumen, funding, volatilidad...) sobre la regla de caída fuerte, solo una
sobrevive: si BTC está >=25% por debajo de su máximo de 90 días la señal es FUERTE (OOS: +7.8% neto, peor caso -13%); si no, DÉBIL
(+0.7%, peor caso -59%). El perfil conservador solo opera señales FUERTES y el balanceado reduce a la mitad el tamaño de las DÉBILES.
Detalle en `research/2026-09-21-filtros-regla-caida-cripto.md`. Fear & Greed y el resto NO mejoran esta regla.

## Sistema final (resumen honesto) y cómo usarlo cada día

**Qué hace:** cada día, tras el cierre de las 00:00 UTC, revisa 45 criptos (validadas), y también forex, commodities y acciones (solo informativo).
Si alguna cripto lleva una caída fuerte (>=3σ, 2+ días) con probabilidad histórica de rebote suficiente, propone comprar al cierre y vender 24 h después,
con tamaño según tu perfil de riesgo, un stop de catástrofe del -30% y un filtro de "capitulación" (BTC >=25% bajo su máximo de 90 días).

**Horario:** ejecutar a las **00:05 UTC** = **02:05 Madrid en verano (CEST, hasta el 25/oct/2026) y 01:05 en invierno (CET)**.
Con retraso el edge se degrada (datos horarios): entrada +1 h ≈ -15%, +4 h ≈ -30%, +8 h ≈ -70% del rendimiento medio.

**Automatizar en Windows** (Programador de tareas, hora local; hay que cambiarla a 01:05 cuando cambie la hora en octubre):
```
schtasks /Create /TN "InformeCripto" /TR "\"C:\ruta\al\proyecto\run_daily.bat\"" /SC DAILY /ST 02:05
```
`run_daily.bat` guarda el informe en `reports\ultimo_informe.txt` y actualiza el registro en papel (`--record`, `state/ledger.json`),
que además te recuerda qué posiciones cerrar cada día. Sin `--record` el informe no escribe nada (útil para probar).

**Perfiles (dial de riesgo) — resultados del replay día a día 2020-2026 (estadísticas sin lookahead, costo 0.15%/lado):**

| Perfil | CAGR | Sharpe | Caída máx. | Operaciones | Monte Carlo 1 año con 1000 € (mediana / peor 5%) |
|---|---|---|---|---|---|
| conservador | +4.2% | 0.88 | -1.2% | 65 | +23 € / -3 € |
| balanceado | +6.6% | 0.89 | -8.2% | 252 | +49 € / -11 € |
| agresivo | +11.0% | 0.74 | -23.4% | 296 | +112 € / -161 € |

Los perfiles se calibraron con estos mismos datos (sesgo optimista). El edge depende de pocos días de rebote: sin los 5 mejores días el balanceado
baja de +6.6% a +1.6%. A costos de 1%/lado rinde +2.3%. Comprar y mantener BTC dio +12.7%/año en 2022-2026 pero con caídas de -67%.

**Re-ejecutar todos los backtests:** `python -m scripts.backtest_all` (guarda cada salida en `reports/backtests/`).


### Actualización: universo top-100 con filtro de liquidez
El informe diario usa ahora las **~94 criptos activas del top-100** (sin stablecoins ni oro tokenizado) y solo opera las que tienen **>= 5 M USDT/día**
de volumen medio (30 días). Datos: `python -m scripts.fetch_crypto100` (actualizar el universo y el histórico una vez al mes) y
`python -m scripts.daily_report --refresh-stats` (recalcular tablas). `--original-universe` vuelve a las 45 originales.

Replay día a día 2020-2026 con el top-100 y liquidez >= 5 M (costo 0.15%/lado):

| Perfil | CAGR | Sharpe | Caída máx. | 2022-2026 (CAGR / Sharpe) |
|---|---|---|---|---|
| conservador | +3.2% | 0.68 | -2.0% | +4.8% / 0.85 |
| balanceado | +6.7% | 0.83 | -6.0% | +9.5% / 0.99 |
| agresivo | +8.6% | 0.62 | -23.7% | +11.4% / 0.70 |

Sin filtro de liquidez el agresivo llegaba a -33.9% de caída. Las monedas nuevas confirman la señal fuera de muestra (tras caídas 3-4σ suben el 68.7%,
neto +2.96%). Sigue dependiendo de pocos días (sin los 5 mejores, el balanceado rinde +1.2%) y a costos de 1%/lado deja de ganar.
Velas de 4 h: la regla extrema (z>=6, mantener 4 h) da CAGR +5.4%, Sharpe 0.86 (OOS 0.91) con 94 monedas, pero requiere ejecución automática.
Velas de 1 h: sin ventaja utilizable (neto negativo fuera de muestra); igual que en 15 minutos.

Velas de 8 h: sin ventaja sobre la regla diaria ni la de 4 h (mejor caso z>=6, mantener 24 h: CAGR +2.5%, Sharpe 0.49, resultados inconsistentes entre 2018-21 y 2022-26); descartada.

## Bot automático (`scripts/run_bot.py`) — simulado o testnet, nunca dinero real
Proceso que corre solo y se despierta en cada cierre de vela de 4 h (00, 04, 08, 12, 16, 20 UTC): cierra lo que toca, aplica el freno diario y el
kill switch, y abre posiciones con (1) la regla diaria a las 00:00 UTC (la misma del informe: perfil, capitulación, liquidez) y (2) la regla extrema de 4 h
(z>=6, mantener 1 vela). Solo entra si el retraso respecto al cierre es pequeño (4 h: 5 min; diaria: 30 min), porque los backtests suponen entrar al instante.

```
python -m scripts.run_bot --mode sim --risk balanceado --capital 1000   # o run_bot.bat: bucle continuo, dejar abierto
python -m scripts.run_bot --once                                        # un solo ciclo y salir
python -m scripts.run_bot --status                                      # equity, posiciones y resultados frente al backtest (incluye slippage real)
```
Parar: Ctrl+C o crear `state/STOP`. Estado en `state/bot_state.json` (sobrevive a reinicios), log en `logs/bot.log`.
- **Modo `sim`** (por defecto): sin claves, con precios reales del libro de órdenes; modela comisión 0.1% + slippage 0.05% por lado.
- **Modo `testnet`**: órdenes de mercado reales con dinero de prueba en https://testnet.binance.vision/ (claves en `.env`, sin permiso de retiros).
  El testnet solo lista unas pocas monedas: las demás se ejecutan simuladas y marcadas `sim_fallback`.
- **No existe modo con dinero real** en el código: se añadiría solo tras el periodo en papel y por decisión explícita.
- Límites: el PC debe estar encendido y con internet; el stop de catástrofe (-30%) lo comprueba el bot en cada ciclo con los mínimos de 1 h
  (no es una orden en el exchange); el tamaño se calcula sobre el equity realizado (USDT tratado como EUR).


## Mejora: modelo de probabilidad de rebote (filtro y tamaño) — campaña de optimización
Se probaron, con walk-forward y criterios de adopción fijados antes (`scripts/optimize_*.py`): modelo de machine learning, tamaños por magnitud, objetivos de
ganancia (TP), entradas con orden límite, menores costos, modelo sobre la regla de 4 h y una capa lenta de drawdowns profundos.
**Solo se adopta el modelo en la regla diaria**: gradient boosting con 17 variables (sentimiento, régimen de BTC, amplitud de mercado, volumen, volatilidad...),
reentrenado con datos anteriores; descarta señales con P(rebote) < 0.60 y dimensiona ∝ P (x0.6 a x1.4). AUC 0.58 (mejora modesta pero robusta).
No sirven: TP (recortan los ganadores: +8% da CAGR +5.4% vs +6.7%), órdenes límite (mejora mínima), bajar costos (+0.3 pts), ML en 4 h (AUC 0.55), tamaños por magnitud (solo escalan el riesgo), drawdowns profundos.

Replay día a día 2020-2026 (top-100, liquidez >= 5 M, 0.15%/lado):

| Perfil | Sin modelo | Con modelo | 2022-2026 con modelo | Monte Carlo 1 año con 1000 € (mediana / peor 5%) |
|---|---|---|---|---|
| conservador | +3.2% / 0.68 / -2.0% | +3.7% / 0.68 / -2.7% | +5.7% | +12 € / -18 € |
| balanceado | +6.7% / 0.83 / -6.0% | **+8.9% / 0.94 / -6.4%** | +13.0% | +60 € / -6 € |
| agresivo | +8.6% / 0.62 / -23.7% | **+14.6% / 1.02 / -14.2%** | +20.1% | +127 € / -32 € |

Sistema completo (balanceado): diaria con modelo +8.9%; + regla de 4 h con ejecución ideal +16.0% (Sharpe 1.25); con retraso realista (ganancia x0.55) +12.8% (Sharpe 1.17);
más capital parado al 3% anual +16.3% (Sharpe 1.45, caída -7.3%; mediana +141 € con 1000 €). Sigue habiendo optimismo (se probaron muchas ideas, AUC bajo,
dependencia de pocos días: sin los 5 mejores el balanceado con modelo rinde +2.4%). El informe y el bot usan el modelo (`screener/ml_score.py`, `screener/allocation.py`);
se reentrena solo si tiene más de 45 días (`python -m scripts.daily_report --refresh-stats` fuerza tablas; el modelo se refresca al arrancar).


## Segunda campaña: otros activos, capa de tendencia y factores (scripts/optimize_ideas.py)
Probado con walk-forward y criterio de adopción fijado antes:
- **Otros activos como pistas del modelo** (S&P, Nasdaq, VIX, dólar, bonos, oro, funding de futuros, caída relativa a BTC): mejora marginal (+9.7% vs +8.9%, Sharpe 1.01 vs 0.94 con
  mercados externos), no adoptada por criterio. Sí hay un patrón con mecanismo claro: los crash de cripto con el S&P subiendo (crash específico) NO rebotan (57%, neto -0.33%, n=113),
  y con estrés en bolsa (VIX>25) rebotan mucho (86%, +8.3%). Un filtro explícito "S&P no sube" reduce la caída máxima a la mitad (-6.4% -> -2.9%) sin subir el CAGR: opción de menor riesgo.
- **Capa de tendencia BTC/ETH (ADOPTADA como capa opcional)**: posición = media de 3 señales (precio > SMA100/150/200) sobre el capital que las reglas de rebote dejan parado. BTC 2022-26: +27% / Sharpe 0.92
  frente a +12.7% / 0.49 de comprar y mantener. Correlación ~0 con las reglas de rebote. Es exposición de mercado, no una ventaja estadística: peor día de la capa al 100% -22.3% (12/3/2020), peor mes -29%.
- **Factores entre monedas** (momentum, reversión, volatilidad, volumen, cercanía a máximos): solo beta de cripto con caídas de -80/-90% y OOS negativo o débil. Descartados.

Sistema completo (reglas diaria+modelo + 4 h con retraso x0.55 + capa de tendencia + resto en caja al 3%), replay 2020-2026:

| Perfil | Fracción en tendencia | Sin capa | **Con capa** | 2022-2026 con capa | Monte Carlo 1 año con 1000 € (mediana / peor 5%) |
|---|---|---|---|---|---|
| conservador | 10% | +10.7% / 1.49 / -3.0% | **+16.1% / 1.85 / -5.3%** | +15.2% | +150 € / +40 € |
| balanceado | 20% | +16.3% / 1.45 / -7.3% | **+27.5% / 1.78 / -9.8%** | +25.7% | +258 € / +52 € |
| agresivo | 35% | +21.6% / 1.28 / -18.2% | **+41.8% / 1.59 / -19.9%** | +35.7% | +404 € / +13 € |

Cautelas: son backtests con optimismo (muchas ideas probadas sobre los mismos datos); la capa de tendencia depende de que cripto siga teniendo tendencias largas (2020-21 y 2023-24 pesan mucho:
la capa ganó +164% y +114% en 2020 y 2021, perdió -19% en 2022 y -3% en 2018); en mercados laterales pierde por cambios de posición (~25 por año y moneda). El bot (`--rules daily,4h,trend`) y el informe
la ejecutan al cierre diario; `trend_fraction` de cada perfil se cambia en `screener/risk.py` (0 la desactiva).


## Tercera campaña: más acierto, más operaciones y apalancamiento (scripts/optimize_more.py)
**Calidad frente a cantidad (perfil balanceado, regla diaria con modelo).** Subir el umbral de probabilidad del modelo (`--min-prob`) sube el acierto y baja el número de operaciones:

| Umbral P | Operaciones/año | Acierto | Neto por operación | CAGR con tamaño base | CAGR con tamaño para caída -10% |
|---|---|---|---|---|---|
| sin filtro | 41 | 66% | +2.0% | +8.5% | +12.6% |
| 0.60 (por defecto) | 34 | 69% | +2.8% | +8.9% | +14.0% |
| 0.80 | 21 | 76% | +4.0% | +8.1% | +14.8% |
| 0.90 | 13 | 80% | +5.1% | +6.9% | +22.9% (tamaño x3.4) |

Más acierto no significa más dinero al mismo tamaño: da menos operaciones. Solo compensa si se puede subir el tamaño. Ojo: el tramo P>=0.9 son pocos episodios de pánico.
**Más operaciones al día:** ampliar a ~200 monedas da más eventos (716 vs 505) pero no más retorno (balanceado +7.4% vs +8.9%): los rebotes ocurren en los mismos días de pánico de mercado
(61-76 días con operación en 6.7 años). El límite son los pánicos, no las monedas.
**Otros activos:** filtrar la capa de tendencia con S&P sobre SMA200, VIX<30 o dólar en tendencia no mejora (S&P: OOS +22.9% -> +10.1%; dólar peor). Las pistas de bolsa/VIX/funding ya se probaron en el modelo (mejora marginal).
**Apalancamiento** del sistema completo balanceado (financiación 6% anual sobre lo prestado; el Sharpe casi no cambia, escalan ganancia y caída):

| Apalancamiento | CAGR | Caída máx. | Peor día | P(caída>20%) | P(caída>30%) | Mediana 1 año con 1000 € |
|---|---|---|---|---|---|---|
| 1.0x | +27.5% | -9.8% | -4.3% | 0% | 0% | +259 € |
| 1.5x | +40.7% | -14.7% | -6.4% | 1% | 0% | +383 € |
| 2.0x | +54.7% | -19.3% | -8.6% | 8% | 1% | +511 € |
| 3.0x | +84.6% | -28.1% | -12.8% | 40% | 7% | +790 € |
| 5.0x | +151.1% | -43.6% | -21.4% | 82% | 46% | +1404 € |

Apalancar solo las señales con P>=0.85 a x2: +8.9% -> +10.5% (mejora pequeña). El bot y el informe admiten `--leverage` (1 a 2, en el bot solo simulado, con financiación) y `--min-prob`.
**España / regulación (verifícalo con tu broker y un asesor fiscal):** para minoristas, las CFD de criptomonedas tienen un límite de apalancamiento de 2:1 (medidas ESMA aplicadas por la CNMV);
otras opciones son futuros regulados (p.ej. futuros micro de BTC/ETH de CME desde un bróker con acceso desde España). Algunos exchanges limitan los derivados a residentes de varios países de la UE.
Las ganancias en CFD/futuros tributan como ganancias patrimoniales del ahorro. El apalancamiento no se modela con liquidaciones, gaps ni cambios de financiación.

## Cuarta campaña: mantenimiento, correlación entre señales y conjunto de modelos (scripts/optimize_hold_risk.py)
- **Tiempo de mantenimiento:** mantener más de 1 día empeora con fuerza y de forma monótona (2d CAGR +5.8%/Sharpe 0.63; 5d ya pierde). Confirma que 24h es el punto correcto, no arbitrario:
  el rebote es un pico de pánico que se revierte parcialmente después, no el inicio de una tendencia.
- **Riesgo por correlación entre señales simultáneas (hallazgo importante):** en los días con 2+ señales el mismo día, el 76% de los pares de monedas se mueven en el mismo sentido al día
  siguiente (el azar sería 50%). El riesgo real de esos días es ~5.6x el que asume el sistema al sumar el riesgo de cada posición como si fueran independientes. Probé corregirlo bajando el
  tamaño de forma uniforme (el Sharpe no cambia, solo desapalanca) y limitando la exposición total solo en días con 3+ señales al 80% (el Sharpe mejora a 0.96 y la caída a -6.0%, pero el CAGR
  baja a +7.8%: no pasa el criterio estricto, pero es una alternativa más conservadora si prefieres priorizar el Sharpe). **No adoptado como cambio automático; el kill switch y el freno diario
  siguen siendo la protección real ante esto**, no la suma de "riesgo €" que muestra el informe en días con varias señales.
- **Conjunto de 5 modelos en vez de 1 solo — ADOPTADO en producción:** mejora las tres métricas a la vez (CAGR +8.9%→+9.1%, Sharpe 0.94→0.95, 2022+ +13.0%→+13.2%, DD -6.4%→-6.7%, dentro
  del límite). `screener/ml_score.py` entrena y puntúa ahora con 5 modelos (bootstrap + semillas), usado por el informe y el bot automáticamente.

**Cifras finales del sistema recalculadas con el conjunto de modelos** (balanceado, con capa de tendencia 20%, replay 2020-2026):

| Perfil | CAGR | Sharpe | Caída máx. | 2022-2026 | Mediana 1 año con 1000 € (peor 5%) |
|---|---|---|---|---|---|
| conservador | +16.0% | 1.86 | -5.2% | +15.1% (1.72) | +149 € (+41 €) |
| **balanceado** | **+27.6%** | **1.79** | **-9.8%** | **+25.9% (1.68)** | **+259 € (+54 €)** |
| agresivo | +42.0% | 1.60 | -21.5% | +36.1% (1.46) | +406 € (+20 €) |

Detalle en `research/2026-09-22-cuarta-campana.md`.

## Quinta campaña: Kelly, stop por volatilidad, señal doble y estacionalidad (scripts/optimize_kelly_stop.py)
- **Kelly fraccionario:** mejora el replay, pero el diagnóstico mostró que la fracción calculada satura el tope de posición el 94% de las veces — es indistinguible de "subir el tope sin más".
  Se **rechaza Kelly completo** por el riesgo de sobreapostar si el modelo se equivoca, combinado con el hallazgo de la campaña anterior de que las señales del mismo día están muy correlacionadas.
- **Tope de posición moderado — ADOPTADO** (misma heurística de siempre, solo con más margen): `max_w` conservador 10%→12%, balanceado 10%→13%, agresivo 30%→35%. Mejora CAGR, Sharpe y
  robustez sin disparar la caída máxima. El motivo real de la mejora: el tope anterior dejaba capital ocioso en días con pocas señales buenas.
- **Stop de catástrofe ajustado a volatilidad — ADOPTADO** (solo regla diaria, validado con velas horarias reales): en vez de -30% fijo para todas las monedas, `6x` la desviación típica diaria
  de cada una (entre -10% y -45%). Mejora el retorno medio (+3.54%→+4.16%) con un peor caso similar, y monedas de baja volatilidad (BTC/ETH) reciben un stop más ceñido que las más volátiles.
- **Señal doble** (regla diaria + racha extrema de 4h el mismo día) y **estacionalidad por día de la semana**: no adoptadas — resultados inconsistentes entre dentro y fuera de muestra, o pura muestra pequeña.

Cifras finales del sistema recalculadas (balanceado, con capa de tendencia 20%, replay 2020-2026): **CAGR +29.2%, Sharpe 1.78, caída máxima -10.7%** (2022+: +27.7%, Sharpe 1.68);
mediana 1 año con 1000€: +274€, peor 5%: +56€. Detalle en `research/2026-09-22-quinta-campana.md`.

## Bot de rejilla (grid trading) — construido, probado a fondo y RECHAZADO
El usuario pidió un bot que ganase dinero "cada hora, aunque sean céntimos". Se explicó que eso no existe garantizado, y que lo más parecido en la práctica es un bot de grid (compra escalonada en un rango,
vende al subir un peldaño) — con el riesgo conocido de "recoger céntimos delante de una apisonadora". Se construyó (`screener/grid.py`) con cortafuegos obligatorio (liquida todo y pausa si el precio rompe
el rango) y se probó con velas horarias **reales** de BTC y ETH desde 2020 (58.924 velas, incluye Covid, mayo 2021, LUNA, Celsius/3AC y FTX). Se encontró y corrigió un bug real en la simulación antes de sacar
conclusiones (ver `research/2026-09-22-bot-de-rejilla-grid.md`), verificado con tests unitarios sobre precios sintéticos (`tests/test_grid.py`).

**Resultado: RECHAZADO.** Con parámetros realistas (rango ±12%, 20 niveles, comisión 0.1%), la rejilla pierde dinero en las dos monedas durante 2020-2026 (BTC -39.2%, ETH -32.8%, frente a comprar y mantener
+1098% y +2028%). El cortafuegos sí funciona (ningún crash individual causó más de -22%), pero el desgaste real viene de recentrar el rango una y otra vez durante las tendencias sostenidas de cripto (398 y 368
recentrados en 6.7 años) — no de los crashes puntuales. **No se ha conectado al informe ni al bot que sigue corriendo en papel.** Es la primera idea de todo el proyecto que se prueba y se descarta después del
backtest, no antes, y confirma con datos reales la advertencia inicial sobre este tipo de estrategia.

## Bot de rejilla en acciones laterales — mejor que en cripto, pero sigue perdiendo frente a comprar y mantener
Tras rechazar el grid en BTC/ETH (el problema era la tendencia sostenida, no la mecánica), se probó en acciones **elegidas con datos, no de memoria**: sobre las 493 del S&P 500 con ≥15 años de historial se
calculó cuánto tiempo pasa cada una cerca de su precio mediano y su ratio de tendencia. Ganadora: **DOC (Healthpeak Properties, REIT sanitario)**, 71% del tiempo dentro del ±15% de su mediana; también se
probaron FRT y PPL (2ª y 3ª candidatas) para no sacar conclusiones de un solo caso.

**Resultado con 32 años de datos diarios reales (1995-2026):** a diferencia de cripto, el grid **no pierde dinero** en ninguna de las tres (DOC +15.8%, FRT +48.4%, PPL +12.1% en total), y en 2 de 3 tampoco
pierde fuera de muestra (2018-2026). Esto confirma que el problema en BTC/ETH era la tendencia del activo, no la estrategia. **Aun así, se rechaza**: en las tres, comprar y mantener la misma acción gana muchísimo
más (CAGR 7.9-10.4% frente a 0.4-1.9% del grid) con mejor Sharpe, y el margen es tan fino que una comisión fija de bróker (habitual en acciones, no un %) probablemente lo borraría con las 110-140 operaciones/año
que genera. Detalle en `research/2026-09-22-bot-de-rejilla-en-acciones-laterales.md`. No conectado a nada.

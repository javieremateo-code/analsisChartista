# Bot de trading por noticias

Bot que escucha noticias en tiempo real (RSS, NewsAPI, Finnhub, X/Twitter),
detecta eventos relevantes para los mercados (guerras, sanciones, decisiones de
bancos centrales, resultados corporativos, fusiones, quiebras, etc.) y, si pasa
los controles de riesgo, envía automáticamente una orden a Alpaca.

## ⚠️ Advertencia importante

Operar automáticamente en respuesta a noticias es una de las formas **más
arriesgadas** de trading algorítmico:

- Las noticias pueden ser falsas, erróneas, ya descontadas por el mercado, o
  ambiguas — el bot puede reaccionar mal.
- Los movimientos de precio tras una noticia son rápidos y volátiles: hay
  slippage, gaps y el precio de entrada puede ser mucho peor del esperado.
- Ningún clasificador (ni por reglas ni por LLM) es perfecto.
- Esto **no es un consejo de inversión** y no hay garantía de resultados.

Por eso el bot arranca **siempre en modo paper trading** (dinero simulado) a
menos que se confirme explícitamente lo contrario (ver más abajo). Empieza en
paper, vigila su comportamiento durante días/semanas, y sólo pasa a real si
entiendes y aceptas el riesgo.

## Arquitectura

```
Fuentes de noticias  ─┐
 (RSS/NewsAPI/         │
  Finnhub/Twitter)     ▼
                  Deduplicación (SQLite)
                       │
                       ▼
                  Clasificador (reglas o Claude)
                       │  → Signal(ticker, dirección, confianza, motivo)
                       ▼
                  Motor de riesgo (RiskManager)
                       │  límites diarios, tamaño de posición, cooldown, kill switch
                       ▼
                  Broker (Alpaca) → orden de mercado con stop-loss/take-profit
```

- **`bot/news/`** — una fuente por proveedor, todas implementan `fetch_latest()`.
- **`bot/analysis/`** — `KeywordClassifier` (por defecto, sin dependencias
  externas de red) y `ClaudeClassifier` (opcional, usa la API de Anthropic
  para una clasificación más precisa; si falla, cae al clasificador por reglas).
- **`bot/signals.py`** — deduplica noticias ya vistas y aplica cooldown por ticker.
- **`bot/risk.py`** — última línea de defensa: límite de pérdida diaria, nº
  máximo de operaciones/posiciones, umbral de confianza mínima, kill switch.
- **`bot/execution/alpaca_broker.py`** — envía órdenes de mercado con
  stop-loss/take-profit adjuntos (bracket order) para acotar el riesgo de cada
  posición desde que se abre.
- **`bot/storage.py`** — SQLite: log de auditoría de todas las noticias vistas
  y operaciones enviadas.

## Instalación

```bash
pip install -r requirements.txt
cp .env.example .env
# edita .env con tus API keys
```

Necesitas al menos:
- Una cuenta de [Alpaca](https://alpaca.markets) (gratis) para paper trading.
- Opcionalmente: [NewsAPI](https://newsapi.org), [Finnhub](https://finnhub.io)
  y/o acceso de streaming a la API de X para más fuentes de noticias.
- Opcionalmente: una API key de Anthropic si quieres el clasificador basado en
  Claude (`USE_LLM_CLASSIFIER=true`).

## Uso

```bash
python main.py --once   # un solo ciclo, útil para probar la configuración
python main.py           # bucle continuo (respeta POLL_INTERVAL_SECONDS)
```

Al arrancar, el bot imprime un banner indicando claramente si está en modo
PAPER, LIVE, o LIVE bloqueado por falta de confirmación.

## Pasar a trading en vivo (dinero real)

Requiere **las dos** variables en `.env`:

```
ALPACA_PAPER=false
LIVE_TRADING_CONFIRM=YES_I_UNDERSTAND_THE_RISK
```

Sin ambas, el bot sigue detectando y registrando señales pero **nunca** envía
una orden real — es una salvaguarda deliberada, no un bug.

## Gestión de riesgo (`.env`)

| Variable | Qué controla |
|---|---|
| `MAX_POSITION_USD` / `MAX_POSITION_PCT_EQUITY` | Tamaño máximo de cada posición |
| `MAX_DAILY_LOSS_USD` | Pérdida realizada máxima antes de dejar de operar por hoy |
| `MAX_OPEN_POSITIONS` / `MAX_TRADES_PER_DAY` | Límites de exposición y frecuencia |
| `COOLDOWN_MINUTES_PER_TICKER` | Evita re-operar el mismo ticker por noticias repetidas |
| `MIN_CONFIDENCE` | Confianza mínima (0–1) de una señal para poder ejecutarse |
| `STOP_LOSS_PCT` / `TAKE_PROFIT_PCT` | Adjuntos a cada orden como bracket order |

`RiskManager` también expone un **kill switch** manual (`trip_kill_switch`)
que bloquea toda nueva operación hasta reiniciar el proceso.

## Clasificación de noticias

Por defecto se usa `KeywordClassifier`: coincidencia de palabras clave sobre
categorías macro (guerra, sanciones, subida/bajada de tipos, etc. →
tickers/ETFs como `LMT`, `USO`, `SPY`, `TLT`) y eventos de empresa (resultados,
quiebras, fusiones → ticker de la compañía mencionada). Las listas están en
`bot/analysis/tickers.py` y **están pensadas para ampliarse** según tu
universo de inversión — es un punto de partida, no una lista exhaustiva.

Activando `USE_LLM_CLASSIFIER=true` (+ `ANTHROPIC_API_KEY`), cada noticia se
envía a Claude para decidir relevancia, dirección y tickers de forma más
matizada que las reglas fijas. Tiene coste por llamada y algo más de latencia;
si la llamada falla, se usa automáticamente el clasificador por reglas.

## Tests

```bash
pytest -q
```

Los tests cubren el clasificador por reglas, el motor de señales (dedupe +
cooldown) y el gestor de riesgo — toda la lógica que no depende de red ni de
credenciales reales.

## Limitaciones conocidas / próximos pasos sugeridos

- El streaming de X/Twitter (`bot/news/twitter_source.py`) requiere un plan de
  pago de la API de X con acceso a filtered stream.
- NewsAPI en su capa gratuita tiene delay y límite de peticiones; no es apta
  para producción 24/7.
- No hay gestión de posiciones existentes más allá del stop-loss/take-profit
  inicial (no hay trailing stop ni cierre manual desde el bot).
- No se ha probado en este entorno de desarrollo contra feeds reales porque la
  red saliente está restringida a un conjunto limitado de dominios (proxy del
  entorno); pruébalo en tu máquina/servidor antes de confiar en él.

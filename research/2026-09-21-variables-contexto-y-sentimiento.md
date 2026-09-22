# Variables 3 y 4: tendencia previa + mini-bajada, y señales de noticias/sentimiento

**Estado**: estudiado en 4 clases (cripto 41-45, forex 30, commodities 18 ETFs, acciones S&P 500). Nada nuevo queda VALIDADO;
una candidata queda en observación.

## Variable 3 — tendencia previa y mini-bajada (¿compensa comprar y mantener?)
Contexto: tendencia previa fuerte (>=3 días y >=2σ) y luego una racha contraria; se mide el retorno posterior en la
dirección de la tendencia (1, 2, 3, 5, 10 días) y cuántos días más continúa.

- Tras la mini-bajada, la tendencia NO continúa de forma distinta al azar: P(sube mañana) ≈ 50-53% en todas las clases y la
  reanudación dura de media ~1 día (P(>=3 días) ≈ 12%), igual que sin condición.
- Exceso sobre la deriva del mercado (neto de costos), regla A "comprar mini-bajada en tendencia alcista":
  * Acciones: 1d -0.10% (t=-4.4), 5d -0.06%, 10d -0.01%. Mantener más días solo captura la deriva.
  * Cripto: dentro de muestra +4.9% (5d, t=4.7) pero FUERA de muestra -0.05% (t=-1.2): el efecto era del mercado alcista 2017-21.
  * Forex y commodities: ~0.
- El "retroceso" (% de la tendencia deshecho) no separa nada para caídas fuertes: casi todas las caídas >=3σ borran >=100% de la subida previa.
- Tendencia BAJISTA + rebote pequeño -> corto (cripto): la caída continúa el 62%; corto 1 día: CAGR +6.6% (OOS +6.3%, Sharpe 0.47) pero con
  costos de corto (+0.15%/lado) baja a +3.8% (OOS +2.3%), y el peor día de un corto fue +36%. NO valida el criterio (OOS Sharpe >= 0.5).

## Variable 4 — noticias / sentimiento durante la subida previa
- Noticias reales (GDELT): solo se pudo bajar 1 año de una serie por límites de velocidad (HTTP 429); el colector es reanudable
  (`python -m scripts.collect_news`). Nunca podrá ser por acción individual (solo mercado/tema). SIN RESULTADO todavía.
- Proxies históricos completos: Fear&Greed (cripto, 2018+) y VIX (resto).
  * VIX bajo (complacencia) NO anticipa recortes; VIX alto empeora algo comprar mini-bajadas (t≈-2.3 en forex/commodities, efecto pequeño).
  * Cripto, Fear&Greed >= 75 en la mini-bajada: la tendencia SE REANUDA con más fuerza (contrario a "aviso de recorte"):
    5d neto +7.1% (n=525, t≈4.9) frente a +1.0% sin codicia; monótono con el umbral (50: +3.7%, 80: +9.2%); OOS +7.1%.
    Aporta más allá del régimen (BTC>SMA200: +7.1% con F&G>=75 vs +1.3% sin). Cartera h=10d: OOS CAGR +6.6% Sharpe 1.15.
  * Límites: solo ~23 episodios independientes; la parte OOS descansa sobre todo en 2024; F&G mezcla momentum/volatilidad/redes.
  => CANDIDATA 'codicia_mini_bajada' en observación (screener/candidates.py). Pendiente de paper trading.

**Decisión**: pendiente (del usuario). Sugerido: paper trading de la candidata + seguir descargando GDELT para evaluar noticias reales.

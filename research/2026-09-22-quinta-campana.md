# Quinta campaña: dimensionado por Kelly, stop por volatilidad, señal doble y estacionalidad

**Estado**: completada (scripts/optimize_kelly_stop.py). Adoptado: tope de posición moderado (NO Kelly completo) y stop de catástrofe ajustado a la volatilidad de cada moneda.
No adoptado: señal doble (inconsistente IS/OOS) y estacionalidad por día de semana (ruido, muestras de 35-126 eventos).

## G1) Kelly fraccionario — se prueba, se entiende por qué funciona, y se RECHAZA la versión completa
Con la probabilidad del modelo (ensemble) y el ratio ganancia/pérdida histórico walk-forward (b≈1.2-1.5), el Kelly fraccionario mejora el replay balanceado:
actual +9.1%/Sharpe 0.95/DD -6.7% -> Kelly x0.25 +10.4%/0.98/-6.9% -> x0.5/x0.75/x1.0 todos +10.9%/0.99/-7.1% (idénticos entre sí).
**Diagnóstico:** la fracción de Kelly calculada (mediana f≈0.71, con el 94% de los eventos por encima del tope del 15%) satura el tope casi siempre — el resultado es indistinguible de subir el tope de posición sin más
(comprobado: heurística actual con tope subido a 15% da +10.8%/1.00/-8.6%, prácticamente igual que "Kelly"). El Kelly no está siendo selectivo; es una forma sofisticada de decir "apuesta el máximo permitido".
**Riesgo de adoptar Kelly completo:** Kelly completo es conocido por ser extremadamente sensible a errores de estimación de p y b — sobreestimar la ventaja un poco lleva a sobreapostar mucho, y esto es aún más peligroso
aquí porque la campaña anterior (F2) ya encontró que las señales del mismo día están correlacionadas ~5.6x más de lo que el dimensionado asume. Poner varias posiciones cerca de Kelly completo en un día de pánico
sistémico multiplicaría ese riesgo ya identificado. **Se rechaza Kelly como criterio de dimensionado.**

## Adoptado: tope de posición moderado (no Kelly, la misma heurística de siempre con más margen)
El tope anterior (max_w 10/10/30%) dejaba capital sin invertir en los días con pocas señales buenas, porque max_exposure permite hasta 100% pero cada posición no podía superar el tope individual.
Subir el tope moderadamente SÍ mejora limpiamente CAGR, Sharpe y "sin 5 mejores días" con una caída máxima que sigue dentro de lo razonable:
- Balanceado: max_w 10%->13% (tope efectivo con el modelo ~18%): +9.1%->+10.2%, Sharpe 0.95->0.98, DD -6.7%->-8.1%.
- Conservador: apenas cambia (su propio dimensionado por riesgo/pérdida raramente satura el tope); se sube igualmente a 12% por consistencia, efecto ~+0.1pp.
- Agresivo: max_w 30%->35%: +14.7%->+15.4%, Sharpe 1.02->1.04, DD -15.5%->-15.8%.
Implementado en `screener/risk.py` (PROFILES). Monte Carlo balanceado con el nuevo tope: mediana 1 año con 1000€ +74€ (antes +63€), peor 5% -8€ (antes -5€): más ganancia esperada con algo más de cola.

## G2) Stop de catástrofe ajustado a volatilidad — ADOPTADO (solo regla diaria)
Con velas horarias REALES (mismo método que validó el -30% fijo, `scr_hourly_events100.pkl`, 530/530 eventos con datos): un stop = 6x la desviación típica diaria de 60d de cada moneda (con
suelo 10% y techo 45%) mejora el retorno medio frente al -30% fijo (+3.54% -> +4.16%) con un peor caso similar (-30.6% vs -30.2%) y se sostiene fuera de muestra (n=430, +3.77% frente a +3.54% dentro de muestra del fijo).
Lógica: monedas de baja volatilidad (BTC, ETH) reciben un stop más ceñido (p.ej. -19% en el ejemplo probado) y las de alta volatilidad uno más ancho (p.ej. -28%), en vez de un -30% igual para todas.
Implementado en `screener/risk.py` (`catastrophe_stop()`), conectado en `bot/strategy.py` (Signal.stop_pct, solo regla diaria) y `scripts/daily_report.py` (columna de la orden). La regla de 4h sigue con el -30% fijo
(no se ha validado un ajuste por volatilidad específico para esa escala). Sin dato de volatilidad, se usa el techo (45%, el más prudente).

## G3) Señal doble (diaria + racha extrema de 4h el mismo día) — NO ADOPTADA
172 eventos con señal doble: dentro de muestra parece mucho mejor (+12.29% vs +3.31% solo diaria) pero fuera de muestra es ligeramente PEOR (+3.34% vs +4.09%): inconsistencia IS/OOS clásica de sobreajuste
con pocos casos (28 eventos IS). No hay motivo para creer que la señal doble aporta información adicional real.

## G4) Estacionalidad por día de la semana — NO ADOPTADA (solo para descartar un efecto obvio)
Con 35-126 eventos por día de la semana, cualquier diferencia es ruido esperable (rango neto/operación de +0.03% a +11.30% entre días, sin patrón económico defendible). Viernes muestra P(sube)=55% con
108 casos OOS (el más bajo de todos), pero con IS de solo 5 casos no se puede confirmar como algo más que azar entre 7 comparaciones. No se implementa ningún filtro por día de la semana.

## Cifras finales del sistema recalculadas (balanceado, con capa de tendencia 20%, replay 2020-2026)
CAGR +29.2%, Sharpe 1.78, DD -10.7% (2022+ +27.7%, Sharpe 1.68); mediana 1 año con 1000€: +274€, peor 5%: +56€.

**Decisión**: pendiente (del usuario).

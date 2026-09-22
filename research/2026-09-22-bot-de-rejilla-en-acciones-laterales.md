# Bot de rejilla en acciones genuinamente laterales — funciona mejor, pero sigue sin ser buena idea

**Estado**: completado (`scripts/study_grid_stock.py`, mismo simulador ya validado `screener/grid.py`). **No se conecta a nada.** Sigue las mismas reglas de decisión que el resto del proyecto.

## Selección de la acción (con datos, no con memoria)
Sobre las 493 acciones del S&P 500 con ≥15 años de historial, se calculó para cada una, en los últimos 15 años: el ratio de eficiencia de Kaufman (movimiento neto ÷ suma de movimientos absolutos: 0 = lateral
puro, 1 = tendencia pura) y el % de sesiones dentro del ±15% de su precio mediano, exigiendo además que no fuera una acción casi arruinada (caída máxima > -70%, rango total < 200%, para no confundir "lateral"
con "se desplomó y luego recuperó todo").

**Ganadora: DOC (Healthpeak Properties, REIT sanitario)** — 71% del tiempo dentro del ±15% de su mediana en 15 años, el ratio de tendencia más bajo de la lista. Tiene sentido: los REIT cotizan más ligados a su
rentabilidad por dividendo que al crecimiento. Segundas y terceras candidatas por el mismo criterio: **FRT** (Federal Realty, otro REIT) y **PPL** (PPL Corporation, eléctrica regulada) — se probaron las tres
para no sacar conclusiones de un solo caso elegido a dedo.

## Resultado: 32 años de datos diarios reales (1995-2026), mismo cortafuegos obligatorio que en cripto

| | Comprar y mantener | Rejilla (32 años) | Rejilla hasta 2018 | Rejilla 2018-2026 (con el Covid) |
|---|---|---|---|---|
| **DOC** | +1017% (CAGR +7.9%, Sharpe 0.40) | +15.8% (CAGR +0.5%, Sharpe 0.11) | +22.2% | **-5.2%** |
| **FRT** | +2213% (CAGR +10.4%, Sharpe 0.49) | +48.4% (CAGR +1.3%, Sharpe 0.22) | +40.7% | +5.4% |
| **PPL** | +1540% (CAGR +9.2%, Sharpe 0.49) | +12.1% (CAGR +0.4%, Sharpe 0.10) | +4.7% | +7.1% |

**A diferencia de BTC/ETH, aquí el grid NO pierde dinero en el conjunto de los 32 años en ninguna de las tres, y en 2 de 3 (FRT, PPL) tampoco pierde en el tramo fuera de muestra.** El cortafuegos saltó mucho
menos (9-14 veces en 32 años, frente a las 29-40 veces en 6.7 años de cripto), confirmando que estas acciones son realmente más tranquilas. Esto confirma la hipótesis de partida: el problema de BTC/ETH no era
la mecánica de la rejilla en sí, era la tendencia sostenida del activo.

## Por qué, aun así, sigue sin ser buena idea

1. **Gana muchísimo menos que simplemente comprar y mantener la misma acción** — en las tres, tanto en retorno total (CAGR 0.4-1.9% de la rejilla frente a 7.9-10.4% de comprar y mantener) como en Sharpe
   (0.07-0.32 de la rejilla frente a 0.40-0.49 de comprar y mantener). Incluso en el mejor caso analizado, habría sido mejor comprar la acción y no tocarla.
2. **Los márgenes son tan finos que una comisión real los borra.** Con DOC, subir la comisión de 0.05% a solo 0.10% por operación deja el resultado en prácticamente cero, y a 0.20% ya es negativo. Con
   3.500-4.400 operaciones en 32 años (~110-140 al año), **muchos brókers de acciones cobran una comisión FIJA por operación (no un porcentaje)** — con una cuenta de 1000€ repartida en 15 niveles (~65€ cada
   uno), una comisión fija de solo 1-2€ por operación ya supera el 0.05-0.10% asumido aquí. Es muy probable que en la práctica esto pierda dinero por comisiones, no que gane los pocos euros del backtest.
3. **La acción se eligió MIRANDO HACIA ATRÁS.** Que DOC, FRT o PPL hayan sido laterales los últimos 15 años no garantiza que lo sigan siendo — de hecho, DOC pasó de ir muy bien hasta 2018 a perder dinero
   después. No hay forma de saber HOY qué acción será lateral los próximos 15 años; solo se puede comprobar con el tiempo, igual que con las tres décadas de historia usadas aquí.
4. **No compensa el riesgo de ejecución** (spread más ancho que en cripto, mercado cerrado fuera de horario, dividendos y ajustes corporativos) frente a un rendimiento que ya de por sí es marginal.

## Decisión
**Rechazado, con matices.** Es un resultado más interesante que el de cripto (no pierde dinero, y confirma que el diagnóstico del rechazo anterior era el correcto: la tendencia sostenida, no la mecánica de
la rejilla), pero la conclusión práctica es la misma: **el dinero y el esfuerzo rendirían más simplemente comprando la acción y no haciendo nada.** No se conecta a ningún informe ni bot.

**Decisión**: pendiente (del usuario).

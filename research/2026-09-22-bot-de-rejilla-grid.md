# Bot de rejilla (grid trading) — probado a fondo y RECHAZADO

**Estado**: completado (`screener/grid.py`, `scripts/study_grid.py`). **No se conecta al bot ni al informe.** Es el primer módulo de todo el proyecto que se descarta tras el backtest, no antes.

## Motivación
El usuario pidió explícitamente un bot que "gane dinero cada hora, aunque sean céntimos". Se explicó que ningún bot puede garantizar eso, y que lo más parecido que existe en la práctica es un bot de grid (compra
escalonada en un rango, vende cuando sube un peldaño) — con el riesgo conocido de "recoger céntimos delante de una apisonadora": funciona en mercado lateral y pierde de golpe cuando el precio rompe con fuerza en
una dirección. El usuario aceptó construirlo y probarlo con el mismo rigor que el resto del proyecto.

## Bug encontrado y corregido ANTES de sacar conclusiones
La primera implementación tenía un fallo real: al armar la rejilla, cualquier línea situada por encima del precio inicial se "compraba" en la primera vela, porque la condición de cruce (`low <= línea`) es
trivialmente cierta para cualquier línea por encima del precio corriente, sin comprobar que el precio la hubiera cruzado de verdad viniendo desde arriba. Esto inflaba artificialmente el número de posiciones
abiertas y las pérdidas al saltar el cortafuegos (una simulación de crash sintético daba -31.5% cuando el cálculo a mano decía ~-5%). Se corrigió exigiendo un cruce real (el precio debe haber estado al otro lado
de la línea en la vela anterior), verificado primero contra el cálculo manual y luego con 4 tests unitarios (`tests/test_grid.py`, precios sintéticos: oscilación lateral, crash sostenido, pausa tras el
cortafuegos, sensibilidad a la comisión) antes de correr el backtest histórico. Sin este paso, el resultado del backtest habría sido artificialmente peor de lo real — pero el resultado real tampoco es bueno.

## Backtest histórico: BTC y ETH, velas horarias reales, 2020-2026 (58.924 velas, incluye todos los grandes crashes)
Configuración base: rango ±12%, 20 niveles, comisión 0.1% (orden límite), cortafuegos si el precio rompe el rango por más de un 3% (liquida a mercado con 0.5% de deslizamiento y pausa 7 días), recentrado cada 21 días.

| | Comprar y mantener | Rejilla CON cortafuegos | Rejilla SIN cortafuegos |
|---|---|---|---|
| **BTC** | +1098% (CAGR +44.7%, DD -77%) | **-39.2%** (CAGR -7.1%, DD -54.1%) | -16.5% (DD -46.7%) |
| **ETH** | +2028% (CAGR +57.6%, DD -81%) | **-32.8%** (CAGR -5.7%, DD -72.3%) | -52.6% (DD -71.2%) |

**El cortafuegos SÍ funciona como debe:** en cada uno de los 5 grandes crashes probados (marzo 2020, mayo 2021, LUNA, Celsius/3AC, FTX) la caída quedó contenida entre -4% y -22% (el peor caso, ETH en marzo 2020,
por ser el crash más violento y rápido de todos). Estas pérdidas puntuales son razonables y es justo lo que el cortafuegos está diseñado para evitar que sea peor.

**El problema real no son los crashes — es el desgaste estructural durante una tendencia sostenida.** BTC y ETH han estado en una tendencia alcista fuerte la mayor parte de 2020-2026. Una rejilla apuesta a que
el precio vuelve a su rango; cuando no vuelve (porque el mercado sube o baja de forma sostenida durante semanas), cada recentrado obliga a cerrar posiciones a un precio peor que el de apertura (vender barato o
comprar caro respecto a la tendencia). Con 398-368 recentrados en 6.7 años, ese desgaste acumulado es lo que explica la mayoría de la pérdida, no los 29-40 saltos del cortafuegos.

- **Dentro y fuera de muestra:** BTC pierde en ambos periodos (2020-22: -33.0%; 2023-26: -9.1%). ETH gana modestamente dentro de muestra (+9.1%) pero pierde con fuerza fuera de muestra (-38.4%): no es un
  resultado que se sostenga de forma fiable.
- **Sensibilidad a la comisión:** el resultado empeora de forma monótona con más comisión (como debe ser), y con la comisión más barata probada (0.05%) sigue siendo negativo en ambas monedas.
- **Sensibilidad al rango:** con un rango muy ancho (25% en BTC) el resultado se vuelve positivo, pero eso ya no es "ingresos de rejilla" — es básicamamente mantener una posición larga diluida que casi no
  vende nunca, pareciéndose cada vez más a comprar y mantener con comisiones de por medio. Elegir ese parámetro después de ver que los demás fallan sería el mismo sobreajuste que este proyecto ha evitado
  sistemáticamente en todo lo demás, así que no se adopta.

## Criterio de adopción (fijado antes de ver resultados) — NO SE CUMPLE
Se exigía: retorno neto positivo en el periodo completo con el cortafuegos activo, ninguna caída por crash superior al 25%, y que se sostuviera tanto en 2020-2022 como en 2023-2026.
La parte del cortafuegos se cumple. **La rentabilidad no se cumple: pierde dinero en la configuración realista, en las dos monedas, en la mayoría de los sub-periodos.**

## Decisión
**Rechazado. No se conecta ni al informe ni al bot que ya está corriendo en papel.** Es la confirmación, con datos reales y no solo con el argumento teórico, de la advertencia inicial: un bot que "gana céntimos
todo el rato" en cripto no sobrevive a las tendencias fuertes que este mercado tiene con frecuencia, y el desgaste no viene solo de los crashes puntuales sino del propio funcionamiento de la estrategia.

**Vías abiertas si se quiere seguir explorando esto** (no hechas, por presupuesto de esta sesión): probar la rejilla en pares con historial más lateral que BTC/ETH (aunque eso reduce la liquidez disponible),
o combinarla con el filtro de tendencia ya validado en este proyecto (pausar la rejilla cuando BTC esté en tendencia fuerte, usando la misma lógica de `screener/trend.py`) para evitar operar precisamente
cuando más pierde. Ninguna de las dos se ha probado todavía.

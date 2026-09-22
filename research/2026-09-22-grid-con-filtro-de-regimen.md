# Opción 3: grid que se apaga en tendencia — mejora algo en BTC, pero no es robusto (rechazado)

**Estado**: completado (`screener/regime.py`, `screener/grid.py` con parámetro `gate`, `scripts/study_grid_regime.py`). **No se conecta a nada.**

## Idea y diseño
En vez de elegir un activo "lateral para siempre" (no existe de forma fiable — DOC dejó de serlo en 2018), se apaga la rejilla (no abre posiciones nuevas ni recentra, que es la operación que más desgaste
genera) cuando el propio mercado está, ahora mismo, en tendencia fuerte. Se usa el mismo ratio de eficiencia de Kaufman ya empleado para elegir las acciones laterales, pero calculado de forma continua sobre una
ventana móvil (`screener/regime.py`). El cortafuegos y la venta de lo que ya se tenía siguen activos siempre, pase lo que pase con el filtro.

## Dos bugs encontrados y corregidos antes de sacar conclusiones
1. Al integrar el filtro, el cortafuegos podía "saltar" (registrar una pérdida y una pausa) sin que hubiera ninguna posición abierta que proteger, simplemente porque el precio llevaba mucho tiempo sin
   recentrarse por estar la puerta cerrada. Se corrigió: el cortafuegos solo actúa si de verdad hay algo invertido.
2. Si la puerta se cerraba con una posición abierta y luego se reabría, el rearmado **descartaba esa posición sin liquidarla ni contabilizar su resultado** — un fallo real de pérdida silenciosa de datos, no
   solo un matiz. Se corrigió liquidándola primero (igual que ya hace un recentrado normal). Ambos bugs quedaron fijados con tests (`tests/test_grid.py`, `tests/test_regime.py`) antes de tocar datos reales.

## Backtest: BTC y ETH, velas horarias reales 2020-2026, ventana y umbral elegidos SOLO con datos hasta 2023
Barrido pre-declarado: ventanas de 7/14/21/30 días, umbrales de eficiencia 0.08/0.12/0.18/0.25 (16 combinaciones). Se elige la de mejor Sharpe dentro de muestra (hasta 2023) y se evalúa después en 2023-2026,
nunca al revés.

**BTC** — mejor combinación (ventana 7 días, umbral 0.18, puerta abierta el 89% del tiempo):
| | Rejilla sin filtro | Rejilla con filtro | Comprar y mantener |
|---|---|---|---|
| Fuera de muestra (2023-26) | CAGR -2.5%, Sharpe -0.16, DD -19.0% | **CAGR +1.9%, Sharpe 0.27, DD -13.7%** | CAGR +55.7%, Sharpe 1.19 |

Aquí sí se cumple el criterio: mejora sobre la rejilla sin filtro y da positivo fuera de muestra.

**ETH** — la MISMA metodología (elegir por mejor Sharpe dentro de muestra) selecciona ventana 7 días, umbral 0.25 (puerta abierta el 97% del tiempo, casi sin filtrar nada), y el resultado fuera de muestra es
**peor que sin filtro** (CAGR -20.7%, Sharpe -0.94, frente a -12.2%/-0.65 sin filtro). El propio proceso de selección, aplicado con el mismo rigor, eligió mal en este caso: sobreajuste de la ventana dentro de
muestra que no se sostuvo después.

## Por qué se rechaza a pesar de la mejora en BTC
1. **No es robusto entre los dos activos que se han probado.** El mismo procedimiento honesto (elegir con datos anteriores, evaluar después) funciona en uno y falla en el otro. Con solo 2 casos y un resultado
   dividido, no hay base para confiar en que se repita.
2. **Incluso en el mejor caso (BTC), sigue muy lejos de comprar y mantener** (Sharpe 0.27 frente a 1.19; CAGR +1.9% frente a +55.7%).
3. **La tabla completa del barrido (16 combinaciones x 2 monedas) muestra que el resultado depende mucho de qué ventana y umbral se elija**, sin una zona claramente estable — varias combinaciones con pésimo
   Sharpe dentro de muestra dan buen resultado fuera de muestra y viceversa, lo que indica que la señal real es débil frente al ruido de la muestra, no un patrón fiable.
4. **En ETH, el periodo 2023-2026 fue estructuralmente malo para el grid con o sin filtro** (todas las 16 combinaciones dan CAGR fuera de muestra negativo): confirma, otra vez, que una tendencia alcista lo
   bastante fuerte y sostenida se come cualquier intento de gatear la rejilla por régimen.

## Decisión
**Rechazado.** La idea tenía una lógica sólida (atacar la causa real del desgaste en vez de esperar encontrar un activo mágicamente quieto) y mejoró de forma honesta en uno de los dos casos probados, pero no
se sostiene con la fiabilidad que este proyecto exige antes de conectar algo a un informe o a un bot. Queda como el intento más cercano a "hacer funcionar el grid en cripto" de los tres probados (BTC/ETH sin
filtro, acciones laterales, BTC/ETH con filtro de régimen), y también el más claramente descartado por falta de robustez, no por pérdidas catastróficas.

**Decisión**: pendiente (del usuario).

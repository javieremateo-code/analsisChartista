# Cuarta campaña: tiempo de mantenimiento, correlación entre señales simultáneas y conjunto de modelos

**Estado**: completada (scripts/optimize_hold_risk.py). Adoptado: conjunto de 5 modelos (integrado en `screener/ml_score.py`, producción). No adoptado: extender el mantenimiento; corrección de tamaño por señales simultáneas.
Hallazgo de riesgo importante sin acción de talla única: las señales del mismo día están muy correlacionadas.

## F1) Tiempo de mantenimiento (perfil balanceado, con modelo, replay 2020-2026)
Mantener más de 1 día empeora con fuerza y de forma monótona: 1d CAGR +8.9%/Sharpe 0.94/DD -6.4%; 2d +5.8%/0.63/-16.7%; 3d +4.0%/0.40/-21.5%; 5d -0.3%/0.02/-21.4%.
El horizonte "adaptativo" (elegido por magnitud con datos <2022) escogió 1 día en todos los tramos — confirma que 24h ya es el óptimo, no una elección arbitraria. El rebote es un pico de pánico
que se revierte parcialmente después del primer día, no el inicio de una tendencia: coherente con toda la evidencia previa del proyecto (TP también perjudicaba, ver segunda campaña).

## F2) Correlación entre señales simultáneas — HALLAZGO DE RIESGO
En los días con >=2 señales (z>=3) simultáneas (53 de 119 días con señal): el 76% de los pares de monedas se mueven en el MISMO sentido al día siguiente (el azar sería 50%).
La desviación típica real del retorno medio de esos días es 6.8%, frente al 2.9% que asumiría el dimensionado si las posiciones fueran independientes: **el riesgo real de un día
con varias señales es ~5.6x el que asume el sistema al sumar riesgos por posición como si no estuvieran correlacionados.**
- Corrección "uniforme" (atenuar el tamaño de cada posición según el nº de señales del día): CAGR y DD bajan proporcionalmente, el Sharpe no cambia (0.94 -> 0.94): es solo desapalancar, no mejora la eficiencia. No adoptada.
- Límite de exposición TOTAL solo en días con >=3 señales (80%): Sharpe SÍ mejora (0.94->0.96, 2022+ 1.12->1.16) y DD mejora (-6.4%->-6.0%), pero el CAGR baja (+8.9%->+7.8%): no pasa el criterio estricto
  (que exige CAGR Y Sharpe mejores), pero es una alternativa legítima más conservadora si se prioriza el Sharpe sobre el CAGR absoluto.
**Implicación para el usuario**: las cifras de "riesgo €" del informe diario, que sí sizean cada posición por su propio percentil 5, SUMAN esos riesgos como si fueran independientes en los días con
varias señales — en la práctica el riesgo conjunto de esos días es mayor. El kill switch (-50% desde el máximo) y el freno diario (-10%) siguen siendo la protección real ante esto, no el "riesgo € conjunto" que se muestra.

## F3) Conjunto de 5 modelos frente a 1 solo — ADOPTADO
Walk-forward trimestral, AUC medio por trimestre: 1 modelo 0.638 (desviación entre trimestres 0.144) vs conjunto de 5 (bootstrap + semillas) 0.625 (desviación 0.150): el AUC medio no mejora,
pero el conjunto SÍ mejora la cartera resultante: CAGR +8.9%->+9.1%, Sharpe 0.94->0.95, 2022+ +13.0%->+13.2% (1.12->1.14), DD -6.4%->-6.7% (dentro del límite de 1.5x), "sin 5 mejores días" +2.4%->+2.5%.
Es una mejora pequeña pero real y en la dirección correcta en las tres métricas: probablemente reduce el ruido de un único árbol en las operaciones límite (cerca del umbral 0.60), no porque prediga mejor en promedio.
**Adoptado en producción**: `screener/ml_score.py` entrena y puntúa con un conjunto de 5 modelos (semilla 0 con todos los datos, semillas 1-4 con remuestreo bootstrap), usado por el informe y el bot.
Cifras finales del sistema completo recalculadas con el conjunto (balanceado, con capa de tendencia 20%): CAGR +27.6%, Sharpe 1.79, DD -9.8%, 2022+ +25.9% (Sharpe 1.68); mediana 1 año con 1000€: +259€, peor 5%: +54€.

**Decisión**: pendiente (del usuario) sobre F2 (límite de exposición más conservador en días de pánico sistémico).

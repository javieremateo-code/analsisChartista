# Tercera campaña: acierto, operaciones por día, otros activos y apalancamiento

**Estado**: completada (scripts/optimize_more.py). Adoptado: dial de confianza (--min-prob) y apalancamiento simulado (--leverage, máx. 2x). Sin ventaja nueva en otros activos ni en más monedas.

E1 calidad/cantidad, balanceado: umbral P 0/0.6/0.7/0.8/0.9 -> operaciones 276/229/187/139/89, acierto 66/69/71/76/80%, neto/op +2.0/+2.8/+3.1/+4.0/+5.1%, CAGR +8.5/+8.9/+8.3/+8.1/+6.9%.
  Con tamaño para caída -10%: +12.6/+14.0/+13.2/+14.8/+22.9% (x1.5/x1.6/x1.6/x1.8/x3.4). Acierto por tramo de P: 0.6-0.7 60%, 0.7-0.8 59%, 0.8-0.9 70%, 0.9-1.0 78% (neto +4.9%, n=79, pocos episodios).
E2 universo 200 (164 monedas activas, liquidez>=5M): eventos z>=3 desde 2020 716 vs 505, 4.6 vs 4.7 por día con señal; balanceado +7.4%/0.89 vs +8.9%/0.94; agresivo +16.6%/0.97/-16.6% vs +14.6%/1.02/-14.2%. Sin mejora.
E3 filtros de otros activos sobre tendencia BTC+ETH: sin filtro +45.9%/1.06 (OOS +22.9%/0.80); S&P>SMA200 +43.2%/1.05 (OOS +10.1%/0.47); VIX<30 +46.2%/1.09 (OOS +22.8%/0.80); dólar<SMA100 +20.5%/0.75 (OOS +11.1%/0.70). Ninguno cumple el criterio.
E4 apalancamiento sistema balanceado con capa de tendencia (financiación 6%): 1x +27.5%/1.78/-9.8%; 1.5x +40.7%/1.71/-14.7%; 2x +54.7%/1.67/-19.3%; 3x +84.6%/1.64/-28.1% (P(DD>30%) 7%); 5x +151%/1.61/-43.6% (P(DD>50%) 3.9%).
  Selectivo x2/x3 en P>=0.85: +10.5%/0.99/-7.8% y +10.7%/0.95/-9.2% frente a +8.9%/0.94/-6.4% sin apalancar.
Conclusión: la probabilidad de acierto se puede subir (hasta ~80%) a costa de operar menos; el retorno se multiplica con el tamaño/apalancamiento pero el riesgo lo hace igual; no hay más ventaja estadística en otros activos.
**Decisión**: pendiente (del usuario).

# Segunda campaña de mejora: otros activos, tendencia y factores

**Estado**: completada (scripts/optimize_ideas.py). Adoptado: capa de tendencia BTC/ETH (opcional por perfil). No adoptado: pistas de otros activos en el modelo, factores.

## A) Pistas de otros activos (modelo walk-forward, perfil balanceado, 2020-2026)
Modelo actual +8.9% / Sharpe 0.94 (AUC 0.581). + mercados externos +9.7% / 1.01 (AUC 0.578). + funding +9.2% / 0.94. + caída relativa a BTC +8.8% / 0.92. + todo +8.9% / 0.96.
Solo "mercados externos" pasa CAGR y Sharpe pero incumple el criterio completo ('sin 5 mejores días' 2.9% vs 2.4% ok; el criterio de DD pasa; la mejora es de 0.8 puntos): marginal.
Patrón con mecanismo (z>=3): S&P sube a 5d -> P(rebote) 57%, neto -0.33% (n=113; OOS -0.79%); S&P cae 0..-5% -> 75%, +4.9%; S&P cae >=5% -> 94%, +9.3%; VIX>25 -> 86%, +8.3% (IS +7.3%, OOS +8.8%).
Filtro 'S&P no sube': balanceado +6.9% / 0.91 / DD -2.8% (sin modelo); con modelo +8.3% / 0.89 / -2.9%; agresivo con modelo +14.6% -> +11.3% pero DD -14.2% -> -8.8%. Es reducción de riesgo, no de retorno.

## B) Capa de tendencia
BTC SMA100/150/200: CAGR +48/+47/+34%, Sharpe 1.13/1.12/0.89, DD -39/-45/-64%; 2022-26 +22.6/+29.3/+29.4% (Sharpe 0.79/0.95/0.94, DD -37/-26/-32%) frente a comprar y mantener +12.7% (0.49, -67%).
Ventanas 50-250: meseta 100-200 (250 más débil: OOS 0.70). Ensamble SMA100/150/200: BTC +43.6% / 1.07 / -48.6% (OOS +27.4% / 0.92); ETH +40.8% / 0.89 (OOS +16.2% / 0.58); BTC+ETH 50/50 +45.9% / 1.06 (OOS +22.9% / 0.80, DD -29.6%).
Tiempo en mercado 53%, ~25 cambios de posición por año. Peor día -22.3% (2020-03-12), peor mes -29.1%; por año: 2018 -3%, 2019 +59%, 2020 +164%, 2021 +114%, 2022 -19%, 2023 +72%, 2024 +60%, 2025 +3%, 2026 +14%.
Correlación con las reglas de rebote 0.00; con BTC 0.73. Sistema balanceado + 15/25/35/50% en tendencia: CAGR +24.7/+30.2/+35.8/+43.9%, DD -8.2/-12.2/-17.0/-23.8%.

## C) Factores entre monedas (long-only, quintil superior, rebalanceo semanal, costos)
momentum 30d +53.7% (OOS +6.5%), momentum 90d +31.2% (OOS -13.5%), reversión 7d -7.4%, baja volatilidad +32.0% (OOS -2.8%), volumen creciente +23.4%, cerca de máximos 30d +52.5% (OOS -7.6%): todos con DD -80/-90%. Sin ventaja sobre BTC.

**Decisión**: pendiente (del usuario). Siguiente paso: paper trading del sistema completo, prestando atención a la capa de tendencia (es la que más depende del régimen de mercado).

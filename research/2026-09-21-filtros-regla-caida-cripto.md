# ¿Mejora alguna variable la regla validada de cripto (comprar tras caída >=3σ de 2+ días)?

**Estado**: estudiado (`scripts/study_crash_filters.py`). Una variable aporta reducción de riesgo; ninguna aporta retorno extra fiable.

Datos añadidos: volumen diario (USDT) y funding rate de perpetuos (45 monedas). Conjunto principal: 510 eventos (107 fechas, 50 episodios
independientes); amplio (z>=2): 2192 eventos. Sin filtrar: neto +4.0% a 1 día, P(sube) 75%.

## 1) Univariante (52 cubetas, terciles fijados con 2017-2021)
- Esperables por azar con |t|>=2: ~3; observadas: 13; con |t|>=3.5: 0. 5 cubetas ★ (|t|>=2.5, n>=150, mismo signo IS/OOS), todas flojas.
- Fear & Greed NO mejora la regla: codicia extrema da +2.6% (peor que el +4.0% base); miedo extremo +5.5% (no significativo).
- Volumen, funding, fin de semana, tamaño de moneda, longitud de racha: sin efecto útil.
- Patrón consistente (Δ positivo en IS y OOS): "capitulación sistémica" — BTC lejos de su máximo de 90d, BTC cae fuerte en 3d, mercado cae fuerte ese día,
  moneda lejos de su máximo de 30d, volatilidad relativa alta.

## 2) Machine learning (entrena 2017-21, prueba 2022-26, defaults sin ajustar)
AUC OOS: solo z y k 0.570 -> todas las variables 0.664 (boosting) / 0.647 (logística). Mitad alta vs baja predicha: +2.9% vs -0.7% (neto 1d).
Importancia: BTC retorno 3d, BTC vs máx 90d, cambio de F&G 7d, retorno medio del mercado, BTC>SMA200. Mejora de ordenación real pero modesta y con muy pocos episodios.

## 3) Walk-forward (mejor filtro elegido cada año con datos anteriores)
Elige un filtro distinto cada año (inestable). Neto por operación sube (+3.6% -> +4.3%) pero la cartera empeora: CAGR 10.8% -> 3.9%, Sharpe 0.70 -> 0.34 (1% invertido). NO ayuda.

## 4) Lo que sí sobrevive: BTC en drawdown >= 25% desde su máximo de 90 días (umbral derivado del tercil IS)
OOS 2022-26: con drawdown: 162 eventos en 8 episodios, neto +7.8%, P(sube) 84%, peor caso -13%; sin él: 235 eventos en 30 episodios, neto +0.7%, P 67%, peor caso -59%.
Cartera OOS: CAGR +10.6% Sharpe 0.92 DD -2% frente a sin filtro +11.0% / 0.68 / -26%. Gradiente monótono IS y OOS (-15%: +3.9%, -20%: +4.8%, -25%: +7.8%, -30%: +10.8% neto OOS).
=> mismo retorno con mucho menos riesgo de cola. Límite: 8 episodios OOS.

**Integración**: etiqueta FUERTE/DÉBIL en `daily_report` (BTC <= -25% vs máx 90d). Conservador solo opera señales FUERTES; balanceado reduce a la mitad las DÉBILES; agresivo no cambia.
**Decisión**: pendiente (del usuario).

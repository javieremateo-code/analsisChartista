# Regla de rebote con velas de 4 h (más eventos por moneda)

**Estado**: estudiado (`scripts/study_crypto_4h.py`). Candidata prometedora pero SOLO para ejecución automática; no integrada en el informe manual.

- z>=3 con velas de 4 h pierde (neto por operación negativo: la caída moderada de 4 h no rebota lo bastante para cubrir costos).
- z>=5 (caída extrema), comprar al cierre de la vela y mantener 1 vela (4 h): 808 operaciones en 129 fechas, neto +1.21% por operación, gana 63%,
  CAGR +5.4%, Sharpe 0.71 (IS 0.72 / OOS 0.71), DD -8.2%. Positiva en 2019-2021 y 2023-2025 (2018 -3%, 2022 -2%, 2026 -1%).
- Correlación diaria con la regla diaria (balanceado): 0.01. Juntas: CAGR +14.4%, Sharpe 1.36, DD -11.4% (OOS +13.5%, Sharpe 1.24).
- Frágil: costo 0.30%/lado -> CAGR +3.2% (Sharpe 0.45); 0.50%/lado -> ~0. Sin las 5 mejores velas +1.0%; sin las 20 mejores -2.9%.
- Sensible al retraso (velas de 15 min): entrada +0 min +1.21%, +15 min +0.68%, +30 min +0.76%, +60 min +0.76% (gana 63% -> 53-58%), +2 h +0.54%.
  Requiere ejecutar en los primeros minutos de cada cierre de 4 h (00, 04, 08, 12, 16, 20 UTC): inviable a mano; solo con bot conectado a la API.

**Decisión**: pendiente (del usuario). Siguiente paso natural: bot automático en Binance Testnet que ejecute la regla diaria y la de 4 h, con medición real de slippage y retraso.

# Campaña de mejora del rendimiento

**Estado**: completada. Adoptado: modelo de probabilidad en la regla diaria. Descartado: el resto.

Criterio de adopción (fijado antes): mejora CAGR y Sharpe en 2022-26, DD <= 1.5x la base, y CAGR sin los 5 mejores días no inferior.
- ML walk-forward trimestral (AUC 0.58; mitad alta +5.04% vs baja +2.33% neto): filtro P>=0.60 CAGR +7.4%; tamaño ∝ P +8.5%; ambos +8.9% (Sharpe 0.94, 2022+ +13.0%). ADOPTADO.
  Perfil agresivo con modelo: +14.6% / Sharpe 1.02 / DD -14.2% (sin modelo +8.6% / 0.62 / -23.7%).
- Tamaño por magnitud (z>=4 x1.3, z>=5 x1.6): CAGR +9.1% pero Sharpe igual (0.83) y DD -9.1%: solo escala riesgo. No adoptado.
- Take-profit (4h de rebote hasta 24 h): +4% CAGR +2.5%, +8% +5.4%, +12% +6.8% (base +6.7%): recorta ganadores. No adoptado.
- Entrada con límite -1%: CAGR +6.8% Sharpe 0.88 (mejora mínima, complejidad operativa); -2% y -3% peor. No adoptado.
- Costos 0.15% -> 0.10%/lado: +0.3 puntos (pocas operaciones al año). Sin efecto material.
- Regla de 4 h con modelo (AUC 0.55): CAGR +5.7% -> +5.2%, reduce operaciones sin mejorar. No adoptado.
- Capa lenta (BTC/ETH en drawdown >= 25-45%, mantener 14-60 días): resultados fuera de muestra con signos mixtos (2-13 episodios), caídas internas de -50%. Descartada.
Sistema completo (balanceado): diaria+modelo +8.9%; +4h ideal +16.0%; +4h con retraso +12.8%; + capital parado 3% +16.3% (Sharpe 1.45, DD -7.3%).
**Decisión**: pendiente (del usuario). Siguiente paso: paper trading del sistema completo.

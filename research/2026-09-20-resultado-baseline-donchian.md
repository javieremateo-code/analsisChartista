# Resultado del primer walk-forward: baseline Donchian breakout

**Estado**: hallazgo, no cambio de código todavía — pendiente de decisión.

## Resultado observado (datos reales BTC/USDT, 21 ventanas walk-forward, ~1 año OOS)

```
n_trades: 98
win_rate: 32.65%
profit_factor: 0.535
max_drawdown: -50.73%
total_return: -47.54%
[HALT] Drawdown máximo alcanzado
```

## Lectura honesta

- **El sistema funcionó como debía**: el kill switch de drawdown cortó exactamente
  donde estaba configurado. Esto es la validación haciendo su trabajo, no un bug.
- **La estrategia base no tiene edge en este mercado/timeframe**: profit_factor
  0.535 significa que por cada € ganado se perdieron ~1.87€ en operaciones
  perdedoras. Con un win rate del 32.65%, el sistema necesitaría un ratio
  ganancia/pérdida promedio de al menos ~2:1 solo para empatar — y claramente
  no lo está logrando.
- **No es solo culpa de los costos**: la pérdida es demasiado grande (-47.5%)
  para atribuirla únicamente a comisión+slippage sobre 98 operaciones. El
  problema es la señal, no la fricción.

## Hipótesis de por qué falla (para la próxima iteración, sin tocar código todavía)

1. BTC en 15m puede comportarse más como **mean-reversion** dentro del rango
   intradía que como trend-following sostenido — los breakouts de Donchian
   fallarían más seguido de lo que la teoría (pensada para futuros/FX con
   tendencias más largas) asume.
2. El filtro de tendencia (EMA200 en 15m) podría estar demasiado lento para
   este timeframe, dejando pasar breakouts que ya perdieron momentum.
3. El ratio riesgo:beneficio fijo (1.5 ATR stop / 3 ATR target) puede no
   encajar con la distribución real de movimientos post-breakout de BTC.

## Lo que NO se va a hacer

Ajustar a mano estos parámetros (canal, EMA, multiplicadores de ATR) sobre
este mismo resultado hasta que "funcione" — es exactamente el overfitting que
el proyecto se propuso evitar. Cualquier cambio de parámetros debe
re-validarse con walk-forward completo, no compararse contra este único run.

## Próximo paso propuesto (pendiente de aprobación)

Probar una familia de estrategia distinta — mean-reversion intradía (ej. RSI2
o bandas de Bollinger con reversión a la media) — como hipótesis alternativa,
en vez de seguir iterando sobre breakout. Se reporta como próxima propuesta
en un archivo separado una vez armado.

**Decisión**: pendiente (del usuario).

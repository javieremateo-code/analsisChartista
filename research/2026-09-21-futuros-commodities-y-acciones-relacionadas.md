# Futuros de commodities: ¿mejoran la situación? ¿anticipan a las acciones relacionadas?

**Estado**: estudiado (`scripts/study_futures.py`, `scripts/study_commodity_stocks.py`). Sin edge explotable en ninguna de las dos preguntas.

## Datos y límites
- 25 futuros continuos de Yahoo (2000-2026). Los contratos continuos saltan al renovar contrato (roll): para reglas de 1 día es un ruido menor, pero
  las cifras de "comprar y mantener" y de seguimiento de tendencia (que mantienen posiciones a través de rolls) NO son fiables (el retorno por roll/carry no está).
  Correlación con ETFs equivalentes: 0.85-0.91 en oro, plata, platino, trigo; 0.62 cobre. Contratos poco líquidos (avena, arroz, zumo, ganado, cerdo) más ruidosos.
- Acciones: 59/67 tickers (faltan CHK, MRO, PXD, SWN, HES, TIF, CTRA, HBI por exclusión de cotización: sesgo de supervivencia). Corte IS/OOS: 2013.

## 1) ¿Mejoran los futuros la situación de commodities?
- Con 26 años se ve una reversión leve: tras caída >=4σ (2+ días) sube el 58.7% (n=254; OOS 59%, n=147); tras subida >=4σ baja el 52% (OOS 51%).
- Carteras 1 día (sin apalancamiento, peso máx 10%, costo 0.03%/lado): largo tras caída z>=4 CAGR +0.5% Sharpe 0.34 (OOS 0.38); z>=5 OOS Sharpe 0.51 con ~100 casos totales;
  corto tras subida z>=3-5 CAGR +0.4-0.9%, Sharpe 0.27-0.34 pero OOS 0.12-0.16 (decae). Continuación (momentum de 1 día) pierde en ambos sentidos.
- Seguimiento de tendencia 12-1 meses (largo/corto, vol-objetivo): Sharpe 0.20-0.25 (OOS 0.33-0.37); con costos 0.08%/lado ~0.
- El apalancamiento no cambia el Sharpe (solo amplifica el drawdown). Veredicto: la clase sigue SIN edge validado (OOS Sharpe base < 0.5).

## 2) ¿Predice el futuro a las acciones relacionadas en los días siguientes?
Relación contemporánea (R² de retorno anómalo de la cesta vs futuro): oro→mineras 41%, plata→mineras 33%, petróleo→E&P 26%, cobre→mineras 23%,
petróleo→servicios 17%, gas→productoras 11%; petróleo→aerolíneas 4%, granos→agro 2-3%, **oro→joyerías 0%**, cacao/café/algodón→consumidoras 0%.
Predicción (42 pruebas: |t|>=2: 10 vs ~2 por azar; |t|>=3: 4):
- Metales y petróleo → mineras/petroleras: efecto NEGATIVO al día siguiente (reversión, p.ej. oro t=-2.3, plata t=-2.5, petróleo→E&P t=-2.1), de ~-0.1% por +1% del futuro. No hay "catch-up".
- Trigo/maíz → agroindustria: positivo (t=+3.1/+4.3) pero dentro de muestra (IS t=+3.5/+4.5, OOS +0.7/+1.2): se diluye; tamaño ~+0.04% por +1% del futuro.
- Tamaño típico tras un día extremo del futuro (|z|>=2): +0.1-0.3% anómalo, del orden del costo de una operación largo/corto (~0.2%). No operable.
**Decisión**: pendiente (del usuario). No se integra al informe diario.

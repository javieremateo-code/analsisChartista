"""Alternativa defensiva: carry de funding delta-neutral (comprar spot + vender el perpetuo por el mismo importe) en BTC y ETH.

Modelo (optimista, no incluye base/liquidación/riesgo de exchange): el capital se reparte mitad spot y mitad margen del perpetuo (1x),
así que el retorno sobre el capital es funding_diario x 0.5. Costos: entrada+salida 0.3% del nocional una vez y rebalanceo mensual 0.05%.
Variante con interruptor: solo mantener la posición cuando el funding medio de 7 días supera 0.01% diario.

Uso: python -m scripts.backtest_funding_carry
"""
import numpy as np
import pandas as pd

from screener.backtest import perf
from screener.extra_data import load_funding


def run(fund, threshold=None, cost_round=0.003, cost_monthly=0.0005):
    f = fund.dropna()
    on = pd.Series(True, index=f.index)
    if threshold is not None:
        on = (f.rolling(7).mean().shift(1) > threshold)
    ret = f * 0.5 * on.astype(float)
    switches = on.astype(int).diff().abs().fillna(0)
    ret = ret - 0.5 * (cost_round * switches / 2 + cost_monthly / 30 * on.astype(float))
    ret.iloc[0] -= 0.5 * cost_round / 2
    return ret


def main():
    fund = load_funding()
    for coin in ("BTC", "ETH"):
        f = fund[coin]
        print(f"\n=== {coin} | funding desde {f.dropna().index[0].date()} | media diaria sobre nocional {f.mean():.4%}")
        for lab, th in (("siempre en posición", None), ("solo si funding 7d > 0.01%/día", 0.0001)):
            r = run(f, th)
            p = perf(r, 365)
            yr = r.groupby(r.index.year).apply(lambda x: (1 + x).prod() - 1)
            print(f"  {lab:<34} CAGR {p['cagr']:+.1%} Sharpe {p['sharpe']:5.2f} DD {p['dd']:6.1%} | por año: " + " ".join(f"{y}:{v:+.1%}" for y, v in yr.items()))
    print("\nNota: sin riesgo de base, liquidación de la pata corta, exchange ni funding negativo prolongado fuera de lo observado en los datos.")


if __name__ == "__main__":
    main()

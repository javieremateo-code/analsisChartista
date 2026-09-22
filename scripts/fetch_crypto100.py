"""Descarga (reanudable) los datos de las 100 principales criptos en 1d, 4h y 1h.  Uso: python -m scripts.fetch_crypto100"""
import time

from screener import crypto100

if __name__ == "__main__":
    t0 = time.time()
    uni = crypto100.get_universe(refresh=True)
    print(f"Universo ({uni['source']}): {len(uni['coins'])} monedas: {' '.join(uni['coins'])}", flush=True)
    for itv in ("1d", "4h", "1h"):
        c, q = crypto100.load(itv)
        print(f"{itv}: {c.shape[1]} monedas | {len(c):,} velas | {c.index[0]} -> {c.index[-1]} | {time.time() - t0:.0f}s", flush=True)

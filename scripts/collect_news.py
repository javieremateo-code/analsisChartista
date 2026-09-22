"""Descarga (reanudable) de la serie GDELT de 'cuota de artículos de aviso de corrección' por mercado.

Uso:  python -m scripts.collect_news            # todos los temas
      python -m scripts.collect_news crypto     # solo uno
"""
import sys

from screener.news import CACHE, TOPICS, warning_share

if __name__ == "__main__":
    topics = sys.argv[1:] or list(TOPICS)
    for t in topics:
        print(f"== {t}")
        df = warning_share(t)
        f = CACHE / f"news_{t}.pkl"
        df.to_pickle(f)
        print(f"   {t}: {len(df)} días ({df.index.min().date() if len(df) else '-'} -> {df.index.max().date() if len(df) else '-'}) guardado en {f.name}")

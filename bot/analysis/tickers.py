"""Mapas de conocimiento: empresa->ticker y categoría macro->tickers afectados.

Son listas de partida, pensadas para ser editadas/ampliadas por el usuario según
su universo de inversión. No pretenden ser exhaustivas.
"""
from __future__ import annotations

# Nombre de empresa (en minúsculas) -> ticker en bolsa.
COMPANY_TICKERS: dict[str, str] = {
    "apple": "AAPL",
    "microsoft": "MSFT",
    "amazon": "AMZN",
    "google": "GOOGL",
    "alphabet": "GOOGL",
    "meta": "META",
    "facebook": "META",
    "tesla": "TSLA",
    "nvidia": "NVDA",
    "netflix": "NFLX",
    "intel": "INTC",
    "amd": "AMD",
    "boeing": "BA",
    "exxon": "XOM",
    "exxonmobil": "XOM",
    "chevron": "CVX",
    "jpmorgan": "JPM",
    "goldman sachs": "GS",
    "bank of america": "BAC",
    "coca-cola": "KO",
    "pfizer": "PFE",
    "moderna": "MRNA",
    "walmart": "WMT",
    "disney": "DIS",
    "lockheed martin": "LMT",
    "raytheon": "RTX",
    "northrop grumman": "NOC",
    "general dynamics": "GD",
}

# Categoría macro -> lista de (ticker, dirección) que la noticia probablemente mueve.
# La dirección es la reacción típica de ese ticker ante la categoría (no garantizada).
MACRO_TICKERS: dict[str, list[tuple[str, str]]] = {
    "war": [("LMT", "buy"), ("RTX", "buy"), ("NOC", "buy"), ("USO", "buy"), ("SPY", "sell")],
    "sanctions": [("USO", "buy"), ("SPY", "sell")],
    "oil_supply_shock": [("USO", "buy"), ("XOM", "buy"), ("CVX", "buy")],
    "rate_hike": [("TLT", "sell"), ("SPY", "sell")],
    "rate_cut": [("TLT", "buy"), ("SPY", "buy")],
    "inflation_hot": [("TLT", "sell"), ("SPY", "sell")],
    "inflation_cool": [("TLT", "buy"), ("SPY", "buy")],
    "recession_fear": [("SPY", "sell"), ("TLT", "buy")],
    "bank_crisis": [("SPY", "sell"), ("KRE", "sell")],
}

# Palabras clave (regex-friendly, en inglés porque la mayoría de feeds financieros lo son)
# que activan cada categoría macro. Se buscan como subcadenas insensibles a mayúsculas.
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "war": ["war", "invasion", "invades", "military strike", "missile attack", "conflict escalates"],
    "sanctions": ["sanctions", "embargo", "trade ban"],
    "oil_supply_shock": ["oil pipeline", "opec cuts", "refinery attack", "strait of hormuz"],
    "rate_hike": ["rate hike", "raises interest rates", "fed hikes"],
    "rate_cut": ["rate cut", "cuts interest rates", "fed cuts"],
    "inflation_hot": ["inflation surges", "cpi higher than expected", "inflation accelerates"],
    "inflation_cool": ["inflation cools", "cpi lower than expected", "inflation slows"],
    "recession_fear": ["recession fears", "gdp contracts", "economy shrinks"],
    "bank_crisis": ["bank collapse", "bank run", "bank failure"],
}

# Palabras que indican eventos específicos de una empresa (se combinan con COMPANY_TICKERS).
COMPANY_EVENT_KEYWORDS: dict[str, str] = {
    "beats estimates": "buy",
    "beats earnings": "buy",
    "raises guidance": "buy",
    "announces buyback": "buy",
    "wins contract": "buy",
    "misses estimates": "sell",
    "misses earnings": "sell",
    "cuts guidance": "sell",
    "profit warning": "sell",
    "files for bankruptcy": "sell",
    "recalls": "sell",
    "under investigation": "sell",
    "data breach": "sell",
}

"""Persistencia simple en SQLite: noticias ya procesadas y registro de operaciones.

Sirve de log de auditoría (imprescindible operando con dinero real) y de estado
para deduplicar noticias y aplicar cooldowns entre reinicios del bot.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from bot.models import Signal


class Storage:
    def __init__(self, db_path: str):
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS news_seen (
                    id TEXT PRIMARY KEY,
                    url TEXT,
                    title TEXT,
                    first_seen_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    notional_usd REAL NOT NULL,
                    confidence REAL NOT NULL,
                    category TEXT,
                    reason TEXT,
                    news_url TEXT,
                    order_id TEXT,
                    status TEXT NOT NULL,
                    realized_pnl_usd REAL
                )
                """
            )

    def is_news_seen(self, news_id: str) -> bool:
        cur = self._conn.execute("SELECT 1 FROM news_seen WHERE id = ?", (news_id,))
        return cur.fetchone() is not None

    def mark_news_seen(self, news_id: str, url: str, title: str) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO news_seen (id, url, title, first_seen_at) VALUES (?, ?, ?, ?)",
                (news_id, url, title, datetime.now(timezone.utc).isoformat()),
            )

    def last_trade_time(self, ticker: str) -> datetime | None:
        cur = self._conn.execute(
            "SELECT ts FROM trades WHERE ticker = ? ORDER BY ts DESC LIMIT 1",
            (ticker,),
        )
        row = cur.fetchone()
        return datetime.fromisoformat(row[0]) if row else None

    def trades_today_count(self) -> int:
        today = datetime.now(timezone.utc).date().isoformat()
        cur = self._conn.execute(
            "SELECT COUNT(*) FROM trades WHERE ts LIKE ?", (f"{today}%",)
        )
        return cur.fetchone()[0]

    def realized_pnl_today(self) -> float:
        today = datetime.now(timezone.utc).date().isoformat()
        cur = self._conn.execute(
            "SELECT COALESCE(SUM(realized_pnl_usd), 0) FROM trades WHERE ts LIKE ? AND realized_pnl_usd IS NOT NULL",
            (f"{today}%",),
        )
        return cur.fetchone()[0]

    def open_positions_count(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) FROM trades WHERE status = 'open'")
        return cur.fetchone()[0]

    def record_trade(self, signal: Signal, notional_usd: float, order_id: str, status: str) -> int:
        with self._conn:
            cur = self._conn.execute(
                """
                INSERT INTO trades
                    (ts, ticker, direction, notional_usd, confidence, category, reason, news_url, order_id, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    signal.ticker,
                    signal.direction,
                    notional_usd,
                    signal.confidence,
                    signal.category,
                    signal.reason,
                    signal.news.url,
                    order_id,
                    status,
                ),
            )
            return cur.lastrowid

    def close(self) -> None:
        self._conn.close()

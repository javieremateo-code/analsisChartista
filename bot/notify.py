"""Notificaciones: siempre por consola/log, opcionalmente también por Telegram."""
from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)


class Notifier:
    def __init__(self, telegram_bot_token: str = "", telegram_chat_id: str = ""):
        self._token = telegram_bot_token
        self._chat_id = telegram_chat_id

    def notify(self, message: str) -> None:
        logger.info(message)
        if self._token and self._chat_id:
            self._send_telegram(message)

    def _send_telegram(self, message: str) -> None:
        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        try:
            requests.post(url, json={"chat_id": self._chat_id, "text": message}, timeout=10)
        except requests.RequestException as exc:
            logger.warning("No se pudo notificar por Telegram: %s", exc)

"""Estado persistente del bot (JSON, escritura atómica). Sobrevive a reinicios; es idempotente por vela procesada."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "state"


class BotState:
    def __init__(self, path=None, capital=1000.0):
        self.path = Path(path) if path else STATE_DIR / "bot_state.json"
        if self.path.exists():
            self.d = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            self.d = dict(capital0=capital, equity=capital, peak=capital, killed=False, day=None, equity_day_start=capital,
                          positions=[], closed=[], trend={}, last_bar=None, liquidity={}, cycles=0, notes=[])

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.d, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)  # atómico: nunca queda un JSON a medias

    def __getitem__(self, k):
        return self.d[k]

    def __setitem__(self, k, v):
        self.d[k] = v

    def open_coins(self):
        return {p["coin"] for p in self.d["positions"]}

    def trend_cost(self):
        return sum(p["cost"] for p in self.d.get("trend", {}).values())

    def exposure(self):
        eq = self.d["equity"]
        return (sum(p["usdt"] for p in self.d["positions"]) + self.trend_cost()) / eq if eq > 0 else 0.0

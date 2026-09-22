"""Motor del bot: un ciclo por cada cierre de vela de 4 h (00, 04, 08, 12, 16, 20 UTC).

Cada ciclo: (1) cierra lo que toca (por tiempo o por stop de catástrofe), (2) actualiza el freno diario y el kill switch,
(3) busca señales (regla diaria a las 00:00 UTC; regla de 4 h en cada cierre) y abre posiciones si el retraso respecto al cierre
es aceptable (los backtests suponen entrar en los primeros minutos). Es idempotente: una vela ya procesada no se repite.
"""
import logging
from dataclasses import dataclass, field

import pandas as pd

from screener.risk import PROFILES
from screener.universe import COST

from screener.trend import trend_targets

from .strategy import daily_signals, four_hour_signals

MIN_USDT = 10.0  # mínimo por orden


class DataNotReady(Exception):
    """La vela cerrada más reciente aún no está disponible en la API: reintentar en unos segundos."""


@dataclass
class BotConfig:
    profile: str = "balanceado"
    capital: float = 1000.0
    rules: tuple = ("daily", "4h", "trend")
    max_delay_min: dict = field(default_factory=lambda: {"4h": 5.0, "daily": 30.0, "trend": 360.0})
    catastrophe_stop: float = 0.30
    kill_dd: float = 0.50
    risk_override: float = None
    cost: float = COST["crypto"]
    ml_min: float = 0.60       # probabilidad mínima de rebote del modelo (subirla = menos operaciones y más acierto)
    leverage: float = 1.0      # SOLO simulación: multiplica el tamaño (máx. 2.0, como el límite ESMA de CFD de cripto para minoristas)
    borrow_rate: float = 0.06  # coste anual de financiación de la parte prestada


class Bot:
    def __init__(self, cfg, feed, exchange, state, stats_daily, stats_4h, log=None, model=None, fg_provider=None):
        self.cfg, self.feed, self.ex, self.st = cfg, feed, exchange, state
        self.stats_d, self.stats_4h = stats_daily, stats_4h
        self.prof = PROFILES[cfg.profile]
        self.lev = min(max(float(cfg.leverage), 1.0), 2.0)
        self.model, self.fg_provider = model, fg_provider
        self.st.d.setdefault("trend", {})
        self.log = log or logging.getLogger("bot")

    # ------------------------------------------------------------------ ciclo
    def cycle(self, now):
        now = pd.Timestamp(now)
        bar = now.floor("4h")
        if self.st["last_bar"] == bar.isoformat():
            return dict(skipped="vela ya procesada")
        c4, _ = self.feed.closes("4h", n=220, now=now)
        if c4.empty or c4.index[-1] != bar - pd.Timedelta(hours=4):
            raise DataNotReady(f"vela 4h de {bar - pd.Timedelta(hours=4)} aún no disponible")
        delay_min = (now - bar).total_seconds() / 60
        self._new_day(now)
        if not self.st["liquidity"]:
            _, qv = self.feed.closes("1d", n=220, now=now)
            self.st["liquidity"] = qv.rolling(30, min_periods=15).mean().iloc[-1].to_dict()
        exits = self._process_exits(now, c4)
        halted, killed = self._risk()
        entries, c1d, qv1d, trades = [], None, None, []
        if bar.hour == 0 and ("daily" in self.cfg.rules or "trend" in self.cfg.rules):
            c1d, qv1d = self.feed.closes("1d", n=400, now=now)
            if c1d.empty or c1d.index[-1] != bar - pd.Timedelta(days=1):
                raise DataNotReady("vela diaria aún no disponible")
            self.st["liquidity"] = qv1d.rolling(30, min_periods=15).mean().iloc[-1].to_dict()
        if "trend" in self.cfg.rules and c1d is not None and delay_min <= self.cfg.max_delay_min["trend"]:
            trades = self._trend(now, c1d, killed)
        if killed:
            self.log.critical("KILL SWITCH: el capital cayó más del %.0f%% desde su máximo. Sin entradas nuevas.", self.cfg.kill_dd * 100)
        elif halted:
            self.log.warning("FRENO DIARIO activo: sin entradas nuevas hasta el próximo día UTC.")
        else:
            sigs = self._signals(now, bar, c4, delay_min, c1d, qv1d)
            entries = self._enter(sigs, now, bar)
        self.st["last_bar"] = bar.isoformat()
        self.st["cycles"] += 1
        self.st.save()
        self.log.info("Ciclo %s (retraso %.1f min): %d cierres, %d aperturas | equity %.2f | posiciones abiertas %d",
                      bar, delay_min, len(exits), len(entries), self.st["equity"], len(self.st["positions"]))
        return dict(bar=str(bar), exits=exits, entries=entries, trend=trades, halted=halted, killed=killed)

    # ------------------------------------------------------------------ piezas
    def _new_day(self, now):
        day = now.date().isoformat()
        if self.st["day"] != day:
            self.st["day"] = day
            self.st["equity_day_start"] = self.st["equity"]

    def _risk(self):
        eq, peak = self.st["equity"], self.st["peak"]
        if eq <= peak * (1 - self.cfg.kill_dd):
            self.st["killed"] = True
        day_pnl = eq / self.st["equity_day_start"] - 1 if self.st["equity_day_start"] else 0.0
        return day_pnl <= -self.prof.daily_loss_limit, bool(self.st["killed"])

    def _process_exits(self, now, c4):
        out = []
        for pos in list(self.st["positions"]):
            ref = float(c4[pos["coin"]].iloc[-1]) if pos["coin"] in c4 and pd.notna(c4[pos["coin"]].iloc[-1]) else pos["entry_px"]
            ml = self.feed.min_low(pos["coin"], pos["entry_bar"])
            if ml is not None and ml <= pos["stop_px"]:
                fill, reason = self.ex.sell_at(pos["coin"], pos["qty"], pos["stop_px"], ref), "stop"
            elif now >= pd.Timestamp(pos["exit_after"]):
                fill, reason = self.ex.sell(pos["coin"], pos["qty"], ref), "time"
            else:
                continue
            lev = pos.get("lev", 1.0)
            held_days = max((now - pd.Timestamp(pos["entry_bar"])).total_seconds() / 86400, 0.0)
            financing = pos["usdt"] * (1 - 1 / lev) * self.cfg.borrow_rate * held_days / 365 if lev > 1 else 0.0
            pnl = fill.usdt - pos["usdt"] - financing
            self.st["equity"] += pnl
            self.st["peak"] = max(self.st["peak"], self.st["equity"])
            self.st["positions"] = [p for p in self.st["positions"] if p["id"] != pos["id"]]
            rec = {**pos, "exit_ts": now.isoformat(), "exit_px": fill.price, "exit_usdt": fill.usdt, "pnl": pnl, "ret": pnl / pos["usdt"],
                   "reason": reason, "exit_mode": fill.mode, "slip_exit_bps": (ref / fill.price - 1) * 1e4}
            self.st["closed"].append(rec)
            out.append(rec)
            self.log.info("CIERRE %s %s [%s]: %+.2f%% (%+.2f USDT)", pos["rule"], pos["coin"], reason, rec["ret"] * 100, pnl)
        return out

    def _trend(self, now, c1d, killed):
        """Capa de tendencia BTC/ETH: rebalancea al peso objetivo (fracción del perfil x señal de 0..1); en kill switch se sale de todo."""
        fraction = 0.0 if killed else self.prof.trend_fraction
        targets = trend_targets(c1d, fraction)
        equity = self.st["equity"]
        out = []
        if self.lev > 1 and self.st["trend"]:
            fin = self.st.trend_cost() * (1 - 1 / self.lev) * self.cfg.borrow_rate / 365
            self.st["equity"] -= fin
            equity = self.st["equity"]
        for coin, t in targets.items():
            pos = self.st["trend"].get(coin, dict(qty=0.0, cost=0.0))
            px = float(c1d[coin].iloc[-1])
            delta = t["target_w"] * self.lev * equity - pos["qty"] * px
            step = max(MIN_USDT, (fraction * self.lev / max(len(targets), 1)) * equity / 6)  # medio escalón de señal (1/3): evita operar por derivas pequeñas
            if delta > step and not killed:
                fill = self.ex.buy(coin, delta, px)
                pos = dict(qty=pos["qty"] + fill.qty, cost=pos["cost"] + fill.usdt)
                out.append(dict(coin=coin, side="buy", usdt=fill.usdt, px=fill.price, sig=t["sig"]))
                self.log.info("TENDENCIA %s: compra %.2f USDT a %.6g (señal %.2f, objetivo %.1f%% del capital)", coin, fill.usdt, fill.price, t["sig"], t["target_w"] * 100)
            elif (delta < -step or (t["target_w"] == 0 and pos["qty"] > 0)) and pos["qty"] > 0:
                qty = pos["qty"] if t["target_w"] == 0 else min(pos["qty"], -delta / px)
                fill = self.ex.sell(coin, qty, px)
                part = pos["cost"] * qty / pos["qty"]
                pnl = fill.usdt - part
                self.st["equity"] += pnl
                self.st["peak"] = max(self.st["peak"], self.st["equity"])
                pos = dict(qty=pos["qty"] - qty, cost=pos["cost"] - part)
                self.st["closed"].append(dict(id=f"trend:{coin}:{now.isoformat()}", rule="trend", coin=coin, usdt=part, pnl=pnl, ret=pnl / part if part else 0.0,
                                              reason="rebalance", exit_ts=now.isoformat(), entry_px=part / qty if qty else 0.0, exit_px=fill.price, mode=fill.mode,
                                              slip_entry_bps=0.0, slip_exit_bps=(px / fill.price - 1) * 1e4))
                out.append(dict(coin=coin, side="sell", usdt=fill.usdt, px=fill.price, sig=t["sig"]))
                self.log.info("TENDENCIA %s: venta %.2f USDT a %.6g (señal %.2f, resultado %+.2f USDT)", coin, fill.usdt, fill.price, t["sig"], pnl)
            if pos["qty"] > 1e-12:
                self.st["trend"][coin] = pos
            else:
                self.st["trend"].pop(coin, None)
        return out

    def _signals(self, now, bar, c4, delay_min, c1d=None, qv=None):
        sigs = []
        cost = self.cfg.cost
        if "daily" in self.cfg.rules and bar.hour == 0 and c1d is not None:
            if delay_min <= self.cfg.max_delay_min["daily"]:
                fg = self.fg_provider() if (self.model is not None and self.fg_provider) else None
                sigs += daily_signals(c1d, qv, self.st["liquidity"], self.stats_d, self.prof, cost, self.cfg.risk_override, self.model, fg, self.cfg.ml_min)
            else:
                self.log.warning("Regla diaria: retraso de %.0f min > %.0f: señales caducadas, no se entra.", delay_min, self.cfg.max_delay_min["daily"])
        if "4h" in self.cfg.rules:
            if delay_min <= self.cfg.max_delay_min["4h"]:
                sigs += four_hour_signals(c4, self.st["liquidity"], self.stats_4h, self.prof, cost, self.cfg.risk_override)
            else:
                self.log.warning("Regla 4h: retraso de %.1f min > %.0f: señales caducadas, no se entra.", delay_min, self.cfg.max_delay_min["4h"])
        return sigs

    def _enter(self, sigs, now, bar):
        out = []
        equity = self.st["equity"]
        held = self.st.open_coins()
        expo = self.st.exposure()
        max_total = self.prof.max_positions * 2
        for s in sigs:
            if s.coin in held:
                continue
            cap = self.prof.max_exposure * self.lev
            if len(self.st["positions"]) >= max_total or expo >= cap:
                break
            w = min(s.w * self.lev, cap - expo)
            usdt = w * equity
            if usdt < MIN_USDT:
                continue
            try:
                fill = self.ex.buy(s.coin, usdt, s.ref)
            except Exception as e:
                self.log.error("Compra de %s falló: %s", s.coin, e)
                continue
            hold = pd.Timedelta(hours=s.hold_hours)
            stop_pct = s.stop_pct if s.stop_pct is not None else self.cfg.catastrophe_stop  # regla diaria: ajustado a volatilidad; 4h: fijo (sin validar por volatilidad)
            pos = dict(id=f"{s.rule}:{s.coin}:{bar.isoformat()}", rule=s.rule, coin=s.coin, entry_ts=now.isoformat(), entry_bar=bar.isoformat(),
                       entry_px=fill.price, qty=fill.qty, usdt=fill.usdt, stop_px=fill.price * (1 - stop_pct), stop_pct=stop_pct,
                       exit_after=(bar + hold).isoformat(), mode=fill.mode, ref=s.ref, lev=self.lev, slip_entry_bps=(fill.price / s.ref - 1) * 1e4, meta=s.meta)
            self.st["positions"].append(pos)
            held.add(s.coin)
            expo += fill.usdt / equity
            out.append(pos)
            self.log.info("COMPRA %s %s: %.2f USDT a %.6g (slippage %+.1f bps, %s), salida %s", s.rule, s.coin, fill.usdt, fill.price, pos["slip_entry_bps"], fill.mode, pos["exit_after"])
        return out

    # ------------------------------------------------------------------ resumen
    def summary(self):
        cl = self.st["closed"]
        by = {}
        for r in cl:
            by.setdefault(r["rule"], []).append(r)
        rules = {k: dict(n=len(v), ret=sum(x["ret"] for x in v) / len(v), win=sum(1 for x in v if x["ret"] > 0) / len(v),
                         slip_in=sum(x["slip_entry_bps"] for x in v) / len(v), slip_out=sum(x["slip_exit_bps"] for x in v) / len(v))
                 for k, v in by.items()}
        return dict(equity=self.st["equity"], ret=self.st["equity"] / self.st["capital0"] - 1, dd=self.st["equity"] / self.st["peak"] - 1,
                    open=len(self.st["positions"]), closed=len(cl), killed=self.st["killed"], rules=rules, trend=dict(self.st["trend"]))

"""Tests del bot con mercado y exchange falsos (sin red): entradas, salidas, stops, frenos, retrasos e idempotencia."""
import numpy as np
import pandas as pd
import pytest

from bot.engine import Bot, BotConfig, DataNotReady
from bot.exchange import SimExchange
from bot.state import BotState
from screener.risk import PROFILES

B1 = pd.Timestamp("2026-03-10 08:00")  # cierre de 4h que NO es medianoche (no activa la regla diaria)
STATS_4H = dict(n=200, p=0.7, p_low=0.65, mean=0.02, p5=-0.05, z_min=6.0)
BAL_W = PROFILES["balanceado"].max_w  # tope de posición del perfil balanceado (se recalibra de vez en cuando)


class FakeFeed:
    """c4: velas de 4h (índice = hora de apertura). Solo se devuelven las cerradas a `now`."""

    def __init__(self, c4, lows=None, quotes=None, c1d=None, qv1d=None):
        self.c4, self.lows, self._quotes, self.c1d, self.qv1d = c4, lows or {}, quotes or {}, c1d, qv1d

    def closes(self, interval, n=220, now=None):
        now = pd.Timestamp(now)
        if interval == "4h":
            d = self.c4[self.c4.index + pd.Timedelta(hours=4) <= now]
            return d.tail(n), d.tail(n) * 0 + 5e7
        d = self.c1d[self.c1d.index + pd.Timedelta(days=1) <= now]
        return d.tail(n), self.qv1d.reindex(d.index)

    def quotes(self):
        return self._quotes

    def min_low(self, coin, start, end=None):
        return self.lows.get(coin)


def make_c4(crash_coin="AAA", n=300):
    idx = pd.date_range(end=B1, periods=n, freq="4h")  # última vela: abre en B1 (cierra en B1+4h)
    rng = np.random.default_rng(5)
    cols = {}
    for c in ("AAA", "BBB"):
        r = rng.normal(0, 0.005, n)
        if c == crash_coin:
            r[-3], r[-2], r[-1] = -0.04, -0.04, 0.03  # dos caídas de 4h antes de B1 y rebote en la vela de B1
        cols[c] = 100 * np.cumprod(1 + r)
    return pd.DataFrame(cols, index=idx)


def make_bot(tmp_path, feed, rules=("4h",), profile="balanceado", state=None):
    st = state or BotState(path=tmp_path / "s.json", capital=1000.0)
    st["liquidity"] = {"AAA": 5e7, "BBB": 5e7}
    q = feed._quotes or {c: dict(bid=float(feed.c4[c].iloc[-3]), ask=float(feed.c4[c].iloc[-3])) for c in ("AAA", "BBB")}
    feed._quotes = q
    cfg = BotConfig(profile=profile, rules=rules)
    return Bot(cfg, feed, SimExchange(feed), st, None, STATS_4H), st


def test_entry_then_time_exit_updates_equity(tmp_path):
    feed = FakeFeed(make_c4())
    bot, st = make_bot(tmp_path, feed)
    out = bot.cycle(B1 + pd.Timedelta(seconds=30))
    assert [p["coin"] for p in out["entries"]] == ["AAA"] and out["entries"][0]["rule"] == "4h"
    pos = st["positions"][0]
    assert abs(pos["usdt"] - BAL_W * 1000) < 1e-6  # balanceado: peso máx del perfil x 1000
    assert pd.Timestamp(pos["exit_after"]) == B1 + pd.Timedelta(hours=4) and abs(pos["stop_px"] / pos["entry_px"] - 0.70) < 1e-9
    feed._quotes = {c: dict(bid=float(feed.c4[c].iloc[-1]), ask=float(feed.c4[c].iloc[-1])) for c in ("AAA", "BBB")}  # rebote +3%
    out2 = bot.cycle(B1 + pd.Timedelta(hours=4, seconds=20))
    assert len(out2["exits"]) == 1 and out2["exits"][0]["reason"] == "time" and not st["positions"]
    rec = st["closed"][0]
    assert abs(st["equity"] - (1000 + rec["pnl"])) < 1e-9
    assert -0.02 < rec["ret"] < 0.05  # rebote del 3% menos costos y slippage


def test_costs_of_immediate_round_trip_are_about_0_3_percent(tmp_path):
    feed = FakeFeed(make_c4())
    feed._quotes = {"AAA": dict(bid=10.0, ask=10.0)}
    ex = SimExchange(feed)
    f = ex.buy("AAA", 100.0, 10.0)
    g = ex.sell("AAA", f.qty, 10.0)
    assert -0.0035 < (g.usdt - f.usdt) / f.usdt < -0.0025


def test_late_entry_is_skipped_but_exits_still_run(tmp_path):
    feed = FakeFeed(make_c4())
    bot, st = make_bot(tmp_path, feed)
    out = bot.cycle(B1 + pd.Timedelta(minutes=10))  # > 5 min de retraso
    assert out["entries"] == [] and not st["positions"]


def test_idempotent_per_bar_and_one_position_per_coin(tmp_path):
    feed = FakeFeed(make_c4())
    bot, st = make_bot(tmp_path, feed)
    bot.cycle(B1 + pd.Timedelta(seconds=30))
    assert bot.cycle(B1 + pd.Timedelta(seconds=50)).get("skipped")  # misma vela: no repite
    assert len(st["positions"]) == 1


def test_daily_loss_halt_and_kill_switch_block_entries(tmp_path):
    feed = FakeFeed(make_c4())
    bot, st = make_bot(tmp_path, feed)
    st["equity"], st["equity_day_start"], st["day"] = 850.0, 1000.0, B1.date().isoformat()  # -15% en el día (límite 10%)
    out = bot.cycle(B1 + pd.Timedelta(seconds=30))
    assert out["halted"] and out["entries"] == []
    feed2 = FakeFeed(make_c4())
    (tmp_path / "k").mkdir()
    bot2, st2 = make_bot(tmp_path / "k", feed2)
    st2["equity"], st2["peak"] = 400.0, 1000.0  # caída del 60% desde el máximo (kill al 50%)
    out2 = bot2.cycle(B1 + pd.Timedelta(seconds=30))
    assert out2["killed"] and out2["entries"] == [] and st2["killed"]


def test_catastrophe_stop_exits_at_stop_price(tmp_path):
    feed = FakeFeed(make_c4())
    bot, st = make_bot(tmp_path, feed)
    bot.cycle(B1 + pd.Timedelta(seconds=30))
    entry = st["positions"][0]["entry_px"]
    feed.lows["AAA"] = entry * 0.60  # mínimo intradía por debajo del stop del -30%
    out = bot.cycle(B1 + pd.Timedelta(hours=4, seconds=20))
    ex = out["exits"][0]
    assert ex["reason"] == "stop" and abs(ex["exit_px"] - entry * 0.70 * 0.997) < 1e-9 and ex["ret"] < -0.30


def test_data_not_ready_raises(tmp_path):
    feed = FakeFeed(make_c4())
    bot, _ = make_bot(tmp_path, feed)
    with pytest.raises(DataNotReady):
        bot.cycle(B1 + pd.Timedelta(hours=8, seconds=10))  # la vela 4h de B1+4h aún no existe en el feed falso


def test_illiquid_coin_is_never_traded(tmp_path):
    feed = FakeFeed(make_c4())
    bot, st = make_bot(tmp_path, feed)
    st["liquidity"] = {"AAA": 1e6, "BBB": 5e7}  # AAA por debajo de 5 M USDT/día
    assert bot.cycle(B1 + pd.Timedelta(seconds=30))["entries"] == []


def test_state_survives_restart(tmp_path):
    feed = FakeFeed(make_c4())
    bot, st = make_bot(tmp_path, feed)
    bot.cycle(B1 + pd.Timedelta(seconds=30))
    st2 = BotState(path=tmp_path / "s.json")
    assert len(st2["positions"]) == 1 and st2["last_bar"] == B1.isoformat() and st2["cycles"] == 1


B0 = pd.Timestamp("2026-03-11 00:00")  # cierre diario (medianoche UTC): activa la capa de tendencia


def make_trend_feed(btc_up=True):
    idx4 = pd.date_range(end=B0 - pd.Timedelta(hours=4), periods=300, freq="4h")
    idx1 = pd.date_range(end=B0 - pd.Timedelta(days=1), periods=420, freq="D")
    c4 = pd.DataFrame({"BTC": 100.0, "ETH": 50.0}, index=idx4)
    up, down = np.linspace(100, 300, 420), np.linspace(300, 100, 420)
    c1d = pd.DataFrame({"BTC": up if btc_up else down, "ETH": down}, index=idx1)
    qv = c1d * 0 + 5e7
    q = {c: dict(bid=float(c1d[c].iloc[-1]), ask=float(c1d[c].iloc[-1])) for c in ("BTC", "ETH")}
    return FakeFeed(c4, quotes=q, c1d=c1d, qv1d=qv)


def make_trend_bot(tmp_path, feed, profile="balanceado"):
    st = BotState(path=tmp_path / "t.json", capital=1000.0)
    cfg = BotConfig(profile=profile, rules=("trend",))
    return Bot(cfg, feed, SimExchange(feed), st, None, None), st


def test_trend_layer_buys_when_signal_on_and_sells_when_off(tmp_path):
    feed = make_trend_feed(btc_up=True)
    bot, st = make_trend_bot(tmp_path, feed)
    out = bot.cycle(B0 + pd.Timedelta(seconds=30))
    assert [t["coin"] for t in out["trend"]] == ["BTC"] and out["trend"][0]["side"] == "buy"  # ETH en tendencia bajista: sin posición
    assert abs(st["trend"]["BTC"]["cost"] - 100.0) < 0.5  # balanceado: 20% del capital repartido entre 2 monedas x señal 1 = 10% = 100 USDT
    # al día siguiente BTC pierde las 3 medias: se vende todo
    feed2 = make_trend_feed(btc_up=False)
    for f in (feed2,):
        f.c1d.index = f.c1d.index + pd.Timedelta(days=1)
        f.c4.index = f.c4.index + pd.Timedelta(days=1)
    bot.feed, bot.ex = feed2, SimExchange(feed2)
    out2 = bot.cycle(B0 + pd.Timedelta(days=1, seconds=30))
    assert out2["trend"] and out2["trend"][0]["side"] == "sell" and "BTC" not in st["trend"]
    rec = [c for c in st["closed"] if c["rule"] == "trend"]
    assert len(rec) == 1 and rec[0]["reason"] == "rebalance" and abs(st["equity"] - (1000 + rec[0]["pnl"])) < 1e-9


def test_trend_layer_exits_everything_on_kill_switch(tmp_path):
    feed = make_trend_feed(btc_up=True)
    bot, st = make_trend_bot(tmp_path, feed)
    bot.cycle(B0 + pd.Timedelta(seconds=30))
    assert "BTC" in st["trend"]
    st["equity"], st["peak"] = 400.0, 1000.0  # -60%: kill switch
    st["last_bar"] = None
    feed2 = make_trend_feed(btc_up=True)
    for f in (feed2,):
        f.c1d.index = f.c1d.index + pd.Timedelta(days=1)
        f.c4.index = f.c4.index + pd.Timedelta(days=1)
    bot.feed, bot.ex = feed2, SimExchange(feed2)
    out = bot.cycle(B0 + pd.Timedelta(days=1, seconds=30))
    assert out["killed"] and "BTC" not in st["trend"] and any(t["side"] == "sell" for t in out["trend"])


def test_trend_cost_counts_towards_exposure(tmp_path):
    feed = make_trend_feed(btc_up=True)
    bot, st = make_trend_bot(tmp_path, feed)
    bot.cycle(B0 + pd.Timedelta(seconds=30))
    assert 0.09 < st.exposure() < 0.11  # ~10% del capital en la capa de tendencia


def test_simulated_leverage_scales_size_caps_at_2x_and_charges_financing(tmp_path):
    feed = FakeFeed(make_c4())
    st = BotState(path=tmp_path / "lev.json", capital=1000.0)
    st["liquidity"] = {"AAA": 5e7, "BBB": 5e7}
    feed._quotes = {c: dict(bid=float(feed.c4[c].iloc[-3]), ask=float(feed.c4[c].iloc[-3])) for c in ("AAA", "BBB")}
    bot = Bot(BotConfig(rules=("4h",), leverage=5.0), feed, SimExchange(feed), st, None, STATS_4H)  # 5x se recorta a 2x
    assert bot.lev == 2.0
    bot.cycle(B1 + pd.Timedelta(seconds=30))
    pos = st["positions"][0]
    assert abs(pos["usdt"] - BAL_W * 2 * 1000) < 1e-6 and pos["lev"] == 2.0  # peso del perfil x apalancamiento 2
    feed._quotes = {c: dict(bid=float(feed.c4[c].iloc[-1]), ask=float(feed.c4[c].iloc[-1])) for c in ("AAA", "BBB")}
    bot.cycle(B1 + pd.Timedelta(hours=4, seconds=20))
    rec = st["closed"][0]
    financing = rec["exit_usdt"] - rec["usdt"] - rec["pnl"]
    assert 0 < financing < 0.01  # 100 USDT prestados x 6% anual x 4 h ≈ 0.0007 USDT... por debajo de 1 céntimo


def test_min_prob_dial_keeps_only_high_confidence_signals():
    from screener.allocation import allocate
    from screener.risk import PROFILES
    df = pd.DataFrame({"activo": ["A", "B", "C"], "p5": [-0.05] * 3, "ev": [0.03] * 3, "ml": [0.65, 0.85, 0.95], "fuerza": ["FUERTE"] * 3})
    assert set(allocate(df, PROFILES["balanceado"])["activo"]) == {"A", "B", "C"}  # umbral por defecto 0.60
    assert set(allocate(df, PROFILES["balanceado"], ml_min=0.80)["activo"]) == {"B", "C"}
    assert set(allocate(df, PROFILES["balanceado"], ml_min=0.90)["activo"]) == {"C"}

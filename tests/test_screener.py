"""Tests del screener: eventos de racha, veredictos por perfil de riesgo y dimensionado."""
import numpy as np
import pandas as pd

from screener.events import build_events, current_state
from screener.risk import PROFILES, position_weight
from scripts.daily_report import evaluate


def _stats():
    pooled = pd.DataFrame([
        dict(dir="down", zb=3, n=358, p=0.715, p_low=0.667, mean=0.0285, median=0.02, p5=-0.08, worst=-0.30, n_oos=283, p_oos=0.71, base=0.518),
        dict(dir="down", zb=2, n=1682, p=0.617, p_low=0.594, mean=0.0106, median=0.01, p5=-0.09, worst=-0.40, n_oos=1261, p_oos=0.61, base=0.518),
        dict(dir="down", zb=4, n=190, p=0.768, p_low=0.675, mean=0.0648, median=0.05, p5=-0.10, worst=-0.25, n_oos=73, p_oos=0.77, base=0.518),
    ])
    cells = pd.DataFrame([dict(dir="down", kc=2, zb=3, n=120, p=0.70)])
    return dict(pooled=pooled, cells=cells)


def _state(zb, k=2, direction="down"):
    return pd.DataFrame([dict(asset="TEST", date=pd.Timestamp("2026-09-20"), dir=direction, k=k, cum=-0.2, z=zb + 0.5,
                              sigma=0.04, last_close=1.0, kc=min(k, 5), zb=zb)])


def test_buy_signal_when_validated_and_criteria_met():
    df = evaluate("crypto", _state(3), _stats(), PROFILES["balanceado"], True, 0.0015, None)
    assert df.loc[0, "verdict"] == "COMPRAR"
    assert df.loc[0, "ev"] > 0


def test_no_buy_when_class_not_validated():
    df = evaluate("stocks", _state(3), _stats(), PROFILES["balanceado"], False, 0.0005, None)
    assert df.loc[0, "verdict"].startswith("no:") and "SIN edge" in df.loc[0, "verdict"]


def test_risk_dial_changes_decisions():
    st = _state(3)
    # sin capitulación de BTC: el conservador no opera, el balanceado opera con la mitad de tamaño, el agresivo con tamaño completo
    verdicts = {n: evaluate("crypto", st, _stats(), PROFILES[n], True, 0.0015, None, capitulation=False).loc[0, "verdict"] for n in PROFILES}
    assert verdicts["conservador"] != "COMPRAR" and verdicts["balanceado"] == "COMPRAR" and verdicts["agresivo"] == "COMPRAR"
    assert PROFILES["balanceado"].weak_size_factor == 0.5 and PROFILES["agresivo"].weak_size_factor == 1.0
    # magnitud < 3σ: ningún perfil lo acepta (los umbrales calibrados con el replay exigen >=3σ)
    for n in PROFILES:
        assert evaluate("crypto", _state(2), _stats(), PROFILES[n], True, 0.0015, None, capitulation=True).loc[0, "verdict"] != "COMPRAR"


def test_risk_dial_is_monotonic():
    c, b, a = PROFILES["conservador"], PROFILES["balanceado"], PROFILES["agresivo"]
    for field in ("min_z", "min_p_low", "min_n"):  # más riesgo = criterios más laxos
        assert getattr(c, field) >= getattr(b, field) >= getattr(a, field), field
    for field in ("risk_per_trade", "max_w", "max_positions", "max_exposure", "daily_loss_limit", "weak_size_factor", "trend_fraction"):  # y posiciones mayores
        assert getattr(c, field) <= getattr(b, field) <= getattr(a, field), field


def test_no_signal_for_single_day_streak_or_up_streak():
    assert "sin señal" in evaluate("crypto", _state(3, k=1), _stats(), PROFILES["agresivo"], True, 0.0015, None).loc[0, "verdict"]
    up = evaluate("crypto", _state(3, direction="up"), _stats(), PROFILES["agresivo"], True, 0.0015, None).loc[0, "verdict"]
    assert up != "COMPRAR"


def test_position_weight_respects_cap_and_risk():
    p = PROFILES["balanceado"]
    assert position_weight(p, 0.08) == p.risk_per_trade / 0.08 if p.risk_per_trade / 0.08 < p.max_w else p.max_w
    assert position_weight(p, 0.001) == p.max_w  # riesgo pequeño -> tope de peso
    assert position_weight(PROFILES["conservador"], 0.08) <= PROFILES["agresivo"].max_w


def test_context_variables_match_between_history_and_live():
    """La tendencia previa y el % deshecho deben definirse igual en el histórico (backtest) y en vivo (reporte)."""
    from screener.context import build_context
    idx = pd.date_range("2024-01-01", periods=400, freq="D")
    rng = np.random.default_rng(3)
    px = 100 * np.cumprod(1 + rng.normal(0, 0.01, 400))
    px[-8] = px[-9] * 0.99  # día previo a la baja, para que la subida empiece exactamente en px[-7]
    base = px[-8]
    px[-7:] = base * np.array([1.02, 1.04, 1.07, 1.10, 1.08, 1.06, 1.055])  # 4 días de subida y 3 de bajada
    close = pd.DataFrame({"A": px}, index=idx)
    st = current_state(close).iloc[0]
    assert st["dir"] == "down" and st["k"] == 3 and st["prev_dir"] == "up" and st["prev_k"] == 4
    ctx = build_context(close)
    row = ctx[ctx["date"] == idx[-1]].iloc[0]
    assert row["cur_k"] == 3 and row["prev_k"] == 4
    assert abs(row["prev_z"] - st["prev_z"]) < 1e-6 and abs(row["retr"] - st["retr"]) < 1e-9 and abs(row["cur_z"] - st["z"]) < 1e-6


def test_candidate_needs_greed_and_context():
    from screener.candidates import matches
    s = pd.Series(dict(dir="down", prev_dir="up", prev_k=4, prev_z=3.0, z=1.0, k=2, retr=0.3))
    assert matches(s, 80) and not matches(s, 60) and not matches(s, None)
    assert not matches(pd.Series({**s.to_dict(), "retr": 0.9}), 80)  # deshace demasiado: ya no es mini-bajada
    assert not matches(pd.Series({**s.to_dict(), "prev_k": 2}), 80)  # tendencia previa demasiado corta


def test_events_and_current_state_agree_on_streak():
    idx = pd.date_range("2024-01-01", periods=400, freq="D")
    rng = np.random.default_rng(1)
    px = 100 * np.cumprod(1 + rng.normal(0, 0.01, 400))
    px[-3:] = px[-4] * np.array([0.97, 0.94, 0.90])  # 3 días seguidos de caída
    close = pd.DataFrame({"A": px}, index=idx)
    st = current_state(close)
    assert st.loc[0, "dir"] == "down" and st.loc[0, "k"] == 3 and st.loc[0, "z"] > 3
    ev = build_events(close)
    last = ev[(ev["date"] == idx[-1]) & (ev["dir"] == "down")]
    assert len(last) == 1 and last.iloc[0]["k"] == 3
    assert abs(last.iloc[0]["z"] - st.loc[0, "z"]) < 1e-6  # misma definición de z en histórico y en vivo


def test_liquidity_gate_blocks_illiquid_coins():
    st = _state(4)
    ok = evaluate("crypto", st, _stats(), PROFILES["agresivo"], True, 0.0015, None, capitulation=True, liquidity={"TEST": 30e6})
    assert ok.loc[0, "verdict"] == "COMPRAR"
    bad = evaluate("crypto", st, _stats(), PROFILES["agresivo"], True, 0.0015, None, capitulation=True, liquidity={"TEST": 1e6})
    assert bad.loc[0, "verdict"].startswith("no:") and "liquidez" in bad.loc[0, "verdict"]
    unknown = evaluate("crypto", st, _stats(), PROFILES["agresivo"], True, 0.0015, None, capitulation=True, liquidity={})
    assert unknown.loc[0, "verdict"].startswith("no:")  # sin dato de liquidez no se opera


def test_capitulation_quality_filter_by_profile():
    st = _state(4)  # >=4σ y >=150 casos: la señal cumple incluso el perfil conservador
    fuerte = evaluate("crypto", st, _stats(), PROFILES["conservador"], True, 0.0015, None, capitulation=True)
    assert fuerte.loc[0, "verdict"] == "COMPRAR" and fuerte.loc[0, "fuerza"] == "FUERTE"
    debil_c = evaluate("crypto", st, _stats(), PROFILES["conservador"], True, 0.0015, None, capitulation=False)
    assert debil_c.loc[0, "verdict"].startswith("no:") and "capitulación" in debil_c.loc[0, "verdict"]  # conservador la rechaza
    debil_b = evaluate("crypto", st, _stats(), PROFILES["balanceado"], True, 0.0015, None, capitulation=False)
    assert debil_b.loc[0, "verdict"] == "COMPRAR" and debil_b.loc[0, "fuerza"] == "DÉBIL"  # balanceado la acepta con menos tamaño


def _buy_df(ml_values, ws=None):
    n = len(ml_values)
    return pd.DataFrame({"activo": [f"C{i}" for i in range(n)], "p5": [-0.05] * n, "ev": [0.03] * n, "ml": ml_values,
                         "fuerza": ["FUERTE"] * n})


def test_allocation_filters_low_ml_and_sizes_by_probability():
    from screener.allocation import allocate
    prof = PROFILES["balanceado"]
    out = allocate(_buy_df([0.50, 0.70, 0.90]), prof)
    assert list(out["activo"]) == ["C2", "C1"] or set(out["activo"]) == {"C1", "C2"}  # C0 (P=0.50 < 0.60) descartada
    w = dict(zip(out["activo"], out["w"]))
    assert w["C2"] > w["C1"] and w["C2"] <= prof.max_w * 1.4 + 1e-12  # más probabilidad -> más tamaño, con tope
    assert abs(w["C1"] - prof.max_w) < 1e-12  # P=0.70 = referencia: peso base (tope 10%)


def test_train_and_score_average_an_ensemble_of_models():
    from screener.ml_score import FEATS, score, train
    rng = np.random.default_rng(7)
    n = 400
    df = pd.DataFrame({f: rng.normal(0, 1, n) for f in FEATS})
    df["z"] = rng.uniform(2, 6, n)
    df["date"] = pd.date_range("2024-01-01", periods=n, freq="D")
    # 'next' depende de una sola variable con ruido, para que el modelo pueda aprender algo real
    df["next"] = np.where(df["z"] + rng.normal(0, 1, n) > 4, 0.02, -0.02)

    mdl = train(df, n_models=3)
    assert len(mdl["models"]) == 3 and mdl["feats"] == FEATS
    p = score(mdl, df)
    assert p.shape == (len(df),) and ((p >= 0) & (p <= 1)).all()
    # el conjunto debe distinguir mejor que el azar en datos con señal real
    from sklearn.metrics import roc_auc_score
    assert roc_auc_score((df["next"] > 0).astype(int), p) > 0.6
    # promedia de verdad: no es idéntico a un único árbol del conjunto
    single = mdl["models"][0].predict_proba(df[FEATS])[:, 1]
    assert not np.allclose(p, single)


def test_allocation_keeps_signals_without_ml_score():
    from screener.allocation import allocate
    out = allocate(_buy_df([float("nan"), float("nan")]), PROFILES["balanceado"])
    assert len(out) == 2  # sin modelo se opera como antes


def test_features_are_computable_with_short_live_window_and_match_history():
    from screener.ml_score import FEATS, compute_features
    idx = pd.date_range("2025-01-01", periods=420, freq="D")
    rng = np.random.default_rng(9)
    close = pd.DataFrame({c: 100 * np.cumprod(1 + rng.normal(0, 0.02, 420)) for c in ("BTC", "AAA", "BBB")}, index=idx)
    qv = pd.DataFrame(rng.uniform(1e7, 2e7, close.shape), index=idx, columns=close.columns)
    fg = pd.Series(rng.uniform(10, 90, 420), index=idx)
    ev = pd.DataFrame({"asset": ["AAA"], "date": [idx[-1]], "k": [3], "z": [4.0]})
    live = compute_features(close.iloc[-400:], qv.iloc[-400:], fg, ev, n_sig=2)
    full = compute_features(close, qv, fg, ev, n_sig=2)
    assert live[FEATS].notna().all().all()  # con 400 días todas las variables (ventanas de hasta 250) están definidas
    assert np.allclose(live[FEATS].values.astype(float), full[FEATS].values.astype(float), equal_nan=True)  # misma cifra con ventana corta o larga


def test_trend_signal_counts_moving_averages_and_targets_scale_with_fraction():
    from screener.trend import trend_signal, trend_targets
    up = pd.Series(np.linspace(100, 300, 260))            # sube siempre: por encima de las 3 medias
    down = pd.Series(np.linspace(300, 100, 260))          # baja siempre: por debajo de las 3
    assert trend_signal(up) == 1.0 and trend_signal(down) == 0.0
    mixed = pd.Series([100.0] * 150 + [200.0] * 60 + [190.0] * 50)  # último precio 190: bajo SMA100 (195), sobre SMA150 (170) y SMA200 (152.5)
    assert abs(trend_signal(mixed) - 2 / 3) < 1e-12
    assert np.isnan(trend_signal(pd.Series(np.arange(50.0))))  # historia insuficiente
    close = pd.DataFrame({"BTC": up, "ETH": down})
    t = trend_targets(close, 0.20)
    assert abs(t["BTC"]["target_w"] - 0.10) < 1e-12 and t["ETH"]["target_w"] == 0.0  # 20% repartido entre 2 monedas x señal


def test_catastrophe_stop_scales_with_volatility_within_bounds():
    from screener.risk import STOP_MAX, STOP_MIN, catastrophe_stop
    assert catastrophe_stop(0.01) == STOP_MIN  # muy poca volatilidad: se queda en el suelo
    assert catastrophe_stop(0.20) == STOP_MAX  # volatilidad extrema: se queda en el techo
    mid = catastrophe_stop(0.04)
    assert STOP_MIN < mid < STOP_MAX and abs(mid - 6.0 * 0.04) < 1e-9  # tramo intermedio: 6x sigma
    assert catastrophe_stop(float("nan")) == STOP_MAX and catastrophe_stop(None) == STOP_MAX  # sin dato: el más prudente
    assert catastrophe_stop(0.0) == STOP_MAX and catastrophe_stop(-0.01) == STOP_MAX  # datos inválidos: el más prudente

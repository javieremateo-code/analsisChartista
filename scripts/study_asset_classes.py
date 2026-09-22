"""Estudio común de rebote/reversión tras rachas, normalizado por volatilidad, en las 4 clases de activos.

Reglas pre-declaradas (no se optimizan): racha >= 2 días; magnitud z >= 3, 4 o 5 (desviaciones típicas
del movimiento de k días); compra tras caída (largo) y, como variante, venta en corto tras subida.
Criterio de "clase validada" (fijado antes de ver resultados): regla base long-only z>=4 con Sharpe
fuera de muestra >= 0.5, CAGR OOS > 0 y >= 100 operaciones OOS.

Uso: python -m scripts.study_asset_classes
"""
import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from screener.backtest import perf, portfolio
from screener.events import build_events
from screener.universe import ANN, CLASSES, COST, SPLIT, load_history

warnings.filterwarnings("ignore")
OUT = Path(__file__).resolve().parent.parent / "screener" / "validation.json"


def main():
    validation = {}
    for cls in CLASSES:
        close, open_ = load_history(cls)
        if close.empty:
            print(f"\n##### {cls}: sin datos")
            continue
        last_ok = close.apply(lambda s: s.last_valid_index())
        close = close.loc[:, last_ok >= last_ok.max() - pd.Timedelta(days=15)]  # descarta ETFs/activos ya inactivos
        split = pd.Timestamp(SPLIT[cls])
        ann, cost = ANN[cls], COST[cls]
        ev = build_events(close)
        print("\n" + "#" * 100)
        print(f"##### {cls.upper()} | {close.shape[1]} activos | {close.index[0].date()} -> {close.index[-1].date()} | {len(ev):,} eventos | costo {cost:.3%}/lado | OOS desde {split.date()}")
        bh = close.pct_change().mean(axis=1).fillna(0)
        pb, ps = perf(bh[bh.index < split], ann), perf(bh[bh.index >= split], ann)
        print(f"Referencia cesta comprar-y-mantener: IS CAGR {pb['cagr']:+.1%} | OOS CAGR {ps['cagr']:+.1%} (Sharpe {ps['sharpe']:.2f}, DD {ps['dd']:.0%})")

        # tabla de probabilidades agregada por dirección y magnitud z (racha >=2)
        e2 = ev[ev["next"].notna() & (ev["k"] >= 2)].copy()
        e2["rev"] = np.where(e2["dir"] == "down", e2["next"] > 0, e2["next"] < 0)
        base_all = ev[ev["next"].notna() & (ev["k"] >= 1)].copy()
        base_all["rev"] = np.where(base_all["dir"] == "down", base_all["next"] > 0, base_all["next"] < 0)
        print("\nP(reversión al día siguiente) por dirección y z (racha>=2)   [ IS n/P | OOS n/P ]")
        for dr in ("down", "up"):
            b = base_all[base_all["dir"] == dr]["rev"].mean()
            lab = "BAJADA→sube" if dr == "down" else "SUBIDA→baja"
            print(f"  {lab} (base {b:.1%})")
            for zb in range(0, 5):
                g = e2[(e2["dir"] == dr) & (e2["zb"] == zb)]
                if len(g) < 50:
                    continue
                gi, go = g[g["date"] < split], g[g["date"] >= split]
                zl = f"{zb}-{zb+1}σ" if zb < 4 else "4σ+"
                sgn = 1 if dr == "down" else -1
                print(f"    z {zl:>6}: n={len(g):6} P={g['rev'].mean():5.1%} ret sig.día {sgn*g['next'].mean():+.3%} (a favor) | IS {len(gi):5}/{gi['rev'].mean() if len(gi) else float('nan'):4.0%} | OOS {len(go):5}/{go['rev'].mean() if len(go) else float('nan'):4.0%}")

        print("\nBacktest de cartera (k>=2)   [total | IS | OOS]")
        best = None
        for dirs, lab in ((("down",), "LARGO tras caída"), (("down", "up"), "LARGO tras caída + CORTO tras subida")):
            for zmin in (3.0, 4.0, 5.0):
                d, e, tr = portfolio(ev, close.index, cost, dirs=dirs, kmin=2, zmin=zmin)
                pt = perf(d, ann)
                pi, po = perf(d[d.index < split], ann), perf(d[d.index >= split], ann)
                sel = ev[ev["next"].notna() & (ev["k"] >= 2) & (ev["z"] >= zmin) & ev["dir"].isin(dirs)]
                n_o = int((sel["date"] >= split).sum())
                print(f"  {lab:38} z>={zmin:.0f}: CAGR {pt['cagr']:+6.1%} Sharpe {pt['sharpe']:5.2f} DD {pt['dd']:6.1%} | IS {pi['cagr']:+6.1%} | OOS {po['cagr']:+6.1%} (Sharpe {po['sharpe']:5.2f}, DD {po['dd']:6.1%}) | n={len(tr)} (OOS {n_o}) neto/trade {tr.mean():+.3%} inv {(e>0).mean():.0%}")
                if dirs == ("down",) and zmin == 4.0:
                    best = dict(oos_sharpe=float(po["sharpe"]) if np.isfinite(po["sharpe"]) else None,
                                oos_cagr=float(po["cagr"]) if np.isfinite(po["cagr"]) else None,
                                n_oos=n_o, is_cagr=float(pi["cagr"]) if np.isfinite(pi["cagr"]) else None)
        ok = best and best["oos_sharpe"] is not None and best["oos_sharpe"] >= 0.5 and (best["oos_cagr"] or 0) > 0 and best["n_oos"] >= 100
        validation[cls] = dict(validated=bool(ok), **(best or {}))
        print(f"\n>>> Clase {cls}: {'VALIDADA' if ok else 'SIN EVIDENCIA SUFICIENTE'} (regla base long z>=4: {best})")

    OUT.write_text(json.dumps(validation, indent=2))
    print(f"\nGuardado {OUT}")


if __name__ == "__main__":
    main()

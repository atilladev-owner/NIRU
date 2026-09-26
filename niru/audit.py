"""Independent checks on the main run. Run after `python -m niru.run`.

1. Rebuild every position from the raw Binance files without the engine: entry prices, every
   funding payment, fees and profit must match the engine's record.
2. Final equity must equal deposits plus the sum of every position's profit.
3. A run cut off at 2023-06-30 must repeat every decision made before that date.
"""

from __future__ import annotations

import pickle
import sys

import numpy as np
import pandas as pd

from niru.carry import Params, simulate
from niru.data import DATA, ROOT, IntradayPrices, spot_pair

DAY = 86_400_000
CUT = 1_688_083_200_000  # 2023-06-30


def _minute(t: np.ndarray) -> np.ndarray:
    return (t + 30_000) // 60_000 * 60_000


def rebuild(positions: pd.DataFrame, prm: Params) -> list[tuple]:
    slip, stress = prm.slippage, prm.slippage * prm.stress_slip
    bad, cache = [], {}
    for p in positions.itertuples():
        if p.symbol not in cache:
            k = pd.read_parquet(DATA / "klines" / f"{p.symbol}.parquet")
            k = k[k.quote_volume > 0].set_index("open_time")
            s = pd.read_parquet(DATA / "spot" / f"{spot_pair(p.symbol)[0]}.parquet").drop_duplicates("open_time")
            s = s[s.quote_volume > 0].set_index("open_time")
            f = pd.read_parquet(DATA / "funding" / f"{p.symbol}.parquet")
            if len(cache) > 30:
                cache.clear()
            cache[p.symbol] = (k, s, f)
        k, s, f = cache[p.symbol]
        mult = spot_pair(p.symbol)[1]
        e_perp = k.open.get(p.entry_day, np.nan) * (1 - slip)
        e_spot = s.open.get(p.entry_day, np.nan) * (1 + slip)

        # funding: payments after entry, up to the last midnight the position was held,
        # valued at the price in force at the payment
        t = _minute(f.time.to_numpy())
        held_until = p.exit_day - DAY if p.reason in ("watchdog", "liquidated") else p.exit_day
        sel = (t > p.entry_day) & (t <= held_until)
        kt = k.index.to_numpy()
        j = np.clip(np.searchsorted(kt, t[sel], side="right") - 1, 0, None)
        price = np.where(kt[j] == t[sel], k.open.to_numpy()[j], k.close.to_numpy()[j])
        funding = float((f.rate.to_numpy()[sel] * price).sum() * p.qty)

        if p.reason == "signal":
            x_perp, x_spot, sl = k.open.get(p.exit_day, np.nan), s.open.get(p.exit_day, np.nan), slip
        elif p.reason in ("watchdog", "liquidated"):
            x_perp, x_spot, sl = p.exit_perp / (1 + stress), p.exit_spot / (1 - stress), stress
            day = k[(k.index >= p.exit_day - DAY) & (k.index < p.exit_day)]
            if not (day.high >= e_perp * (1 + prm.reset_frac / prm.leverage)).any():
                bad.append((p.Index, p.symbol, "watchdog exit without a crossing"))
        else:  # unavailable or end: exits at the day's marks
            x_perp, x_spot, sl = p.exit_perp / (1 + slip), p.exit_spot / (1 - slip), slip
        xp, xs = x_perp * (1 + sl), x_spot * (1 - sl)
        spot_leg = p.qty * mult * (xs - e_spot)
        posted = p.qty * k.open.get(p.entry_day) / prm.leverage
        perp_leg = -posted if p.reason == "liquidated" else p.qty * (e_perp - xp)
        fees = (p.qty * mult * e_spot * prm.spot_fee + p.qty * e_perp * prm.perp_fee + p.qty * mult * xs * prm.spot_fee
                + (0.0 if p.reason == "liquidated" else p.qty * xp * prm.perp_fee))
        pnl = spot_leg + perp_leg + funding - fees
        for name, mine, engine in (("entry_perp", e_perp, p.entry_perp), ("entry_spot", e_spot, p.entry_spot),
                                   ("funding", funding, p.funding), ("fees", fees, p.fees), ("pnl", pnl, p.pnl)):
            if not np.isclose(mine, engine, rtol=1e-6, atol=1e-6):
                bad.append((p.Index, p.symbol, p.reason, name, mine, engine))
    return bad


def truncated(pn, prm: Params):
    cut = int(np.searchsorted(pn.days, CUT))
    f = {k: (v[:cut + 1] if isinstance(v, np.ndarray) and v.ndim == 2 else v) for k, v in pn.__dict__.items()}
    f["days"] = pn.days[:cut + 1]
    short_pn = type(pn)(**f)
    return cut, simulate(short_pn, prm, IntradayPrices(short_pn))


def main() -> int:
    prm = Params()
    pn = pickle.loads((DATA / "panel.pkl").read_bytes())
    full = simulate(pn, prm, IntradayPrices(pn))
    ok = True

    bad = rebuild(full.positions, prm)
    print(f"rebuild: {len(full.positions)} positions, {len(bad)} mismatches")
    for b in bad[:10]:
        print("  ", b)
    ok &= not bad

    gap = abs((full.equity[-1] - full.deposits[-1]) - full.positions.pnl.sum())
    print(f"accounting: equity minus deposits differs from summed profit by {gap:.9f}")
    ok &= gap < 1e-6

    cut, short = truncated(pn, prm)
    key = ["symbol", "entry_day", "exit_day", "notional", "pnl"]
    a = full.positions[full.positions.exit_day < pn.days[cut]][key].reset_index(drop=True)
    b = short.positions[short.positions.exit_day < pn.days[cut]][key].reset_index(drop=True)
    same = np.allclose(full.equity[:cut], short.equity[:cut]) and a.round(9).equals(b.round(9))
    print(f"look ahead: run cut at 2023-06-30 {'matches' if same else 'DIFFERS FROM'} the full run ({len(a)} positions)")
    ok &= same

    print("audit passed" if ok else "audit FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

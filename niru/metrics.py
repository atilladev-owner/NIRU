"""Year end, per coin and lifetime statistics for a carry run."""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from niru.carry import DAY, Result


def nav(equity: np.ndarray, deposits: np.ndarray) -> np.ndarray:
    """Unitised NAV: each deposit buys units at the prevailing NAV, so flows never move it."""
    out = np.empty(len(equity))
    units, prev_dep, prev_eq = 0.0, 0.0, 0.0
    for i, (e, d) in enumerate(zip(equity, deposits)):
        if d != prev_dep:
            units += (d - prev_dep) / (prev_eq / units if units else 1.0)
        out[i] = e / units if units else 1.0
        prev_dep, prev_eq = d, e
    return out


def period(days, equity, deposits, t0: int, t1: int) -> dict:
    m = (days >= t0) & (days < t1)
    if not m.any():
        return {"pnl_usd": 0.0, "pnl_pct": np.nan, "dd_usd": 0.0, "dd_pct": 0.0}
    i0, i1 = np.flatnonzero(m)[[0, -1]]
    pnl = equity - deposits
    v = nav(equity, deposits)
    base_pnl = pnl[i0 - 1] if i0 > 0 else 0.0
    base_nav = v[i0 - 1] if i0 > 0 else 1.0
    seg_pnl = np.r_[base_pnl, pnl[i0:i1 + 1]]
    seg_nav = np.r_[base_nav, v[i0:i1 + 1]]
    return {
        "pnl_usd": float(pnl[i1] - base_pnl),
        "pnl_pct": float(v[i1] / base_nav - 1),
        "dd_usd": float((np.maximum.accumulate(seg_pnl) - seg_pnl).max()),
        "dd_pct": float((1 - seg_nav / np.maximum.accumulate(seg_nav)).max()),
    }


def trade_stats(t: pd.DataFrame) -> dict:
    pnl = t.pnl.to_numpy()
    wins, losses = pnl[pnl > 0].sum(), -pnl[pnl < 0].sum()
    pays = t.payments.sum()
    return {
        "positions": int(len(t)),
        "accuracy": float((pnl > 0).mean()) if len(t) else np.nan,
        "profit_factor": float(wins / losses) if losses > 0 else (np.inf if wins > 0 else np.nan),
        "fees": float(t.fees.sum()),
        "funding": float(t.funding.sum()),
        "payment_accuracy": float(t.positive.sum() / pays) if pays else np.nan,
    }


def year_bounds(y: int) -> tuple[int, int]:
    f = lambda yy: int(datetime(yy, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    return f(y), f(y + 1)


def summarize(r: Result) -> dict:
    P = r.positions.assign(year=pd.to_datetime(r.positions.exit_day, unit="ms").dt.year)
    days = r.days
    years = sorted(set(pd.to_datetime(days, unit="ms").year))
    total = {"years": {}, "lifetime": {}}
    for y in years:
        t0, t1 = year_bounds(y)
        total["years"][y] = {**period(days, r.equity, r.deposits, t0, t1), **trade_stats(P[P.year == y]),
                             "deposited": float(r.deposits[(days < t1)][-1])}
    total["lifetime"] = {**period(days, r.equity, r.deposits, int(days[0]), int(days[-1]) + DAY),
                         **trade_stats(P), "deposited": float(r.deposits[-1])}

    coins = []
    for sym, g in P.groupby("symbol"):
        g = g.sort_values("exit_day")
        deployed = g.notional * (1 + 1 / r.params.leverage)
        cum = g.pnl.cumsum().to_numpy()
        dd = float((np.maximum.accumulate(np.r_[0.0, cum]) - np.r_[0.0, cum]).max())
        row = {"symbol": sym, "years": {}, "lifetime": {**trade_stats(g), "pnl_usd": float(g.pnl.sum()),
               "return_on_deployed": float(g.pnl.sum() / deployed.sum()), "dd_usd": dd,
               "days_held": int(((g.exit_day - g.entry_day) // DAY).sum())}}
        for y, gy in g.groupby("year"):
            cy = gy.pnl.cumsum().to_numpy()
            row["years"][int(y)] = {
                **trade_stats(gy), "pnl_usd": float(gy.pnl.sum()),
                "return_on_deployed": float(gy.pnl.sum() / (gy.notional * (1 + 1 / r.params.leverage)).sum()),
                "dd_usd": float((np.maximum.accumulate(np.r_[0.0, cy]) - np.r_[0.0, cy]).max()),
                "days_held": int(((gy.exit_day - gy.entry_day) // DAY).sum()),
            }
        coins.append(row)
    coins.sort(key=lambda c: -c["lifetime"]["pnl_usd"])
    return {"total": total, "coins": coins}

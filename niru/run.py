"""Run every variant and write reports/results.json."""

from __future__ import annotations

import json
import math
import pickle
from datetime import datetime, timezone

import numpy as np

from niru.carry import Params, simulate
from niru.data import DATA, ROOT, IntradayPrices, build_panel
from niru.metrics import nav, summarize

START, END = 1_577_836_800_000, 1_788_134_400_000  # 2020-01-01 to 2026-08-31, the last day both markets have data
VARIANTS = {
    "main": ("7 day funding persistence, $25k liquidity floor, 10 slots, 1x, taker fees, 0.05% slippage", Params()),
    "slip10": ("Same with 0.10% slippage", Params(slippage=0.0010)),
    "slip15": ("Same with 0.15% slippage", Params(slippage=0.0015)),
    "safer": ("Safer: 7 day lookback, $50k liquidity floor, 7 day cost cover", Params(lookback=7, min_liquidity=50_000.0, hold_days=7)),
    "unfiltered": ("Audited setup before the filters: no persistence rule or liquidity floor", Params(persist_days=0, min_liquidity=0.0)),
}


def _clean(x):
    if isinstance(x, dict):
        return {str(k): _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, (float, np.floating)):
        return None if not math.isfinite(float(x)) else float(f"{float(x):.6g}")
    if isinstance(x, np.integer):
        return int(x)
    return x


def panel():
    path = DATA / "panel.pkl"
    if path.exists():
        return pickle.loads(path.read_bytes())
    pn = build_panel(START, END)
    path.write_bytes(pickle.dumps(pn))
    return pn


def _ms(y: int, m: int, d: int) -> int:
    return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)


def _window(pn, a: int, b: int, trade_from: int):
    """Days in [a, b). Days before trade_from are warm up: signal history, no entries."""
    m = (pn.days >= a) & (pn.days < b)
    f = {k: (v[m].copy() if isinstance(v, np.ndarray) and v.ndim == 2 else v) for k, v in pn.__dict__.items()}
    f["days"] = pn.days[m]
    f["liq_volume"][f["days"] < trade_from] = 0.0
    return type(pn)(**f)


def lump_sum(pn, amount: float = 10_000.0) -> dict:
    """$10,000 at the start of each year with no deposits, and once in January 2020 held to the end.

    Each year gets a December warm up so its filters have history on day one (2020 has none).
    """
    prm = Params(first_deposit=amount, monthly_deposit=0.0)

    def one(a: int, b: int, start: int) -> dict:
        p = _window(pn, a, b, start)
        r = simulate(p, prm, IntradayPrices(p))
        eq = r.equity[p.days >= start]
        P = r.positions
        return {"pnl_usd": float(eq[-1] - amount), "pnl_pct": float(eq[-1] / amount - 1),
                "dd_pct": float((1 - eq / np.maximum.accumulate(eq)).max()), "positions": int(len(P)),
                "accuracy": float((P.pnl > 0).mean()) if len(P) else None, "fees": float(P.fees.sum()),
                "funding": float(P.funding.sum()), "days": int(len(eq))}

    years = {}
    for y in range(2020, 2027):
        start, end = _ms(y, 1, 1), (_ms(y + 1, 1, 1) if y < 2026 else END + 86_400_000)
        years[str(y)] = one(_ms(y - 1, 12, 1) if y > 2020 else start, end, start)
    life = one(START, END + 86_400_000, START)
    life["annual"] = (1 + life["pnl_pct"]) ** (365.25 / life["days"]) - 1
    return {"amount": amount, "years": years, "lifetime": life}


def main() -> None:
    pn = panel()
    out = {"coins_tested": len(pn.symbols), "variants": {}}
    intraday = IntradayPrices(pn)
    for key, (label, prm) in VARIANTS.items():
        r = simulate(pn, prm, intraday)
        deployed = np.zeros(len(pn.days))
        for p in r.positions.itertuples():
            a, b = np.searchsorted(pn.days, [p.entry_day, p.exit_day])
            deployed[a:b] += p.notional * (1 + 1 / prm.leverage)
        util = np.divide(deployed, r.equity, out=np.zeros_like(deployed), where=r.equity > 0)
        out["variants"][key] = {
            "label": label,
            **summarize(r),
            "curve": {"start": int(pn.days[0]), "equity": r.equity.round(2).tolist(),
                      "deposits": r.deposits.tolist(), "nav": nav(r.equity, r.deposits).round(5).tolist(),
                      "utilisation": util.round(3).tolist()},
        }
        (ROOT / "reports").mkdir(exist_ok=True)
        r.positions.to_csv(ROOT / "reports" / f"positions_{key}.csv", index=False)
        L = out["variants"][key]["total"]["lifetime"]
        print(f"{key:11s} pnl {L['pnl_usd']:8.0f}  nav {L['pnl_pct']*100:6.2f}%  acc {L['accuracy']*100:5.1f}%  positions {L['positions']}")
    out["lump_sum"] = lump_sum(pn)
    life = out["lump_sum"]["lifetime"]
    print(f"lump sum   $10,000 to ${10_000 + life['pnl_usd']:,.0f}  {life['annual']*100:.2f}% a year")
    out["spot_candles_missing_at_watchdog"] = intraday.spot_missing
    (ROOT / "reports" / "results.json").write_text(json.dumps(_clean(out)))


if __name__ == "__main__":
    main()

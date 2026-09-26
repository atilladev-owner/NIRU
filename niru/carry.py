"""Funding rate carry: long spot, short perp, rotate daily into the richest funding."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

import numpy as np
import pandas as pd

DAY = 86_400_000
MMR = 0.005  # maintenance margin rate used for the liquidation price

# intraday(coin, day_index, trigger, liq_price) -> (reason, perp_price, spot_price) for the first
# 15 minute candle of that day whose perp high reached the trigger, priced at that candle's close.
Intraday = Callable[[int, int, float, float], tuple[str, float, float]]


@dataclass
class Params:
    k: int = 10  # max concurrent positions, equal equity slots
    leverage: float = 1.0  # perp short leverage; spot leg is always fully paid
    lookback: int = 3  # days of funding averaged for the signal
    hold_days: int = 14  # expected hold used to judge whether funding covers costs
    persist_days: int = 7  # entry needs funding positive on each of this many recent days; 0 is off
    min_liquidity: float = 25_000.0  # entry needs this trailing median 15m quote volume on the thinner leg
    reset_frac: float = 0.5  # watchdog: close both legs once price covers this share of the way to liquidation
    stress_slip: float = 3.0  # slippage multiple on watchdog exits, which happen in fast markets
    liq_share: float = 0.02  # max notional as a share of trailing median 15m volume
    spot_fee: float = 0.00075
    perp_fee: float = 0.00045  # taker; maker fills are not assumed
    slippage: float = 0.0005
    first_deposit: float = 100.0  # paid in on the first day
    monthly_deposit: float = 80.0  # paid in on the 1st of every later month

    @property
    def round_trip(self) -> float:
        """Cost of opening and closing both legs, as a share of notional."""
        return 2 * (self.spot_fee + self.perp_fee + 2 * self.slippage)


@dataclass
class Panel:
    """Daily arrays shaped (days, coins). Row d holds values known at 00:00 UTC of day d."""
    symbols: list[str]
    days: np.ndarray
    mult: np.ndarray  # spot units per perp contract
    perp_open: np.ndarray  # NaN when the perp does not trade that day
    perp_high: np.ndarray  # high of day d, only known at 00:00 of day d + 1
    perp_mark: np.ndarray  # open, or the last close once the perp stops trading
    spot_open: np.ndarray
    spot_mark: np.ndarray
    rate_sum: np.ndarray  # funding rates paid in (d - 1, d]
    value: np.ndarray  # USDT paid to a one contract short in (d - 1, d]
    payments: np.ndarray
    positive: np.ndarray
    liq_volume: np.ndarray
    valid: np.ndarray  # tradeable for a new entry: both prices, agreeing within tolerance, liquidity known
    stopped: np.ndarray  # perp or spot has traded for the last time; a delisted perp is settled by Binance
    perp_step: np.ndarray  # exchange order rules, per coin
    perp_min_qty: np.ndarray
    perp_min_notional: np.ndarray
    spot_step: np.ndarray
    spot_min_qty: np.ndarray
    spot_min_notional: np.ndarray


@dataclass
class _Pos:
    coin: int
    entry_i: int
    qty: float  # perp contracts; spot units = qty * mult
    notional: float
    entry_perp: float
    entry_spot: float
    margin: float
    liq_price: float
    fees: float
    outlay: float  # cash put in at entry, fees included
    funding: float = 0.0
    payments: float = 0.0
    positive: float = 0.0


@dataclass
class Result:
    params: Params
    days: np.ndarray
    equity: np.ndarray
    deposits: np.ndarray
    positions: pd.DataFrame


def _is_first_of_month(ms: int) -> bool:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).day == 1


def simulate(pn: Panel, prm: Params, intraday: Intraday) -> Result:
    n_days, n_coins = pn.perp_open.shape
    cash = 0.0
    deposited = 0.0
    held: dict[int, _Pos] = {}
    rows: list[dict] = []
    equity = np.zeros(n_days)
    deposits = np.zeros(n_days)
    step = np.maximum(pn.perp_step, pn.spot_step / pn.mult)  # contracts; both legs must match

    # Trailing mean daily funding rate over the lookback, known at 00:00 of day d. Exits read it
    # directly; entries also need the day to be tradeable and a full lookback of tradeable days.
    rs = np.nan_to_num(pn.rate_sum)
    csum = np.cumsum(rs, axis=0)
    trailing = np.full(rs.shape, np.nan)
    L = prm.lookback
    trailing[L - 1:] = (csum[L - 1:] - np.r_[np.zeros((1, n_coins)), csum[:-L]]) / L
    ok = (np.cumsum(pn.valid, axis=0) >= L) & pn.valid & (pn.liq_volume >= prm.min_liquidity)
    if prm.persist_days:
        pos = np.cumsum(rs > 0, axis=0)
        n = prm.persist_days
        ok[n - 1:] &= (pos[n - 1:] - np.r_[np.zeros((1, n_coins)), pos[:-n]]) == n
        ok[:n - 1] = False
    entry_signal = np.where(ok, trailing, np.nan)

    def mark(p: _Pos, i: int) -> float:
        spot = p.qty * pn.mult[p.coin] * pn.spot_mark[i, p.coin]
        return spot + p.margin + p.qty * (p.entry_perp - pn.perp_mark[i, p.coin])

    def close(p: _Pos, i: int, reason: str, perp_px: float, spot_px: float, slip: float) -> None:
        nonlocal cash
        spot_fill = spot_px * (1 - slip)
        spot_val = p.qty * pn.mult[p.coin] * spot_fill
        fees = spot_val * prm.spot_fee
        perp_fill = perp_px * (1 + slip)
        if reason == "liquidated":
            perp_back = 0.0  # isolated margin is gone
        else:
            perp_back = p.margin + p.qty * (p.entry_perp - perp_fill)
            fees += p.qty * perp_fill * prm.perp_fee
        proceeds = spot_val - fees + perp_back
        cash += proceeds
        total_fees = p.fees + fees
        pnl = proceeds - p.outlay + p.funding
        rows.append({
            "symbol": pn.symbols[p.coin], "entry_day": int(pn.days[p.entry_i]), "exit_day": int(pn.days[i]),
            "notional": p.notional, "funding": p.funding, "fees": total_fees,
            "basis": pnl - p.funding + total_fees, "pnl": pnl, "reason": reason,
            "payments": p.payments, "positive": p.positive, "qty": p.qty, "mult": pn.mult[p.coin],
            "entry_perp": p.entry_perp, "entry_spot": p.entry_spot, "exit_perp": perp_fill, "exit_spot": spot_fill,
        })
        del held[p.coin]

    for i in range(n_days):
        day = int(pn.days[i])
        # 1. deposits
        if i == 0 or _is_first_of_month(day):
            amount = prm.first_deposit if i == 0 else prm.monthly_deposit
            cash += amount
            deposited += amount

        # 2. watchdog and liquidation during the previous day, priced from its 15m candles
        if i > 0:
            for c, p in list(held.items()):
                trigger = p.entry_perp * (1 + prm.reset_frac / prm.leverage)
                if pn.perp_high[i - 1, c] >= min(trigger, p.liq_price):
                    reason, perp_px, spot_px = intraday(c, i - 1, trigger, p.liq_price)
                    close(p, i, reason, perp_px, spot_px, prm.slippage * prm.stress_slip)

        # 3. funding paid during the day just ended
        for c, p in held.items():
            got = p.qty * pn.value[i, c]
            p.funding += got
            p.payments += pn.payments[i, c]
            p.positive += pn.positive[i, c]
            cash += got

        # 4. exits
        for c, p in list(held.items()):
            if pn.stopped[i, c]:
                close(p, i, "unavailable", pn.perp_mark[i, c], pn.spot_mark[i, c], prm.slippage)
            elif trailing[i, c] < 0 and np.isfinite(pn.perp_open[i, c]) and np.isfinite(pn.spot_open[i, c]):
                close(p, i, "signal", pn.perp_open[i, c], pn.spot_open[i, c], prm.slippage)

        # 5. entries into the top k by trailing funding
        if i < n_days - 1:
            tr = entry_signal[i]
            eq = cash + sum(mark(p, i) for p in held.values())
            for c in np.argsort(-np.nan_to_num(tr, nan=-np.inf))[:prm.k]:
                if len(held) >= prm.k or not np.isfinite(tr[c]):
                    break
                if c in held or tr[c] * prm.hold_days <= prm.round_trip:
                    continue
                per_unit = ((1 + prm.slippage) * (1 + prm.spot_fee) + 1 / prm.leverage
                            + (1 - prm.slippage) * prm.perp_fee)
                notional = min(eq / prm.k, cash) / per_unit
                cap = prm.liq_share * pn.liq_volume[i, c]
                if np.isfinite(cap):
                    notional = min(notional, cap)
                qty = notional / pn.perp_open[i, c]
                if step[c] > 0:
                    qty = np.floor(qty / step[c] + 1e-9) * step[c]
                perp_px = pn.perp_open[i, c] * (1 - prm.slippage)
                spot_px = pn.spot_open[i, c] * (1 + prm.slippage)
                spot_units = qty * pn.mult[c]
                if (qty <= 0 or qty < pn.perp_min_qty[c] or spot_units < pn.spot_min_qty[c]
                        or qty * perp_px < pn.perp_min_notional[c]
                        or spot_units * spot_px < pn.spot_min_notional[c]):
                    continue
                notional = qty * pn.perp_open[i, c]
                spot_cost = spot_units * spot_px
                fees = spot_cost * prm.spot_fee + qty * perp_px * prm.perp_fee
                margin = notional / prm.leverage
                outlay = spot_cost + margin + fees
                if outlay > cash + 1e-9:
                    continue
                cash -= outlay
                held[c] = _Pos(
                    coin=c, entry_i=i, qty=qty, notional=notional, entry_perp=perp_px, entry_spot=spot_px, margin=margin,
                    liq_price=perp_px * (1 + 1 / prm.leverage) / (1 + MMR), fees=fees, outlay=outlay,
                )

        equity[i] = cash + sum(mark(p, i) for p in held.values())
        deposits[i] = deposited

    last = n_days - 1
    for c, p in list(held.items()):
        close(p, last, "end", pn.perp_mark[last, c], pn.spot_mark[last, c], prm.slippage)
    equity[-1] = cash

    cols = ["symbol", "entry_day", "exit_day", "notional", "funding", "fees", "basis", "pnl",
            "reason", "payments", "positive", "qty", "mult", "entry_perp", "entry_spot", "exit_perp", "exit_spot"]
    return Result(prm, pn.days, equity, deposits, pd.DataFrame(rows, columns=cols))

import numpy as np
import pandas as pd
import pytest

from niru.carry import Panel, Params, simulate
from niru.data import bucket_funding

DAY = 86_400_000
D0 = 1_577_836_800_000  # 2020-01-01


def panel(n_days=40, n_coins=1, price=100.0, rate=0.0003):
    shape = (n_days, n_coins)
    p = np.full(shape, price)
    ones = np.ones(n_coins)
    return Panel(
        symbols=[f"C{i}USDT" for i in range(n_coins)],
        days=D0 + np.arange(n_days) * DAY,
        mult=ones.copy(),
        perp_open=p.copy(), perp_high=p.copy(), perp_mark=p.copy(), spot_open=p.copy(), spot_mark=p.copy(),
        rate_sum=np.full(shape, rate), value=np.full(shape, rate * price),
        payments=np.full(shape, 3.0), positive=np.full(shape, 3.0 if rate > 0 else 0.0),
        liq_volume=np.full(shape, 1e12), valid=np.ones(shape, bool), stopped=np.zeros(shape, bool),
        perp_step=np.zeros(n_coins), perp_min_qty=np.zeros(n_coins), perp_min_notional=ones * 5,
        spot_step=np.zeros(n_coins), spot_min_qty=np.zeros(n_coins), spot_min_notional=ones * 5,
    )


def no_cross(coin, day_i, trigger, liq):
    raise AssertionError("intraday lookup should not be needed")


FREE = dict(spot_fee=0.0, perp_fee=0.0, slippage=0.0)


def run(pn, intraday=no_cross, **kw):
    # Mechanics tests run without the entry filters unless a test switches them on.
    return simulate(pn, Params(**{"persist_days": 0, "min_liquidity": 0.0, **kw}), intraday)


def _candles(n=3 * 96):
    t = D0 + np.arange(n) * 15 * 60_000
    return pd.DataFrame({"open_time": t, "open": 100.0, "close": 100.0})


def test_funding_stamped_just_after_midnight_belongs_to_that_midnight():
    f = pd.DataFrame({"time": [D0 + DAY + 2, D0 + DAY + 8 * 3_600_000 + 1], "rate": [0.001, 0.002]})
    b = bucket_funding(f, _candles())
    assert b.loc[D0 + DAY, "rate_sum"] == pytest.approx(0.001)  # 00:00:00.002 is the midnight payment
    assert b.loc[D0 + 2 * DAY, "rate_sum"] == pytest.approx(0.002)


def test_funding_is_valued_at_the_price_in_force_never_a_later_one():
    k = _candles()
    k.loc[k.open_time == D0 + 4 * 3_600_000 - 15 * 60_000, "close"] = 90.0  # last close before a gap
    k = k[(k.open_time < D0 + 4 * 3_600_000) | (k.open_time >= D0 + 5 * 3_600_000)]  # no candles 04:00 to 05:00
    k.loc[k.open_time == D0 + 5 * 3_600_000, "open"] = 200.0
    f = pd.DataFrame({"time": [D0 + 4 * 3_600_000], "rate": [0.001]})
    assert bucket_funding(f, k).loc[D0 + DAY, "value"] == pytest.approx(0.001 * 90.0)


def test_no_trade_when_funding_cannot_cover_costs():
    assert len(run(panel(rate=0.00001), k=1).positions) == 0


def test_enters_only_once_funding_is_known():
    pn = panel(rate=0.0)
    pn.rate_sum[5:] = 0.001
    pn.value[5:] = 0.1
    r = run(pn, k=1, **FREE)
    assert r.positions.entry_day.min() == pn.days[5]


def test_flat_prices_zero_fees_pnl_equals_funding_received():
    pn = panel(n_days=20, rate=0.001)
    pn.value[:] = 0.1
    p = run(pn, k=1, **FREE).positions.iloc[0]
    qty = 50.0 / 100  # $100 slot at 1x: $50 notional plus $50 margin
    assert p.funding == pytest.approx(qty * 0.1 * ((p.exit_day - p.entry_day) // DAY))
    assert p.pnl == pytest.approx(p.funding)


def test_fees_charged_on_both_legs_both_ways():
    pn = panel(n_days=20, rate=0.001)
    pn.value[:] = 0.0
    p = run(pn, k=1, spot_fee=0.00075, perp_fee=0.00045, slippage=0.0).positions.iloc[0]
    n = 100 / (1 + 0.00075 + 1 + 0.00045)
    assert p.notional == pytest.approx(n)
    assert p.fees == pytest.approx(2 * n * (0.00075 + 0.00045))
    assert p.pnl == pytest.approx(-p.fees)


def test_hedge_cancels_price_move():
    pn = panel(n_days=20, rate=0.001)
    pn.value[:] = 0.0
    for a in (pn.perp_open, pn.perp_mark, pn.spot_open, pn.spot_mark, pn.perp_high):
        a[10:] = 120.0
    assert run(pn, k=1, **FREE).positions.pnl.sum() == pytest.approx(0.0, abs=1e-9)


def test_watchdog_exits_at_real_intraday_prices_of_both_legs():
    pn = panel(n_days=20, rate=0.001)
    pn.value[:] = 0.0
    pn.perp_high[6] = 160.0
    seen = []

    def intraday(coin, day_i, trigger, liq):
        seen.append((day_i, round(trigger, 6)))
        return "watchdog", 151.0, 140.0  # perp squeezed above spot at the trigger candle close

    p = run(pn, intraday, k=1, **FREE).positions.iloc[0]
    assert seen == [(6, 150.0)]
    assert p.reason == "watchdog"
    assert p.exit_day == pn.days[7]
    assert p.pnl == pytest.approx(0.5 * (140 - 100) + 0.5 * (100 - 151))  # basis loss is real


def test_liquidation_loses_the_margin():
    pn = panel(n_days=20, rate=0.001)
    pn.value[:] = 0.0
    pn.perp_high[6] = 260.0
    p = run(pn, lambda c, d, t, l: ("liquidated", l, 190.0), k=1, **FREE).positions.iloc[0]
    assert p.reason == "liquidated"
    assert p.pnl == pytest.approx(0.5 * (190 - 100) - 50.0)  # spot gain minus the whole perp margin


def test_watchdog_still_checked_when_the_day_fails_the_price_check():
    pn = panel(n_days=20, rate=0.001)
    pn.value[:] = 0.0
    pn.perp_high[6] = 160.0
    pn.valid[6] = False  # perp and spot diverged, but both still trade
    p = run(pn, lambda c, d, t, l: ("watchdog", 150.0, 150.0), k=1, **FREE).positions.iloc[0]
    assert p.reason == "watchdog"


def test_divergence_alone_does_not_force_an_exit():
    pn = panel(n_days=20, rate=0.001)
    pn.valid[8:10] = False
    assert list(run(pn, k=1, **FREE).positions.reason) == ["end"]


def test_missing_price_closes_at_current_prices_not_stale_ones():
    pn = panel(n_days=20, rate=0.001)
    pn.value[:] = 0.0
    pn.perp_open[10:] = np.nan  # perp delisted; settles at its last close
    pn.perp_mark[10:] = 100.0
    pn.spot_open[10:] = pn.spot_mark[10:] = 80.0  # spot kept trading and fell
    pn.valid[10:] = False
    pn.stopped[10:] = True
    p = run(pn, k=1, **FREE).positions.iloc[0]
    assert p.reason == "unavailable"
    assert p.exit_day == pn.days[10]
    assert p.pnl == pytest.approx(0.5 * (80 - 100))


def test_funding_is_credited_on_the_day_a_position_closes_for_missing_data():
    pn = panel(n_days=20, rate=0.001)
    pn.value[:] = 0.1
    pn.perp_open[10:] = np.nan
    pn.valid[10:] = False
    pn.stopped[10:] = True
    p = run(pn, k=1, **FREE).positions.iloc[0]
    assert p.funding == pytest.approx(0.5 * 0.1 * (10 - 2))


def test_quantity_rounds_down_to_the_coarser_step():
    pn = panel(n_days=20, rate=0.001)
    pn.perp_step[:] = 0.1
    pn.spot_step[:] = 0.3  # spot step dominates
    p = run(pn, k=1, **FREE).positions.iloc[0]
    assert p.notional == pytest.approx(30.0)  # 0.5 contracts rounds down to 0.3


def test_orders_below_exchange_minimums_are_skipped():
    pn = panel(n_days=20, rate=0.001)
    pn.perp_min_notional[:] = 60.0  # $100 at 1x buys only $50 of notional
    assert len(run(pn, k=1, **FREE).positions) == 0
    pn = panel(n_days=20, rate=0.001)
    pn.perp_min_qty[:] = 1.0
    assert len(run(pn, k=1, **FREE).positions) == 0


def test_exit_when_trailing_funding_turns_negative():
    pn = panel(n_days=30, rate=0.001)
    pn.rate_sum[12:] = -0.001
    p = run(pn, k=1, **FREE).positions.iloc[0]
    assert p.reason == "signal"
    assert p.exit_day <= pn.days[14]


def test_a_held_position_is_kept_while_funding_stays_positive():
    pn = panel(n_days=30, n_coins=2)
    pn.rate_sum[:, 0] = 0.001
    pn.rate_sum[:, 1] = 0.0005
    pn.rate_sum[15:, 1] = 0.003
    p = run(pn, k=1, **FREE).positions
    assert list(p.symbol) == ["C0USDT"]
    assert p.iloc[0].reason == "end"


def test_top_k_by_trailing_funding():
    pn = panel(n_coins=3)
    pn.rate_sum[:, 0] = 0.0005
    pn.rate_sum[:, 1] = 0.002
    pn.rate_sum[:, 2] = 0.001
    assert set(run(pn, k=2, **FREE).positions.symbol) == {"C1USDT", "C2USDT"}


def test_equal_slots_share_equity():
    first = run(panel(n_coins=2), k=2, **FREE).positions.groupby("symbol").notional.first()
    assert list(first) == pytest.approx([25.0, 25.0])


def test_deposits_and_equity_curve():
    r = run(panel(n_days=40, rate=0.0), k=1, **FREE)
    assert r.deposits[0] == 100.0
    assert r.deposits[-1] == 180.0
    np.testing.assert_allclose(r.equity, r.deposits)


def test_final_equity_equals_deposits_plus_every_position_pnl():
    rng = np.random.default_rng(5)
    pn = panel(n_days=120, n_coins=6)
    walk = 100 * np.exp(np.cumsum(rng.normal(0, 0.03, pn.perp_open.shape), axis=0))
    for a in (pn.perp_open, pn.perp_mark, pn.spot_open, pn.spot_mark):
        a[:] = walk
    pn.perp_high[:] = walk * 1.02
    pn.rate_sum[:] = rng.normal(0.0005, 0.001, pn.rate_sum.shape)
    pn.value[:] = pn.rate_sum * walk
    r = run(pn, lambda c, d, t, l: ("watchdog", t, t), k=3, leverage=1.0)
    assert len(r.positions) > 5
    assert r.equity[-1] - r.deposits[-1] == pytest.approx(r.positions.pnl.sum())


def test_zero_volume_candles_do_not_count_as_trading():
    from niru.data import daily_bars

    t = D0 + np.arange(3 * 96) * 15 * 60_000
    k = pd.DataFrame({"open_time": t, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
                      "quote_volume": 1000.0})
    k.loc[k.open_time >= D0 + DAY + 10 * 3_600_000, ["open", "high", "low", "close"]] = 80.0
    k.loc[k.open_time >= D0 + DAY + 10 * 3_600_000, "quote_volume"] = 0.0  # delisted at 10:00 on day 1
    d = daily_bars(k, D0 + np.arange(3) * DAY)
    assert d.open.iloc[1] == 100.0
    assert d.high.iloc[1] == 101.0  # the flat settlement candles are ignored
    assert np.isnan(d.open.iloc[2])  # day 2 has no trading at all
    assert d["mark"].iloc[2] == 100.5  # carried from the last real close


def test_a_temporary_gap_is_held_through_not_exited():
    pn = panel(n_days=20, rate=0.001)
    pn.perp_open[10] = np.nan  # no candle at 00:00, trading resumes the next day
    pn.valid[10] = False
    p = run(pn, k=1, **FREE).positions
    assert list(p.reason) == ["end"]


def test_persistence_requires_funding_positive_on_each_recent_day():
    pn = panel(n_days=30, rate=0.001)
    pn.rate_sum[2] = -0.0005  # one negative day
    r = run(pn, k=1, persist_days=5, **FREE)
    assert r.positions.entry_day.min() == pn.days[7]  # days 3 to 7 are the first 5 positive in a row
    assert run(pn, k=1, **FREE).positions.entry_day.min() == pn.days[2]  # without the filter


def test_liquidity_floor_blocks_thin_markets():
    pn = panel(n_days=20, rate=0.001)
    pn.liq_volume[:] = 10_000.0
    assert len(run(pn, k=1, min_liquidity=20_000.0, **FREE).positions) == 0
    assert len(run(pn, k=1, min_liquidity=5_000.0, **FREE).positions) == 1


def test_lump_sum_without_monthly_deposits():
    r = run(panel(n_days=40, rate=0.0), k=1, first_deposit=10_000.0, monthly_deposit=0.0, **FREE)
    assert r.deposits[0] == 10_000.0
    assert r.deposits[-1] == 10_000.0  # Feb 1 adds nothing

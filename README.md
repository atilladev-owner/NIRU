# NIRU

Audited backtester for a delta neutral Binance funding carry bot. 476 coins, 2020 to 2026, every trade rebuilt from raw exchange data.

NIRU buys a coin on spot and shorts the same amount on its USDT perpetual. Price moves cancel, and what is left is the funding rate that leveraged longs pay shorts every eight hours. The project is the backtester, a full audit of it, and a static site that presents the results.

## Verdict

The edge is real and small. NIRU earns roughly what funding pays: rich in bull markets, close to nothing when leverage leaves. It is shelved as a money maker and published as a piece of engineering.

| January 2020 to August 2026 | |
|---|---|
| Deposited | $100, then $80 on the 1st of each month: $6,420 |
| Profit after deposits | +$1,047 |
| Return a year, time weighted | 6.67% |
| Positions | 383 |
| Closed in profit | 71.8% |
| Funding payments in its favour | 95.8% |
| Worst drawdown | 2.49% |
| Fees paid | $154 |
| Funding collected | $1,184 |

A single $10,000 in January 2020, with no further deposits, became $16,132 by August 2026, 7.44% a year. More capital does not raise the rate: in lean years most of the money sits idle because few coins pay enough funding to be worth holding.

### By year

| Year | Return | Profit | Worst drawdown | Positions | Accuracy | Fees | Funding |
|---|---|---|---|---|---|---|---|
| 2020 | +10.20% | +$59 | 0.13% | 61 | 82.0% | $4 | $56 |
| 2021 | +22.03% | +$301 | 0.20% | 95 | 84.2% | $18 | $315 |
| 2022 | +0.19% | +$4 | 0.18% | 32 | 62.5% | $9 | $40 |
| 2023 | +3.68% | +$145 | 0.14% | 48 | 68.8% | $22 | $113 |
| 2024 | +6.97% | +$333 | 0.83% | 58 | 70.7% | $36 | $381 |
| 2025 | -1.27% | -$79 | 2.49% | 55 | 56.4% | $37 | $145 |
| 2026 to Aug | +4.28% | +$284 | 0.51% | 34 | 58.8% | $28 | $135 |

### $10,000 at the start of each year, no deposits

| Year | Return | Profit | Worst drawdown | Positions |
|---|---|---|---|---|
| 2020 | +13.1% | +$1,313 | 0.3% | 76 |
| 2021 | +24.4% | +$2,440 | 0.2% | 106 |
| 2022 | +0.0% | +$4 | 0.2% | 24 |
| 2023 | +3.6% | +$365 | 0.1% | 58 |
| 2024 | +7.6% | +$757 | 0.9% | 62 |
| 2025 | -0.9% | -$92 | 2.5% | 58 |
| 2026 to Aug | -0.1% | -$12 | 0.5% | 29 |

### Variants

| Variant | Setup | Profit | Accuracy | Worst drawdown | Positions |
|---|---|---|---|---|---|
| Main | 7 day funding persistence, $25k liquidity floor, 10 slots, 1x, taker fees, 0.05% slippage | +$1,047 | 71.8% | 2.49% | 383 |
| 0.10% slippage | Same with 0.10% slippage | +$531 | 71.1% | 3.16% | 304 |
| 0.15% slippage | Same with 0.15% slippage | +$432 | 64.5% | 2.74% | 287 |
| Safer | Safer: 7 day lookback, $50k liquidity floor, 7 day cost cover | +$855 | 84.6% | 0.81% | 221 |
| Without filters | Audited setup before the filters: no persistence rule or liquidity floor | +$705 | 58.5% | 4.26% | 600 |

## The rules

1. Every day at 00:00 UTC, rank coins by their average funding rate over the last 3 days, using only payments already made.
2. Enter a coin when it ranks in the top 10, when 14 days of that funding would cover the round trip cost, when funding was positive on each of the last 7 days, and when the thinner leg trades at least $25,000 per 15 minutes.
3. Hold spot and a 1x perp short of equal size. Each position takes an equal share of the pool.
4. Close when the 3 day funding average turns negative, when the market stops trading for good, or when the perp rises halfway to the short's liquidation price (the watchdog).

Costs: spot 0.075%, perp 0.045% taker on every order, 0.05% slippage per fill and triple that on watchdog exits. Funding is the real history.

## The audit

The first version of this backtest reported $1,110 at 62.2% accuracy. A second script rebuilt every trade from the raw Binance files and found ten ways the model flattered itself. Each was closed behind a failing test.

1. Funding stamped a few milliseconds after midnight was counted a day late, crediting new positions with a payment made before they opened.
2. Delisted contracts kept publishing flat, zero volume candles in the archive, and the model traded them as live markets.
3. Watchdog exits assumed spot moved in step with the perp. They are now priced from real 15 minute candles of both legs.
4. Watchdog and liquidation checks were skipped on the days spot and perp disagreed, which are the squeeze days.
5. Positions were closed and marked at stale prices when data broke.
6. Binance minimum order sizes and quantity steps were ignored.
7. Perp orders were assumed to fill as maker. Every order now pays the taker fee.
8. A maintenance gap forced an exit. Only a market that never trades again does now.
9. Funding across a data gap was valued at a later price.
10. September 2026 spot files were not yet published, so the backtest ends on 2026-08-31.

Verification:

- `niru/audit.py` rebuilds all 383 positions of the main run from the raw files: entry prices, every funding payment, fees and profit. Zero mismatches.
- Final equity equals deposits plus the sum of every position's profit, to the cent.
- A run cut off at June 2023 reproduces every earlier decision exactly, so no result depends on future data.
- The two entry filters were chosen on 2020 to 2023 and confirmed on 2024 to 2026. The rule set in advance picked the unfiltered setup; the filters were adopted because they raised accuracy on unseen data in every paired comparison. The leverage and exit rules were set after seeing the full period, so treat lifetime figures as optimistic.

## Reproduce

```
pip install -e ".[dev]"
python -m niru.data          # download candles, funding and order rules to data/ (large)
python -m pytest             # 29 tests
python -m niru.run           # every variant plus the lump sum run, into reports/
python -m niru.audit         # rebuild every position from raw data, accounting and look ahead checks
python -m niru.site --fonts  # site data and self hosted fonts, into site/
```

Open `site/index.html` through any static server, for example `python -m http.server -d site`.

## Layout

| Path | What it holds |
|---|---|
| `niru/data.py` | Binance archive downloads, the daily panel, 15 minute exit prices |
| `niru/carry.py` | The strategy and account simulator |
| `niru/metrics.py` | Yearly and lifetime statistics |
| `niru/run.py` | Every variant and the lump sum run |
| `niru/audit.py` | Independent rebuild of every position, accounting and look ahead checks |
| `niru/site.py` | Site data and fonts |
| `reports/` | Results and every position of each variant |
| `site/` | The static site deployed on Vercel |
| `tests/` | Engine, data and metrics tests |

Raw Binance data is not in the repository. `python -m niru.data` downloads it.

## Known limits

- Binance publishes no historical spot order book, so spot spreads cannot be measured. The slippage variants show how much execution cost the strategy absorbs.
- A live bot would also need Binance's delisting announcements, which no public dataset carries.
- Order rules come from today's exchange info and are applied to the whole period.

## Credits

- Market data: the Binance public data archive at data.binance.vision.
- Fonts: Bricolage Grotesque, Instrument Sans and Martian Mono, under the SIL Open Font License 1.1.
- GitHub icon: Phosphor Icons, MIT License.

## License

PolyForm Noncommercial 1.0.0. You may read, run, modify and share NIRU for any noncommercial purpose. Commercial use needs permission. See `LICENSE.md`.

Backtest only. Not financial advice.

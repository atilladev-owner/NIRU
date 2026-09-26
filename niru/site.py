"""Build the static site's data and fonts. Run after `python -m niru.run`.

    python -m niru.site          # data only
    python -m niru.site --fonts  # also fetch the self hosted font files
"""

from __future__ import annotations

import json
import pickle
import re
import sys

import numpy as np
import pandas as pd
import requests

from niru.data import DATA, ROOT

SITE = ROOT / "site"
REPORTS = ROOT / "reports"
WEEK = 7

FONTS_CSS = ("https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wdth,wght@12..96,75..100,500..800"
             "&family=Instrument+Sans:wght@400;500;600&family=Martian+Mono:wdth,wght@87.5,400;87.5,500&display=swap")
FONT_FILES = {"Bricolage Grotesque": "bricolage-grotesque", "Instrument Sans": "instrument-sans", "Martian Mono": "martian-mono"}
# Audit stages as reported: before the audit, after it, and with the two entry filters.
STAGES = [
    {"name": "First backtest", "pnl": 1110, "acc": 0.622, "dd": 0.0075, "pos": 806},
    {"name": "After the audit", "pnl": 705, "acc": 0.585, "dd": 0.0426, "pos": 600},
    {"name": "With filters", "pnl": 1047, "acc": 0.718, "dd": 0.0249, "pos": 383},
]
KEEP = ["pnl_usd", "pnl_pct", "dd_usd", "dd_pct", "positions", "accuracy", "profit_factor", "fees", "funding",
        "payment_accuracy", "deposited"]


def pulse(pn, positions: pd.DataFrame) -> dict:
    """Weekly market funding (median and top decile, % a year) and positions NIRU held."""
    n = len(pn.days)
    week = np.arange(n) // WEEK
    rate = np.where(np.isfinite(pn.perp_open), np.nan_to_num(pn.rate_sum), np.nan) * 365 * 100
    held = np.zeros(n, int)
    for p in positions.itertuples():
        a, b = np.searchsorted(pn.days, [p.entry_day, p.exit_day])
        held[a:b] += 1
    med, p90, listed, hold = [], [], [], []
    for w in range(int(week[-1]) + 1):
        rows = week == w
        per_coin = rate[rows]
        counts = np.isfinite(per_coin).sum(0)
        coin_mean = np.nansum(per_coin, 0)[counts > 0] / counts[counts > 0]
        med.append(round(float(np.median(coin_mean)), 1))
        p90.append(round(float(np.percentile(coin_mean, 90)), 1))
        listed.append(int(coin_mean.size))
        hold.append(int(round(held[rows].mean())))
    return {"start": int(pn.days[0]), "median": med, "p90": p90, "listed": listed, "held": hold}


def results(raw: dict) -> dict:
    v = raw["variants"]["main"]
    c = v["curve"]
    pick = lambda s: {k: s[k] for k in KEEP if k in s}
    coins = [{"s": x["symbol"].removesuffix("USDT"), "pnl": x["lifetime"]["pnl_usd"],
              "ret": x["lifetime"]["return_on_deployed"], "n": x["lifetime"]["positions"],
              "acc": x["lifetime"]["accuracy"], "fund": x["lifetime"]["funding"], "fees": x["lifetime"]["fees"],
              "days": x["lifetime"]["days_held"]} for x in v["coins"]]
    return {
        "start": c["start"],
        "pnl": [round(e - d, 2) for e, d in zip(c["equity"], c["deposits"])],
        "deposits": c["deposits"],
        "life": pick(v["total"]["lifetime"]),
        "years": {y: pick(s) for y, s in v["total"]["years"].items()},
        "coins": coins,
        "coinsTested": raw["coins_tested"],
        "variants": [{"key": k, "label": x["label"], **pick(x["total"]["lifetime"])} for k, x in raw["variants"].items()],
        "stages": STAGES,
    }


def fonts() -> None:
    """Download the latin subset of each font and write site/fonts.css."""
    ua = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
    css = requests.get(FONTS_CSS, headers=ua, timeout=30).text
    out, done = [], set()
    for block in re.findall(r"/\* latin \*/\s*(@font-face \{.*?\})", css, re.S):
        family = re.search(r"font-family: '([^']+)'", block).group(1)
        url = re.search(r"url\((https://[^)]+\.woff2)\)", block).group(1)
        name = FONT_FILES[family]
        if name not in done:
            (SITE / "fonts").mkdir(exist_ok=True)
            (SITE / "fonts" / f"{name}.woff2").write_bytes(requests.get(url, timeout=60).content)
            done.add(name)
        out.append(block.replace(url, f"fonts/{name}.woff2"))
    header = "/* Self hosted from Google Fonts, SIL Open Font License 1.1. Latin subset only. */\n"
    (SITE / "fonts.css").write_text(header + "\n".join(out) + "\n", encoding="utf-8")
    print("fonts:", sorted(done))


def main() -> None:
    pn = pickle.loads((DATA / "panel.pkl").read_bytes())
    positions = pd.read_csv(REPORTS / "positions_main.csv")
    raw = json.loads((REPORTS / "results.json").read_text())
    (SITE / "data").mkdir(parents=True, exist_ok=True)
    (SITE / "data" / "pulse.json").write_text(json.dumps(pulse(pn, positions), separators=(",", ":")))
    (SITE / "data" / "results.json").write_text(json.dumps(results(raw), separators=(",", ":")))
    print("site data written")
    if "--fonts" in sys.argv:
        fonts()


if __name__ == "__main__":
    main()

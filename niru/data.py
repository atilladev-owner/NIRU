"""Binance archive access and the daily panels the carry engine runs on."""

from __future__ import annotations

import io
import json
import re
import time
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
ARCHIVE = "https://data.binance.vision"
BUCKET = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
FAPI = "https://fapi.binance.com"
DAY_MS = 86_400_000
M15 = 15 * 60_000
SPOT_OVERRIDES = {"LUNA2USDT": ("LUNAUSDT", 1.0)}  # the relaunched chain trades as LUNA on spot
INDEX_CONTRACTS = {"BTCDOMUSDT", "DEFIUSDT", "FOOTBALLUSDT", "BLUEBIRDUSDT"}
PRICE_TOLERANCE = 0.03  # spot and perp must agree within 3% for a day to allow a new entry
_session = requests.Session()


def _get(url: str, **kw) -> requests.Response | None:
    for attempt in range(5):
        try:
            r = _session.get(url, timeout=30, **kw)
            if r.status_code == 404:
                return None
            if r.status_code in (418, 429) or r.status_code >= 500:
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            return r
        except requests.RequestException:
            if attempt == 4:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError(f"gave up on {url}")


def parse_kline_zip(blob: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        text = z.read(z.namelist()[0]).decode()
    header = 0 if not text[:1].isdigit() else None
    df = pd.read_csv(io.StringIO(text), header=header).iloc[:, [0, 1, 2, 3, 4, 7]]
    df.columns = ["open_time", "open", "high", "low", "close", "quote_volume"]
    df["open_time"] = df["open_time"].astype("int64")
    df.loc[df.open_time > 10**14, "open_time"] //= 1000  # microsecond files
    return df.astype({c: "float64" for c in df.columns[1:]})


def _list(prefix: str, folders: bool = False) -> list[str]:
    ns = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
    out, marker = [], ""
    while True:
        params = {"prefix": prefix, "marker": marker, **({"delimiter": "/"} if folders else {})}
        root = ET.fromstring(_get(BUCKET, params=params).content)
        path = "s3:CommonPrefixes/s3:Prefix" if folders else "s3:Contents/s3:Key"
        items = [k.text for k in root.findall(path, ns)]
        out += items
        if root.findtext("s3:IsTruncated", namespaces=ns) != "true" or not items:
            return out if folders else sorted(k for k in out if k.endswith(".zip"))
        marker = root.findtext("s3:NextMarker", namespaces=ns) or items[-1]


def _fetch(keys: list[str]) -> list[bytes]:
    with ThreadPoolExecutor(8) as pool:
        return [r.content for r in pool.map(lambda k: _get(f"{ARCHIVE}/{k}"), keys) if r is not None]


def spot_pair(perp: str) -> tuple[str, float]:
    """Spot symbol and quantity multiplier for a perp: 1000SHIBUSDT -> (SHIBUSDT, 1000)."""
    if perp in SPOT_OVERRIDES:
        return SPOT_OVERRIDES[perp]
    base = perp.removesuffix("USDT")
    m = re.fullmatch(r"(1000000|1000)([A-Z].*)", base)
    if m:
        return m.group(2) + "USDT", float(m.group(1))
    return perp, 1.0


# ---------------------------------------------------------------- downloads

def download_spot(perp: str) -> bool:
    """Daily spot candles. False when the coin has no Binance spot market."""
    spot, _ = spot_pair(perp)
    path = DATA / "spot" / f"{spot}.parquet"
    if path.exists():
        return True
    blobs = _fetch(_list(f"data/spot/monthly/klines/{spot}/1d/"))
    if not blobs:
        return False
    df = pd.concat([parse_kline_zip(b) for b in blobs]).drop_duplicates("open_time").sort_values("open_time")
    path.parent.mkdir(exist_ok=True)
    df.reset_index(drop=True).to_parquet(path)
    return True


def download_perp(symbol: str, active: bool) -> None:
    """15m klines (monthly then daily files) and funding (archive plus REST for the live month)."""
    kpath = DATA / "klines" / f"{symbol}.parquet"
    fpath = DATA / "funding" / f"{symbol}.parquet"
    if not kpath.exists():
        monthly = _list(f"data/futures/um/monthly/klines/{symbol}/15m/")
        last = monthly[-1][-11:-4] if monthly else "0000-00"
        daily = [k for k in _list(f"data/futures/um/daily/klines/{symbol}/15m/") if k[-14:-7] > last]
        frames = [parse_kline_zip(b) for b in _fetch(monthly + daily)]
        if not frames:
            return
        kpath.parent.mkdir(exist_ok=True)
        pd.concat(frames).drop_duplicates("open_time").sort_values("open_time").reset_index(drop=True).to_parquet(kpath)
    if not fpath.exists():
        frames = []
        for b in _fetch(_list(f"data/futures/um/monthly/fundingRate/{symbol}/")):
            with zipfile.ZipFile(io.BytesIO(b)) as z:
                f = pd.read_csv(z.open(z.namelist()[0]))
            frames.append(pd.DataFrame({"time": f.iloc[:, 0].astype("int64"), "rate": f.iloc[:, 2].astype("float64")}))
        df = pd.concat(frames) if frames else pd.DataFrame({"time": pd.Series(dtype="int64"), "rate": pd.Series(dtype="float64")})
        if active:
            start = int(df.time.max()) + 1 if len(df) else 0
            r = _get(f"{FAPI}/fapi/v1/fundingRate", params={"symbol": symbol, "startTime": start, "limit": 1000})
            if r is not None and r.json():
                live = pd.DataFrame(r.json())
                df = pd.concat([df, pd.DataFrame({"time": live.fundingTime.astype("int64"),
                                                   "rate": live.fundingRate.astype("float64")})])
        fpath.parent.mkdir(exist_ok=True)
        df.drop_duplicates("time").sort_values("time").reset_index(drop=True).to_parquet(fpath)


def download_filters() -> None:
    """Current order rules (quantity step, minimum quantity, minimum notional) for both markets."""
    out: dict[str, dict] = {"perp": {}, "spot": {}}
    for market, url in (("perp", f"{FAPI}/fapi/v1/exchangeInfo"), ("spot", "https://api.binance.com/api/v3/exchangeInfo")):
        for s in _get(url).json()["symbols"]:
            f = {x["filterType"]: x for x in s["filters"]}
            mn = f.get("MIN_NOTIONAL", {}).get("notional") or f.get("NOTIONAL", f.get("MIN_NOTIONAL", {})).get("minNotional", 5)
            out[market][s["symbol"]] = {"step": float(f["LOT_SIZE"]["stepSize"]),
                                        "min_qty": float(f["LOT_SIZE"]["minQty"]), "min_notional": float(mn)}
    (DATA / "filters.json").write_text(json.dumps(out))


def coin_perps() -> list[dict]:
    """Every USDT margined coin perpetual in the archive, active or delisted."""
    info = {s["symbol"]: s for s in _get(f"{FAPI}/fapi/v1/exchangeInfo").json()["symbols"]}
    syms = [p.rstrip("/").rsplit("/", 1)[-1] for p in _list("data/futures/um/monthly/klines/", folders=True)]
    return [{"symbol": s, "active": info.get(s, {}).get("status") == "TRADING"}
            for s in sorted(syms) if s.endswith("USDT") and "_" not in s and s not in INDEX_CONTRACTS]


def download_all() -> None:
    """Spot first: a perp without a spot market cannot carry, so its history is skipped."""
    coins = coin_perps()
    (DATA / "coins.json").write_text(json.dumps(coins, indent=1))

    def one(c: dict) -> None:
        if download_spot(c["symbol"]):
            download_perp(c["symbol"], c["active"])

    with ThreadPoolExecutor(3) as pool:
        list(pool.map(one, coins))
    download_filters()


# ---------------------------------------------------------------- daily panel

def bucket_funding(f: pd.DataFrame, k: pd.DataFrame) -> pd.DataFrame:
    """Funding per day bucket d: payments in (d - 1 day, d], valued per contract.

    Binance stamps many payments a few milliseconds after the hour, so times are rounded to the
    minute first; a 00:00:00.002 payment is the midnight payment and belongs to that midnight.
    Each payment is valued at the price in force at that moment: the open of a candle starting
    then, otherwise the last close before it.
    """
    t = (f.time.to_numpy() + 30_000) // 60_000 * 60_000
    kt = k.open_time.to_numpy()
    j = np.clip(np.searchsorted(kt, t, side="right") - 1, 0, len(kt) - 1)
    price = np.where(kt[j] == t, k.open.to_numpy()[j], k.close.to_numpy()[j])
    rate = f.rate.to_numpy()
    df = pd.DataFrame({"rate": rate, "value": rate * price, "positive": rate > 0,
                       "day": -(-t // DAY_MS) * DAY_MS})
    g = df.groupby("day")
    return pd.DataFrame({"rate_sum": g.rate.sum(), "value": g.value.sum(), "payments": g.rate.size(),
                         "positive": g.positive.sum()})


def daily_bars(k: pd.DataFrame, days: np.ndarray) -> pd.DataFrame:
    """Daily open, high, close, median volume and mark from candles that actually traded.

    Binance keeps publishing flat zero volume candles for contracts after delisting, so those are
    dropped. The open is the 00:00 candle's open, or NaN if the market was not trading then. The
    mark is the open, or the last real close carried forward once the market stops.
    """
    k = k[k.quote_volume > 0]
    day = k.open_time // DAY_MS * DAY_MS
    g = k.groupby(day)
    first = g.open_time.min()
    d = pd.DataFrame({"open": g.open.first().where(first == first.index), "high": g.high.max(),
                      "close": g.close.last(), "vol15": g.quote_volume.median(),
                      "quote_volume": g.quote_volume.sum()}).reindex(days)
    d["mark"] = d.open.fillna(d.close.shift(1)).ffill()
    return d


def build_panel(start_ms: int, end_ms: int):
    """Daily panel over every coin perp with a spot market. Rows are 00:00 UTC days in [start, end]."""
    from niru.carry import Panel

    days = np.arange(start_ms, end_ms + 1, DAY_MS)
    filters = json.loads((DATA / "filters.json").read_text())
    names = ["perp_open", "perp_high", "perp_mark", "spot_open", "spot_mark", "rate_sum", "value",
             "payments", "positive", "liq_volume", "valid", "stopped"]
    rules = ["perp_step", "perp_min_qty", "perp_min_notional", "spot_step", "spot_min_qty", "spot_min_notional"]
    cols: dict[str, list] = {k: [] for k in names + rules}
    symbols, mults = [], []
    for c in json.loads((DATA / "coins.json").read_text()):
        perp = c["symbol"]
        spot_sym, mult = spot_pair(perp)
        paths = [DATA / "spot" / f"{spot_sym}.parquet", DATA / "klines" / f"{perp}.parquet",
                 DATA / "funding" / f"{perp}.parquet"]
        if not all(p.exists() for p in paths):
            continue
        k = pd.read_parquet(paths[1])
        perp_d = daily_bars(k, days)
        sp = daily_bars(pd.read_parquet(paths[0]).drop_duplicates("open_time"), days)
        fund = bucket_funding(pd.read_parquet(paths[2]), k).reindex(days)
        liq = np.fmin(perp_d.vol15.rolling(30, min_periods=5).median().shift(1),
                      (sp.quote_volume / 96).rolling(30, min_periods=5).median().shift(1))
        ratio = sp.open.to_numpy() * mult / perp_d.open.to_numpy()
        valid = np.isfinite(ratio) & (np.abs(ratio - 1) < PRICE_TOLERANCE) & np.isfinite(liq.to_numpy())
        if not valid.any():
            continue
        symbols.append(perp)
        mults.append(mult)
        cols["perp_open"].append(perp_d.open.to_numpy())
        cols["perp_high"].append(perp_d.high.to_numpy())
        cols["perp_mark"].append(perp_d["mark"].to_numpy())
        cols["spot_open"].append(sp.open.to_numpy())
        cols["spot_mark"].append(sp["mark"].to_numpy())
        cols["rate_sum"].append(fund.rate_sum.to_numpy())
        cols["value"].append(fund.value.fillna(0).to_numpy())
        cols["payments"].append(fund.payments.fillna(0).to_numpy())
        cols["positive"].append(fund.positive.fillna(0).to_numpy())
        cols["liq_volume"].append(liq.to_numpy())
        cols["valid"].append(valid)
        last_trade = min(perp_d.close.last_valid_index() or 0, sp.close.last_valid_index() or 0)
        cols["stopped"].append(days > last_trade)
        pf = filters["perp"].get(perp, {"step": 0.0, "min_qty": 0.0, "min_notional": 5.0})
        sf = filters["spot"].get(spot_sym, {"step": 0.0, "min_qty": 0.0, "min_notional": 5.0})
        for side, f in (("perp", pf), ("spot", sf)):
            cols[f"{side}_step"].append(f["step"])
            cols[f"{side}_min_qty"].append(f["min_qty"])
            cols[f"{side}_min_notional"].append(f["min_notional"])
    arr = {k: (np.column_stack(v) if k in names else np.array(v)) for k, v in cols.items()}
    return Panel(symbols=symbols, days=days, mult=np.array(mults), **arr)


# ---------------------------------------------------------------- intraday exits

class IntradayPrices:
    """Prices both legs at the first 15 minute candle of a day whose perp high reached the trigger.

    Perp candles come from the local cache. Spot 15 minute candles are fetched per month on first
    use and cached under data/spot15. The fill is that candle's close on both legs, the price a
    bot watching the market would get within the candle. If the same candle also reached the
    liquidation price, the position is treated as liquidated.
    """

    def __init__(self, pn):
        self.pn = pn
        self._perp: dict[str, pd.DataFrame] = {}
        self.spot_missing = 0

    def _perp_day(self, sym: str, day: int) -> pd.DataFrame:
        if sym not in self._perp:
            if len(self._perp) > 40:
                self._perp.clear()
            k = pd.read_parquet(DATA / "klines" / f"{sym}.parquet")
            self._perp[sym] = k[k.quote_volume > 0].set_index("open_time")
        k = self._perp[sym]
        return k[(k.index >= day) & (k.index < day + DAY_MS)]

    def _spot_close(self, spot: str, t: int) -> float | None:
        month = pd.to_datetime(t, unit="ms").strftime("%Y-%m")
        path = DATA / "spot15" / f"{spot}-{month}.parquet"
        if not path.exists():
            r = _get(f"{ARCHIVE}/data/spot/monthly/klines/{spot}/15m/{spot}-15m-{month}.zip")
            if r is None:
                day0 = t // DAY_MS * DAY_MS
                d = _list(f"data/spot/daily/klines/{spot}/15m/{spot}-15m-{pd.to_datetime(day0, unit='ms'):%Y-%m-%d}")
                blobs = _fetch(d)
                df = parse_kline_zip(blobs[0]) if blobs else pd.DataFrame(columns=["open_time", "close"])
            else:
                df = parse_kline_zip(r.content)
            path.parent.mkdir(exist_ok=True)
            df[["open_time", "close"]].to_parquet(path)
        s = pd.read_parquet(path).set_index("open_time").close
        return float(s[t]) if t in s.index else None

    def __call__(self, coin: int, day_i: int, trigger: float, liq: float) -> tuple[str, float, float]:
        sym = self.pn.symbols[coin]
        spot, mult = spot_pair(sym)
        k = self._perp_day(sym, int(self.pn.days[day_i]))
        hit = k[k.high >= min(trigger, liq)]
        row = hit.iloc[0] if len(hit) else k.iloc[-1]
        t = int(hit.index[0] if len(hit) else k.index[-1])
        spot_px = self._spot_close(spot, t)
        if spot_px is None:
            self.spot_missing += 1
            day_ratio = self.pn.spot_open[day_i, coin] * mult / self.pn.perp_open[day_i, coin]
            spot_px = row.close * day_ratio / mult
        if row.high >= liq:
            return "liquidated", liq, spot_px
        return "watchdog", float(row.close), spot_px


if __name__ == "__main__":
    download_all()

"""Daily rule-based screen of the Nifty 500.

Downloads one year of daily prices per stock from Yahoo Finance, applies four
fixed rules, and writes the result to docs/data.json for the static page.

This is a personal screening tool. It lists stocks that meet mechanical rules.
It does not predict prices and is not investment advice.

Standard library only, so the scheduled job needs no dependency install.
"""
from __future__ import annotations

import csv
import io
import json
import math
import statistics
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent
OUT = ROOT / "docs" / "data.json"
SYMBOLS_FILE = ROOT / "symbols.txt"
NSE_LIST = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"
HOSTS = ["query1.finance.yahoo.com", "query2.finance.yahoo.com"]
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
IST = timezone(timedelta(hours=5, minutes=30))
MIN_SYMBOLS = 450  # below this the data source is failing; keep the last good file
ERRORS: dict[str, int] = {}  # why fetches failed, for the job log


def fail(msg: str) -> int:
    """Report a failure so it shows as an annotation on the GitHub run."""
    detail = ", ".join(f"{k} x{v}" for k, v in sorted(ERRORS.items(), key=lambda kv: -kv[1])[:5])
    print(f"::error::{msg}" + (f" Fetch errors: {detail}" if detail else ""))
    return 1


def http_get(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def load_symbols() -> list[str]:
    """Use the bundled list; refresh it from NSE when NSE answers."""
    bundled = SYMBOLS_FILE.read_text().split()
    try:
        text = http_get(NSE_LIST).decode("utf-8", "replace")
        fresh = [row["Symbol"].strip() for row in csv.DictReader(io.StringIO(text)) if row.get("Symbol")]
        fresh = [s for s in fresh if s and not s.startswith("DUMMY")]
        if len(fresh) >= MIN_SYMBOLS:
            if fresh != bundled:
                SYMBOLS_FILE.write_text(" ".join(fresh) + "\n")
            return fresh
    except Exception as e:  # NSE often refuses cloud addresses; the bundled list is fine
        print(f"NSE list not refreshed ({e}); using bundled list", file=sys.stderr)
    return [s for s in bundled if not s.startswith("DUMMY")]


def fetch(symbol: str, ysym: str) -> dict | None:
    """Return computed metrics for one symbol, or None if data is unusable."""
    path = f"/v8/finance/chart/{urllib.parse.quote(ysym)}?range=1y&interval=1d"
    data = None
    last_error = "unknown"
    for attempt in range(4):
        host = HOSTS[attempt % len(HOSTS)]
        try:
            data = json.loads(http_get(f"https://{host}{path}"))
            break
        except Exception as e:
            last_error = f"{type(e).__name__} {getattr(e, 'code', '')}".strip()
            time.sleep(1.5 * (attempt + 1))
    if not data:
        ERRORS[last_error] = ERRORS.get(last_error, 0) + 1
        return None
    try:
        res = data["chart"]["result"][0]
        q = res["indicators"]["quote"][0]
        rows = [
            (t, c, h, l, v or 0)
            for t, c, h, l, v in zip(res["timestamp"], q["close"], q["high"], q["low"], q["volume"])
            if c is not None and h is not None and l is not None
        ]
    except (KeyError, IndexError, TypeError):
        return None
    return metrics(symbol, res.get("meta", {}), rows)


def metrics(symbol: str, meta: dict, rows: list[tuple]) -> dict | None:
    n = len(rows)
    if n < 30:
        return None
    c = [r[1] for r in rows]
    last = rows[-1]

    def ret(k: int) -> float | None:
        return (c[-1] / c[-1 - k] - 1) * 100 if n > k else None

    gains = losses = 0.0
    for i in range(n - 14, n):
        d = c[i] - c[i - 1]
        if d > 0:
            gains += d
        else:
            losses -= d
    rsi = 100 - 100 / (1 + gains / (losses or 1e-9))

    vol = None
    if n > 64:
        rets = [c[i] / c[i - 1] - 1 for i in range(n - 63, n)]
        vol = statistics.pstdev(rets) * math.sqrt(252) * 100

    prior_vol = [r[4] for r in rows[-21:-1]]
    return {
        "s": symbol,
        "name": meta.get("longName") or meta.get("shortName") or symbol,
        "t": meta.get("regularMarketTime") or last[0],
        "c": c[-1],
        "pc": c[-2],
        "h52": max(r[2] for r in rows),
        "l52": min(r[3] for r in rows),
        "d50": sum(c[-50:]) / 50 if n >= 50 else None,
        "d200": sum(c[-200:]) / 200 if n >= 200 else None,
        "v": last[4],
        "av": sum(prior_vol) / len(prior_vol) if prior_vol else 0,
        "r1m": ret(21),
        "r3m": ret(63),
        "r6m": ret(126),
        "h20": max(r[2] for r in rows[-20:]),
        "rsi": rsi,
        "vol": vol,
        "n": n,
        "dh": last[2],
        "dl": last[3],
    }


def rnd(x: float | None, d: int = 1) -> float | None:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    return round(x, d)


def row(r: dict) -> dict:
    return {
        "s": r["s"],
        "n": str(r["name"])[:40],
        "c": rnd(r["c"], 2),
        "day": rnd((r["c"] / r["pc"] - 1) * 100, 2),
        "p50": rnd((r["c"] / r["d50"] - 1) * 100) if r["d50"] else None,
        "p200": rnd((r["c"] / r["d200"] - 1) * 100) if r["d200"] else None,
        "fh": rnd((r["c"] / r["h52"] - 1) * 100),
        "fl": rnd((r["c"] / r["l52"] - 1) * 100),
        "r3m": rnd(r["r3m"]),
        "r6m": rnd(r["r6m"]),
        "vx": rnd(r["v"] / r["av"]) if r["av"] else None,
        "rsi": rnd(r["rsi"], 0),
        "vol": rnd(r["vol"], 0),
    }


def build(R: dict[str, dict], nifty: dict) -> dict:
    """Apply the four rules to the fetched metrics."""
    U = list(R.values())
    full = [r for r in U if r["d200"]]

    traded = sorted(r["av"] * r["c"] for r in U)
    liquid_floor = traded[len(traded) // 2]
    vols = sorted(r["vol"] for r in full if r["vol"] is not None)
    vol_median = vols[len(vols) // 2] if vols else None

    def uptrend(r: dict) -> bool:
        return r["c"] > r["d50"] > r["d200"]

    # 1. Steady uptrend: rising trend, actively traded, smallest price swings first.
    steady = sorted(
        (r for r in full if r["vol"] is not None and uptrend(r) and r["av"] * r["c"] >= liquid_floor),
        key=lambda r: r["vol"],
    )
    # 2. Momentum: rising trend and within 5% of the 52-week high.
    mom = sorted(
        (r for r in full if uptrend(r) and r["c"] >= r["h52"] * 0.95),
        key=lambda r: -(r["r3m"] or 0),
    )
    # 3. Pullback: long-term uptrend, back near the 50-day average after a dip.
    pull = sorted(
        (
            r
            for r in full
            if r["c"] > r["d200"]
            and r["d50"] > r["d200"]
            and abs(r["c"] / r["d50"] - 1) <= 0.03
            and r["c"] <= r["h20"] * 0.95
        ),
        key=lambda r: -(r["r6m"] or 0),
    )
    # 4. Beaten down: near the 52-week low with a low RSI.
    low = sorted(
        (r for r in U if r["n"] >= 200 and r["c"] <= r["l52"] * 1.05 and r["rsi"] < 30),
        key=lambda r: r["rsi"],
    )

    return {
        "asOf": datetime.fromtimestamp(nifty["t"], timezone.utc).isoformat().replace("+00:00", "Z"),
        "nifty": {
            k: rnd(nifty[k], 2) for k in ("c", "pc", "d50", "d200", "h52", "l52", "dh", "dl")
        }
        | {"r1m": rnd(nifty["r1m"]), "r3m": rnd(nifty["r3m"]), "rsi": rnd(nifty["rsi"], 0)},
        "breadth": {
            "n": len(U),
            "a50": sum(1 for r in U if r["d50"] and r["c"] > r["d50"]),
            "n200": len(full),
            "a200": sum(1 for r in full if r["c"] > r["d200"]),
            "adv": sum(1 for r in U if r["c"] > r["pc"]),
            "dec": sum(1 for r in U if r["c"] < r["pc"]),
            "volMed": rnd(vol_median, 0),
        },
        "counts": {"steady": len(steady), "mom": len(mom), "pull": len(pull), "low": len(low)},
        "steady": [row(r) for r in steady[:6]],
        "mom": [row(r) for r in mom[:10]],
        "pull": [row(r) for r in pull[:10]],
        "low": [row(r) for r in low[:10]],
    }


def main() -> int:
    force = "--force" in sys.argv
    symbols = load_symbols()
    print(f"{len(symbols)} symbols")

    nifty = fetch("^NSEI", "^NSEI")
    if not nifty:
        return fail("Could not fetch the Nifty 50; kept the last good file.")
    data_day = datetime.fromtimestamp(nifty["t"], IST).date()
    today = datetime.now(IST).date()
    if data_day != today and not force:
        print(f"Latest market data is from {data_day}, not today ({today}). Market closed; nothing written.")
        return 0

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda s: fetch(s, s + ".NS"), symbols))
    R = {s: r for s, r in zip(symbols, results) if r}
    print(f"{len(R)} of {len(symbols)} fetched")
    if len(R) < MIN_SYMBOLS:
        return fail(f"Only {len(R)} of {len(symbols)} symbols fetched; kept the last good file.")

    doc = build(R, nifty)
    doc["generatedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, separators=(",", ":")) + "\n")
    print(f"Wrote {OUT} ({doc['counts']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

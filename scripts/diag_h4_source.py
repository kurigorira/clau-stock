"""Do the two H4 series agree on the trend?

The H4 trend gate is where the macd edge lives - out-of-sample, turning it
off took the test result from +276 to -243. But the two sides build H4
differently:

    backtest : resamples the H1 CSV into 4-hour buckets
    live     : asks MT5 for the broker's own H4 bars

A US-stock CFD only has H1 bars during its session, so a resampled 4-hour
bucket and a broker H4 bar need not cover the same span. Where they differ,
h4_trend_dir can differ - and the bot then takes entries the backtest would
gate out, which is what the signal reconciliation keeps finding.

This fetches both for each symbol, runs the same h4_trend_dir over each, and
reports how often they disagree on the bars that matter. An agreement rate
near 100% clears the H4 source; anything lower measures how much of the
live/backtest gap it accounts for.

Usage:
    python scripts/diag_h4_source.py --account 1 --limit 20 config/us_fleet/*.yaml
    python scripts/diag_h4_source.py --account 1 --days 30 config/us_fleet/*.yaml
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader import mt5_client  # noqa: E402
from gold_trader.cli_util import expand_paths  # noqa: E402
from gold_trader.config import Config  # noqa: E402
from gold_trader.data import load_csv, resample_ohlcv  # noqa: E402
from gold_trader.mt5_client import MT5Credentials, connect  # noqa: E402
from gold_trader.strategy import add_indicators, h4_trend_dir  # noqa: E402

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def _csv_for(symbol: str) -> Path | None:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", symbol.lower())
    alnum = "".join(c for c in symbol.lower() if c.isalnum())
    for name in (safe, alnum):
        p = DATA_DIR / f"{name}_h1.csv"
        if p.exists():
            return p
    return None


def _dir_series(h4, cfg: Config, since: datetime) -> dict:
    """{bar_time: direction} using the same rule the gate applies live."""
    out = {}
    enriched = add_indicators(h4, cfg)
    for i in range(1, len(enriched)):
        t = enriched.index[i]
        if t < since:
            continue
        out[t] = h4_trend_dir(enriched.iloc[: i + 1], cfg)
    return out


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    p = argparse.ArgumentParser(description="broker H4 vs resampled H4 trend agreement")
    p.add_argument("configs", nargs="+")
    p.add_argument("--account", default=None)
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--limit", type=int, default=20,
                   help="how many symbols to check (default 20; each needs an MT5 fetch)")
    args = p.parse_args()

    load_dotenv()
    cfgs = [Config.from_yaml(x) for x in expand_paths(args.configs)]
    if not cfgs:
        sys.stderr.write("no configs matched\n")
        sys.exit(2)
    cfgs = [c for c in cfgs if _csv_for(c.symbol)][: max(1, args.limit)]
    if not cfgs:
        sys.stderr.write("no symbols have a dumped CSV - run dump_history.py first\n")
        sys.exit(2)

    suffix = f"_{args.account}" if args.account else ""
    try:
        creds = MT5Credentials(
            login=int(os.environ[f"MT5_LOGIN{suffix}"]),
            password=os.environ[f"MT5_PASSWORD{suffix}"],
            server=os.environ[f"MT5_SERVER{suffix}"],
            path=os.environ.get(f"MT5_PATH{suffix}") or None,
        )
    except KeyError as missing:
        sys.stderr.write(f"missing env var {missing}\n")
        sys.exit(2)

    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    agree = disagree = 0
    per_symbol: list[tuple[str, int, int]] = []
    pattern: Counter = Counter()
    bars_broker = bars_resampled = 0

    with connect(creds):
        for cfg in cfgs:
            try:
                broker = mt5_client.fetch_ohlcv(cfg.symbol, "H4", 800)
            except Exception as exc:  # noqa: BLE001
                print(f"  {cfg.symbol}: H4 fetch failed ({exc})")
                continue
            df = load_csv(_csv_for(cfg.symbol))
            resampled = resample_ohlcv(df, "4h")
            bars_broker += len(broker[broker.index >= since])
            bars_resampled += len(resampled[resampled.index >= since])

            a = _dir_series(broker, cfg, since)
            b = _dir_series(resampled, cfg, since)
            shared = sorted(set(a) & set(b))
            ok = sum(1 for t in shared if a[t] == b[t])
            bad = len(shared) - ok
            agree += ok
            disagree += bad
            per_symbol.append((cfg.symbol, ok, bad))
            for t in shared:
                if a[t] != b[t]:
                    pattern[(b[t], a[t])] += 1

    total = agree + disagree
    print(f"H4 source check - {len(per_symbol)} symbols, last {args.days} days")
    print(f"broker H4 bars in window: {bars_broker}   resampled: {bars_resampled}")
    if total == 0:
        print("no overlapping H4 bar times - the two series do not even line up.")
        print("That alone explains a gate that differs live from the backtest.")
        return
    print(f"trend direction agrees on {agree}/{total} shared bars "
          f"({100.0 * agree / total:.1f}%)")
    if pattern:
        print("disagreements (backtest -> live):")
        for (b_dir, a_dir), n in pattern.most_common(6):
            print(f"  {b_dir:+d} -> {a_dir:+d} : {n}")
    worst = sorted(per_symbol, key=lambda r: -r[2])[:8]
    print("worst symbols: " + ", ".join(f"{s}({bad})" for s, _, bad in worst if bad))
    print()
    rate = 100.0 * disagree / total
    if rate < 2:
        print("verdict: the two H4 series agree. The gate is not where live and")
        print("  backtest part company - look elsewhere.")
    else:
        print(f"verdict: the gate disagrees on {rate:.1f}% of bars. The bot is not")
        print("  applying the filter the backtest validated. Either resample H4 from")
        print("  H1 live (reproducing the validation), or re-validate against broker")
        print("  H4 - but the two must be the same series.")


if __name__ == "__main__":
    main()

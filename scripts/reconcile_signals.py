"""Did the live bot take the trades the backtest took?

Runs the fleet's backtest over the live window and matches every signal it
produces against the entries the account actually made. Unlike the payoff
audit this needs no sample size: a live entry with no backtest signal behind
it is a bug at any number of trades, and so is a wholesale disagreement.

The comparison window starts at the first live entry by default, so a bot
that was launched partway through the requested period is not blamed for the
signals that fired before it existed. Pass --since to override.

Usage:
    python scripts/reconcile_signals.py --account 1 --days 30 config/us_fleet/*.yaml
    python scripts/reconcile_signals.py --account 4 --days 30 config/us_fleet_a4/*.yaml
    python scripts/reconcile_signals.py --account 1 --days 30 --since 2026-09-01 \\
        config/us_fleet/*.yaml
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader.backtest import run_backtest  # noqa: E402
from gold_trader.cli_util import expand_paths  # noqa: E402
from gold_trader.config import Config  # noqa: E402
from gold_trader.data import load_csv  # noqa: E402
from gold_trader.mt5_client import MT5Credentials, connect  # noqa: E402
from gold_trader.reconcile import (  # noqa: E402
    LiveEntry,
    Signal,
    format_reconciliation,
    match_signals,
)

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
MIN_BARS = 300
_DEAL_ENTRY_IN = 0


def _csv_for(symbol: str) -> Path | None:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", symbol.lower())
    alnum = "".join(c for c in symbol.lower() if c.isalnum())
    for name in (safe, alnum):
        p = DATA_DIR / f"{name}_h1.csv"
        if p.exists():
            return p
    return None


def _live_entries(creds: MT5Credentials, since: datetime, magics: set[int]):
    """Opening deals belonging to this fleet, as LiveEntry rows.

    Opening deals - not closed trades - so a position still open counts, and
    the comparison is about what the bot DECIDED, not what has resolved.
    """
    with connect(creds) as mt5:
        deals = mt5.history_deals_get(
            since - timedelta(days=1), datetime.now(timezone.utc) + timedelta(hours=1)
        ) or []
    out: list[LiveEntry] = []
    for d in deals:
        if d.entry != _DEAL_ENTRY_IN or not getattr(d, "symbol", ""):
            continue
        if magics and d.magic not in magics:
            continue
        t = datetime.fromtimestamp(d.time, tz=timezone.utc)
        if t < since:
            continue
        out.append(
            LiveEntry(symbol=d.symbol, side="buy" if d.type == 0 else "sell",
                      time=t, magic=d.magic)
        )
    return out


def _backtest_signals(cfgs: list[Config], since: datetime, slippage_bp: float):
    signals: list[Signal] = []
    used, skipped = 0, []
    for cfg in cfgs:
        csv = _csv_for(cfg.symbol)
        if csv is None:
            skipped.append(cfg.symbol)
            continue
        df = load_csv(csv)
        if len(df) < MIN_BARS:
            skipped.append(cfg.symbol)
            continue
        slip = float(df["close"].median()) * slippage_bp / 10_000.0
        res = run_backtest(df, cfg, slippage_price=slip)
        used += 1
        for t in res["trades"]:
            bar_time = t.entry_time.to_pydatetime()
            if bar_time.tzinfo is None:
                bar_time = bar_time.replace(tzinfo=timezone.utc)
            if bar_time >= since:
                signals.append(
                    Signal(symbol=cfg.symbol, side=t.side, bar_time=bar_time)
                )
    return signals, used, skipped


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    p = argparse.ArgumentParser(description="reconcile live entries with backtest signals")
    p.add_argument("configs", nargs="+")
    p.add_argument("--account", default=None, help="env-var suffix (MT5_LOGIN_N ...)")
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--since", default=None,
                   help="ISO date/time (UTC) to start comparing from; default is "
                        "the first live entry found in the window")
    p.add_argument("--slippage-bp", type=float, default=5.0)
    p.add_argument("--slack-bars", type=int, default=1,
                   help="how many bars after the signal bar a fill may land "
                        "(default 1, covering a retry on the next poll)")
    args = p.parse_args()

    load_dotenv()
    paths = expand_paths(args.configs)
    cfgs = [Config.from_yaml(x) for x in paths]
    if not cfgs:
        sys.stderr.write("no configs matched\n")
        sys.exit(2)
    magics = {c.execution.magic_number for c in cfgs}

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

    window_start = datetime.now(timezone.utc) - timedelta(days=args.days)
    live = _live_entries(creds, window_start, magics)
    if not live:
        print(f"no live entries with this fleet's magic numbers in the last "
              f"{args.days} days - nothing to reconcile")
        return

    if args.since:
        since = datetime.fromisoformat(args.since)
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
    else:
        # start where the bot actually started, so signals that fired before it
        # was running are not counted as things it "missed"
        since = min(e.time for e in live).replace(minute=0, second=0, microsecond=0)

    live = [e for e in live if e.time >= since]
    signals, used, skipped = _backtest_signals(cfgs, since, args.slippage_bp)

    print(f"signal reconciliation - account {args.account}")
    print(f"fleet: {len(cfgs)} configs, strategy '{cfgs[0].strategy}'")
    print(f"window: {since:%Y-%m-%d %H:%M} UTC -> now "
          f"({'--since' if args.since else 'first live entry'})")
    print(f"backtest ran on {used}/{len(cfgs)} symbols"
          + (f"; skipped {len(skipped)} without usable data" if skipped else ""))
    print(f"fill allowed {1}-{1 + max(0, args.slack_bars)} bars after the signal bar")
    print()
    print(format_reconciliation(
        match_signals(signals, live, slack_bars=args.slack_bars)
    ))


if __name__ == "__main__":
    main()

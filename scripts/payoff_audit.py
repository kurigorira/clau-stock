"""Why is a backtested strategy losing live: wrong win rate, or wrong payoff?

For each strategy on an account it puts the live shape next to the backtest
shape over the same window - win rate, average win, average loss, payoff
ratio, expectancy, median holding time - and names the gap. PnL units
cancel in every figure, so a backtest in price units compares cleanly with
live results in JPY.

The backtest side needs the fleet's YAMLs and a `data/<symbol>_h1.csv` per
symbol (scripts/dump_history.py writes those). Symbols without a CSV are
skipped and counted, so a thin backtest side is visible rather than silent.

Usage:
    python scripts/payoff_audit.py --account 1 --days 30 config/us_fleet/*.yaml
    python scripts/payoff_audit.py --account 4 --days 30 config/us_fleet_a4/*.yaml
    python scripts/payoff_audit.py --account 1 --days 30 --slippage-bp 5 \\
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

from gold_trader import monthly, payoff, report  # noqa: E402
from gold_trader.backtest import run_backtest  # noqa: E402
from gold_trader.cli_util import expand_paths  # noqa: E402
from gold_trader.config import Config  # noqa: E402
from gold_trader.data import load_csv  # noqa: E402
from gold_trader.mt5_client import MT5Credentials, connect  # noqa: E402

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def _csv_for(symbol: str) -> Path | None:
    """data/<name>_h1.csv for a broker symbol, using dump_history's naming.

    Matching is exact on the sanitised name (dump_history's `_safe_name`) or
    on the alphanumeric reduction of it. Deliberately no fuzzy prefix match:
    silently backtesting a different instrument than the one that traded
    would corrupt the comparison this whole script exists to make.
    """
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", symbol.lower())
    alnum = "".join(c for c in symbol.lower() if c.isalnum())
    for name in (safe, alnum):
        p = DATA_DIR / f"{name}_h1.csv"
        if p.exists():
            return p
    return None


def _print_reason_table(title: str, reasons: dict, decimals: int = 2) -> None:
    """Shared renderer so the live and backtest mixes line up column for column."""
    rows = {k: v for k, v in reasons.items() if v["n"]}
    if not rows:
        return
    total = sum(v["n"] for v in rows.values()) or 1
    print(title)
    print(f"  {'reason':<10} {'trades':>8} {'share':>7} {'win%':>7} "
          f"{'avg pnl':>14} {'avg hold':>10}")
    for k, v in sorted(rows.items(), key=lambda kv: -kv[1]["n"]):
        n = v["n"] or 1
        print(f"  {k:<10} {v['n']:>8} {100.0 * v['n'] / total:>6.0f}% "
              f"{100.0 * v['wins'] / n:>6.1f}% {v['pnl'] / n:>14,.{decimals}f} "
              f"{v['hours'] / n:>9.1f}h")


_DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _print_stop_timing(rows, cfg: Config) -> None:
    """When do live stops actually fire, relative to the trading session?

    The backtest can only see bars inside the session it was dumped for and
    fills every stop at exactly the stop price. A stop that fires outside
    that window - overnight, or on the next open through a gap - is invisible
    to it, which would show up live as both a higher stop rate and stops that
    cost more than the risk they were sized for.
    """
    stops = [t for t in rows if t.exit_reason == "sl" and t.close_time]
    if not stops:
        return
    start, end = cfg.session.start_utc, cfg.session.end_utc
    days = set(cfg.session.trade_days)

    inside, outside = [], []
    for t in stops:
        u = t.close_time.astimezone(timezone.utc)
        in_day = _DAY_NAMES[u.weekday()] in days
        in_hours = start <= u.time() <= end
        (inside if (in_day and in_hours) else outside).append(u)

    print(f"  live stop-outs vs the session window "
          f"({start.strftime('%H:%M')}-{end.strftime('%H:%M')} UTC, "
          f"{'/'.join(sorted(days, key=_DAY_NAMES.index))}):")
    n = len(stops)
    print(f"    inside the window : {len(inside):>3} ({100.0 * len(inside) / n:.0f}%)")
    print(f"    OUTSIDE the window: {len(outside):>3} "
          f"({100.0 * len(outside) / n:.0f}%)")
    if outside:
        hours = sorted({u.strftime('%H:00') for u in outside})
        print(f"    outside-window hours (UTC): {', '.join(hours)}")
        print("    -> these fired when the backtest had no bars at all, so no "
              "amount of re-validating on this data could have predicted them")


def _live_trades(creds: MT5Credentials, days: int, magic_index):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    with connect(creds) as mt5:
        deals = mt5.history_deals_get(
            since, datetime.now(timezone.utc) + timedelta(hours=1)
        ) or []
    trades, _ops = monthly.build_trades(list(deals), magic_index)
    return [t for t in trades if t.close_time.timestamp() >= since.timestamp()]


MIN_BARS = 300  # indicator warm-up plus room for the window itself


def _backtest_shape(cfgs: list[Config], days: int, slippage_bp: float):
    """Pool the backtest trades of every fleet symbol over the recent window.

    The backtest runs on the FULL dumped history and only the trades that
    closed inside the window are counted. Slicing to the window first would
    spend its opening bars warming up the indicators, which on a 30-day
    window of session-limited US-stock bars is most of the sample.
    """
    pnls: list[float] = []
    hours: list[float] = []
    used = 0
    no_csv: list[str] = []
    too_short: list[str] = []
    reasons: dict[str, dict] = {}
    for cfg in cfgs:
        csv = _csv_for(cfg.symbol)
        if csv is None:
            no_csv.append(cfg.symbol)
            continue
        df = load_csv(csv)
        if len(df) < MIN_BARS:
            too_short.append(f"{cfg.symbol}({len(df)})")
            continue
        cutoff = df.index.max() - timedelta(days=days)
        slip = float(df["close"].median()) * slippage_bp / 10_000.0
        res = run_backtest(df, cfg, slippage_price=slip)
        used += 1
        for t in res["trades"]:
            if t.exit_time < cutoff:
                continue
            pnls.append(t.pnl_price)
            # wall-clock hours, matching how live holding time is measured.
            # bars_held would undercount: a US-stock CSV has no overnight
            # bars, so 12 bars can span two calendar days.
            hours.append((t.exit_time - t.entry_time).total_seconds() / 3600.0)
            # tallied here rather than from res["exit_reasons"], which covers
            # the whole file - these must describe the same window as the stats
            slot = reasons.setdefault(
                t.reason, {"n": 0, "pnl": 0.0, "wins": 0, "hours": 0.0}
            )
            slot["n"] += 1
            slot["pnl"] += t.pnl_price
            slot["wins"] += 1 if t.pnl_price > 0 else 0
            slot["hours"] += (t.exit_time - t.entry_time).total_seconds() / 3600.0
    return payoff.stats_from_pnls(pnls, hours), used, no_csv, too_short, reasons


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    p = argparse.ArgumentParser(description="live vs backtest payoff audit")
    p.add_argument("configs", nargs="+", help="fleet YAMLs (globs are expanded here)")
    p.add_argument("--account", default=None, help="env-var suffix (MT5_LOGIN_N ...)")
    p.add_argument("--days", type=int, default=30, help="window, days back (default 30)")
    p.add_argument("--slippage-bp", type=float, default=5.0,
                   help="per-side cost charged to the BACKTEST, in bp of price "
                        "(default 5 - the figure the fleet was validated at)")
    p.add_argument("--no-backtest", action="store_true",
                   help="live figures only; skips the CSV requirement")
    args = p.parse_args()

    load_dotenv()
    paths = expand_paths(args.configs)
    cfgs = [Config.from_yaml(x) for x in paths]
    if not cfgs:
        sys.stderr.write("no configs matched\n")
        sys.exit(2)

    repo_root = Path(__file__).resolve().parents[1]
    magic_index = report.load_magic_index(repo_root / "config")
    for d in sorted({Path(x).parent for x in paths}):
        magic_index.update(report.load_magic_index(d))

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

    trades = _live_trades(creds, args.days, magic_index)
    if not trades:
        print(f"no closed trades on account {args.account} in the last {args.days} days")
        return

    by_strategy: dict[str, list] = {}
    for t in trades:
        by_strategy.setdefault(t.strategy, []).append(t)

    fleet_strategy = cfgs[0].strategy
    back, used, no_csv, too_short, reasons = (None, 0, [], [], {})
    if not args.no_backtest:
        back, used, no_csv, too_short, reasons = _backtest_shape(
            cfgs, args.days, args.slippage_bp
        )

    print(f"payoff audit - account {args.account} - last {args.days} days")
    print(f"fleet: {len(cfgs)} configs, strategy '{fleet_strategy}', "
          f"backtest cost {args.slippage_bp:g}bp/side")
    coverage = 100.0 * used / len(cfgs)
    if not args.no_backtest:
        print(f"backtest ran on {used}/{len(cfgs)} symbols ({coverage:.0f}% coverage)")
        if no_csv:
            print(f"  no data/*_h1.csv: {len(no_csv)} "
                  f"({', '.join(no_csv[:8])}{' ...' if len(no_csv) > 8 else ''})")
        if too_short:
            print(f"  CSV shorter than {MIN_BARS} bars: {len(too_short)} "
                  f"({', '.join(too_short[:8])}{' ...' if len(too_short) > 8 else ''})")
        if used == 0:
            print("  -> nothing to compare against. Dump history first:")
            print("     python scripts/dump_history.py --account "
                  f"{args.account} --months 6 {' '.join(args.configs)}")
        elif coverage < 60.0:
            print("  -> WARNING: the backtest column is built from a minority of "
                  "the fleet and is NOT a valid baseline for the live column.")
            print("     Dump the missing symbols before drawing any conclusion:")
            print("     python scripts/dump_history.py --account "
                  f"{args.account} --months 6 {' '.join(args.configs)}")
    print()

    for name in sorted(by_strategy, key=lambda k: -len(by_strategy[k])):
        rows = by_strategy[name]
        live = payoff.stats_from_pnls(
            [t.net for t in rows],
            [t.hours_held for t in rows if t.hours_held is not None],
        )
        # only the fleet's own strategy has a backtest to compare against, and
        # only when enough of the fleet actually produced one
        pair = (
            back
            if (back and back.n and name == fleet_strategy and coverage >= 60.0)
            else None
        )
        print(payoff.format_block(f"{name} (account {args.account})", live, pair))
        _print_reason_table(
            f"  live exits, by reason ({name}):",
            {
                r: {
                    "n": len([t for t in rows if t.exit_reason == r]),
                    "pnl": sum(t.net for t in rows if t.exit_reason == r),
                    "wins": len([t for t in rows if t.exit_reason == r and t.net > 0]),
                    "hours": sum(
                        t.hours_held or 0.0 for t in rows if t.exit_reason == r
                    ),
                }
                for r in sorted({t.exit_reason for t in rows})
            },
        )
        if name == fleet_strategy:
            _print_stop_timing(rows, cfgs[0])
        print()

    if reasons:
        _print_reason_table("backtest exits, by reason:", reasons, decimals=4)
        print("  'sl' = stopped out, 'channel'/'expert' = the strategy's own exit "
              "signal, 'tp' = take profit.")
        print("  Compare the SHARE of 'sl' above with the live table: a live stop "
              "rate well over the backtest's is what turns a backtested win rate "
              "into a live one half its size.")


if __name__ == "__main__":
    main()

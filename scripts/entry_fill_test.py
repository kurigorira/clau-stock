"""Does the edge survive the price the bot can actually get?

Every backtest in this repo assumes an entry fills at the close of the bar
that produced the signal. The live bot cannot do that: it only sees the bar
once the bar has closed, then sends a market order, so it fills at the next
bar's open. The stop is anchored to the signal bar's close either way - so a
worse fill does not move the stop, it just leaves less room in front of it.

That single difference would raise the stop rate and shrink the winners at
the same time, which is exactly the shape of the live/backtest gap the payoff
audit found (stops 40% live vs 22% on paper, signal exits worth 0.14 of a
stop live vs 0.56 on paper).

This runs the same fleet both ways and prints the difference. It settles what
no amount of re-validating on the old assumption could:

    edge gone at next_open   -> the strategy was never reachable; the same
                                question applies to every other strategy
                                validated under the close-fill assumption
    edge survives            -> the fill is not the culprit; look at the
                                stop-distance guard and per-trade costs

Usage:
    python scripts/entry_fill_test.py config/us_fleet/*.yaml
    python scripts/entry_fill_test.py --slippage-bp 5 config/us_fleet_a4/*.yaml
    python scripts/entry_fill_test.py --months 6 config/us_fleet/*.yaml
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader import payoff  # noqa: E402
from gold_trader.backtest import run_backtest  # noqa: E402
from gold_trader.cli_util import expand_paths  # noqa: E402
from gold_trader.config import Config  # noqa: E402
from gold_trader.data import load_csv  # noqa: E402

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
MIN_BARS = 300


def _csv_for(symbol: str) -> Path | None:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", symbol.lower())
    alnum = "".join(c for c in symbol.lower() if c.isalnum())
    for name in (safe, alnum):
        p = DATA_DIR / f"{name}_h1.csv"
        if p.exists():
            return p
    return None


def _run(cfgs, months: int, slippage_bp: float, entry_fill: str):
    """Pool every fleet symbol's trades under one fill assumption."""
    pnls: list[float] = []
    hours: list[float] = []
    reasons: dict[str, int] = {}
    used = 0
    for cfg in cfgs:
        csv = _csv_for(cfg.symbol)
        if csv is None:
            continue
        df = load_csv(csv)
        if len(df) < MIN_BARS:
            continue
        if months > 0:
            df = df[df.index >= df.index.max() - timedelta(days=months * 30)]
            if len(df) < MIN_BARS:
                continue
        slip = float(df["close"].median()) * slippage_bp / 10_000.0
        res = run_backtest(df, cfg, slippage_price=slip, entry_fill=entry_fill)
        used += 1
        for t in res["trades"]:
            pnls.append(t.pnl_price)
            hours.append((t.exit_time - t.entry_time).total_seconds() / 3600.0)
            reasons[t.reason] = reasons.get(t.reason, 0) + 1
    return payoff.stats_from_pnls(pnls, hours), used, reasons


def _row(label: str, a: float, b: float, fmt: str = "{:,.4f}") -> str:
    delta = b - a
    return (f"  {label:<20} {fmt.format(a):>14} {fmt.format(b):>14} "
            f"{fmt.format(delta):>14}")


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    p = argparse.ArgumentParser(description="close-fill vs next-open-fill backtest")
    p.add_argument("configs", nargs="+")
    p.add_argument("--slippage-bp", type=float, default=5.0,
                   help="per-side cost in bp of price, charged to both runs (default 5)")
    p.add_argument("--months", type=int, default=0,
                   help="limit to the last N months of each CSV (0 = all history)")
    args = p.parse_args()

    cfgs = [Config.from_yaml(x) for x in expand_paths(args.configs)]
    if not cfgs:
        sys.stderr.write("no configs matched\n")
        sys.exit(2)

    close_s, used, close_r = _run(cfgs, args.months, args.slippage_bp, "close")
    open_s, _, open_r = _run(cfgs, args.months, args.slippage_bp, "next_open")

    print(f"entry-fill test - {len(cfgs)} configs, strategy '{cfgs[0].strategy}'")
    print(f"backtest ran on {used}/{len(cfgs)} symbols, {args.slippage_bp:g}bp/side"
          + (f", last {args.months} months" if args.months else ", full history"))
    if used == 0:
        print("no usable data/*_h1.csv - run scripts/dump_history.py first")
        sys.exit(2)
    print()
    print(f"  {'':<20} {'close fill':>14} {'next open':>14} {'difference':>14}")
    print(_row("trades", close_s.n, open_s.n, "{:,.0f}"))
    print(_row("win rate %", close_s.win_rate * 100, open_s.win_rate * 100, "{:,.1f}"))
    print(_row("avg win", close_s.avg_win, open_s.avg_win))
    print(_row("avg loss", close_s.avg_loss, open_s.avg_loss))
    print(_row("payoff ratio", close_s.payoff_ratio, open_s.payoff_ratio, "{:,.2f}"))
    print(_row("expectancy/trade", close_s.expectancy, open_s.expectancy))
    print(_row("total pnl", close_s.total, open_s.total, "{:,.1f}"))
    print()

    for label, r, total in (("close fill", close_r, close_s.n),
                            ("next open ", open_r, open_s.n)):
        n = total or 1
        parts = ", ".join(f"{k} {v} ({100.0 * v / n:.0f}%)"
                          for k, v in sorted(r.items(), key=lambda kv: -kv[1]))
        print(f"  exits, {label}: {parts}")
    print()

    print("verdict:")
    if close_s.n == 0 or open_s.n == 0:
        print("  one side produced no trades - nothing to compare")
    elif close_s.expectancy > 0 and open_s.expectancy <= 0:
        print("  the edge exists ONLY at a fill the bot cannot get. Every result")
        print("  validated under the close-fill assumption - macd, bollrci and the")
        print("  retired fibonacci/donchian fleets alike - is overstated by this")
        print("  same gap, and this strategy should not be judged on those numbers.")
    elif open_s.expectancy > 0:
        keep = 100.0 * open_s.expectancy / close_s.expectancy if close_s.expectancy else 0.0
        print(f"  the edge survives the realistic fill, keeping {keep:.0f}% of its")
        print("  expectancy. The fill is not what the live results are missing -")
        print("  look at risk.min_stop_fraction and per-trade costs instead.")
    else:
        print("  the strategy loses under BOTH fills, so the fill assumption is not")
        print("  what made it look viable. Whatever validated it, re-examine that.")


if __name__ == "__main__":
    main()

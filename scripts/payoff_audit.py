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
    """data/<slug>_h1.csv for a broker symbol name, if it was dumped."""
    slug = "".join(c for c in symbol.lower() if c.isalnum())
    for p in (DATA_DIR / f"{slug}_h1.csv", DATA_DIR / f"{symbol.lower()}_h1.csv"):
        if p.exists():
            return p
    # fall back to a loose match so BTCUSD / btc_usd style names still hit
    for p in DATA_DIR.glob("*_h1.csv"):
        if "".join(c for c in p.stem.lower() if c.isalnum()).startswith(slug):
            return p
    return None


def _live_trades(creds: MT5Credentials, days: int, magic_index):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    with connect(creds) as mt5:
        deals = mt5.history_deals_get(
            since, datetime.now(timezone.utc) + timedelta(hours=1)
        ) or []
    trades, _ops = monthly.build_trades(list(deals), magic_index)
    return [t for t in trades if t.close_time.timestamp() >= since.timestamp()]


def _backtest_shape(cfgs: list[Config], days: int, slippage_bp: float):
    """Pool the backtest trades of every fleet symbol over the recent window."""
    pnls: list[float] = []
    hours: list[float] = []
    used, missing = 0, []
    reasons: dict[str, int] = {}
    for cfg in cfgs:
        csv = _csv_for(cfg.symbol)
        if csv is None:
            missing.append(cfg.symbol)
            continue
        df = load_csv(csv)
        cutoff = df.index.max() - timedelta(days=days)
        window = df[df.index >= cutoff]
        if len(window) < 200:            # not enough bars for indicators + trades
            missing.append(cfg.symbol)
            continue
        slip = float(window["close"].median()) * slippage_bp / 10_000.0
        res = run_backtest(window, cfg, slippage_price=slip)
        used += 1
        for t in res["trades"]:
            pnls.append(t.pnl_price)
            hours.append(float(t.bars_held))   # H1 bars -> hours
        # exit_reason_breakdown returns per-reason aggregates, not counts:
        # {'sl': {'n':.., 'pnl':.., 'win_rate':.., 'avg_bars_held':..}, ...}
        for k, agg in (res.get("exit_reasons") or {}).items():
            slot = reasons.setdefault(k, {"n": 0, "pnl": 0.0, "wins": 0, "bars": 0.0})
            slot["n"] += agg["n"]
            slot["pnl"] += agg["pnl"]
            slot["wins"] += round(agg["win_rate"] * agg["n"])
            slot["bars"] += agg["avg_bars_held"] * agg["n"]
    return payoff.stats_from_pnls(pnls, hours), used, missing, reasons


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
    back, used, missing, reasons = (None, 0, [], {})
    if not args.no_backtest:
        back, used, missing, reasons = _backtest_shape(cfgs, args.days, args.slippage_bp)

    print(f"payoff audit - account {args.account} - last {args.days} days")
    print(f"fleet: {len(cfgs)} configs, strategy '{fleet_strategy}', "
          f"backtest cost {args.slippage_bp:g}bp/side")
    if not args.no_backtest:
        print(f"backtest ran on {used}/{len(cfgs)} symbols"
              + (f"; no usable data/*_h1.csv for {len(missing)} "
                 f"({', '.join(missing[:8])}{' ...' if len(missing) > 8 else ''})"
                 if missing else ""))
        if used == 0:
            print("  -> nothing to compare against. Dump history first:")
            print("     python scripts/dump_history.py --account "
                  f"{args.account} {' '.join(args.configs)}")
    print()

    for name in sorted(by_strategy, key=lambda k: -len(by_strategy[k])):
        rows = by_strategy[name]
        live = payoff.stats_from_pnls(
            [t.net for t in rows],
            [t.hours_held for t in rows if t.hours_held is not None],
        )
        # only the fleet's own strategy has a backtest to compare against
        pair = back if (back and back.n and name == fleet_strategy) else None
        print(payoff.format_block(f"{name} (account {args.account})", live, pair))
        print()

    if reasons:
        total = sum(v["n"] for v in reasons.values()) or 1
        print("backtest exits, by reason:")
        print(f"  {'reason':<10} {'trades':>8} {'share':>7} {'win%':>7} "
              f"{'avg pnl':>12} {'avg hold':>10}")
        for k, v in sorted(reasons.items(), key=lambda kv: -kv[1]["n"]):
            n = v["n"] or 1
            print(f"  {k:<10} {v['n']:>8} {100.0 * v['n'] / total:>6.0f}% "
                  f"{100.0 * v['wins'] / n:>6.1f}% {v['pnl'] / n:>12.4f} "
                  f"{v['bars'] / n:>9.1f}h")
        print("  'sl' = stopped out, 'channel' = the strategy's own exit signal, "
              "'tp' = take profit.")
        print("  If the backtest's winners come from long 'channel' holds but "
              "live holds are short, the exit is firing earlier live than on paper.")


if __name__ == "__main__":
    main()

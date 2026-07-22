"""A/B test: does the stochastic gate improve a strategy's win rate, fleet-wide?

For every data/<symbol>_h1.csv this runs the chosen strategy twice on identical
data — once with stoch.use=false (base) and once with stoch.use=true — and
prints win-rate and PnL side by side, then an aggregate verdict.

The stochastic gate rejects longs whose %K is already overbought and shorts
whose %K is already oversold (see StochConfig). Interpretation per strategy:
donchian skips breakouts firing into overbought; fibonacci skips shallow
pullbacks whose oscillator never came down; macd skips late zero-crosses. The
hypothesis under test: "waiting for room to run lifts win rate." The AGGREGATE
row answers it — a single symbol proves nothing.

Base params come from the matching fib_<slug>.yaml (so ATR%/ADX filters match
the main comparison), then strategy is forced to --strategy. Thresholds are
tunable so you can sweep the gate.

Usage:
    python scripts/ab_stoch.py                          # donchian, all data
    python scripts/ab_stoch.py --strategy fibonacci     # fib base vs +stoch
    python scripts/ab_stoch.py --strategy macd
    python scripts/ab_stoch.py --overbought 70 --oversold 30
    python scripts/ab_stoch.py --strategy fibonacci data/xauusd_h1.csv
"""
from __future__ import annotations

import argparse
import copy
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader.backtest import run_backtest  # noqa: E402
from gold_trader.config import Config  # noqa: E402
from gold_trader.data import load_csv  # noqa: E402

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def _config_for_csv(csv_path: Path) -> Path | None:
    slug = re.sub(r"[^a-z0-9]", "_", csv_path.stem.removesuffix("_h1").lower())
    candidate = CONFIG_DIR / f"fib_{slug}.yaml"
    return candidate if candidate.exists() else None


def _base_cfg(csv_path: Path, args) -> Config:
    matched = _config_for_csv(csv_path)
    cfg = Config.from_yaml(matched) if matched else Config()
    cfg.strategy = args.strategy
    cfg.stoch.overbought = args.overbought
    cfg.stoch.oversold = args.oversold
    return cfg


def main() -> None:
    p = argparse.ArgumentParser(description="stochastic-gate A/B for any strategy")
    p.add_argument("--strategy", default="donchian",
                   choices=("donchian", "fibonacci", "macd"))
    p.add_argument("--data-dir", default="data")
    p.add_argument("--overbought", type=float, default=80.0)
    p.add_argument("--oversold", type=float, default=20.0)
    p.add_argument("csvs", nargs="*", help="explicit CSVs (default: data/*_h1.csv)")
    args = p.parse_args()

    csvs = [Path(x) for x in args.csvs] or sorted(Path(args.data_dir).glob("*_h1.csv"))
    if not csvs:
        sys.stderr.write(f"no CSVs in {args.data_dir}/ — run dump_history.py first\n")
        sys.exit(2)

    hdr = (
        f"{'symbol':<14} | {'n':>4} {'win%':>6} {'pnl':>11}  (base) | "
        f"{'n':>4} {'win%':>6} {'pnl':>11}  (stoch) | {'Δwin':>6} {'Δpnl':>11}"
    )
    print(f"# {args.strategy} stochastic-gate A/B  "
          f"(OB={args.overbought:g}/OS={args.oversold:g})")
    print(hdr)
    print("-" * len(hdr))

    # trade-weighted win-rate accumulators + symbol win/loss tallies
    base_wins = base_n = stoch_wins = stoch_n = 0
    base_pnl = stoch_pnl = 0.0
    win_improved = win_worse = 0
    for csv_path in csvs:
        symbol = csv_path.stem.replace("_h1", "")
        df = load_csv(csv_path)
        base = copy.deepcopy(_base_cfg(csv_path, args)); base.stoch.use = False
        stoch = copy.deepcopy(_base_cfg(csv_path, args)); stoch.stoch.use = True
        try:
            rb = run_backtest(df, base)
            rs = run_backtest(df, stoch)
        except Exception as exc:  # noqa: BLE001
            print(f"{symbol:<14} | ERROR: {exc}")
            continue
        dwin = rs["win_rate"] - rb["win_rate"]
        dpnl = rs["total_pnl_price"] - rb["total_pnl_price"]
        print(
            f"{symbol:<14} | {rb['n']:>4} {rb['win_rate']:>6.1%} "
            f"{rb['total_pnl_price']:>11.2f}  (base) | "
            f"{rs['n']:>4} {rs['win_rate']:>6.1%} "
            f"{rs['total_pnl_price']:>11.2f}  (stoch) | "
            f"{dwin:>+6.1%} {dpnl:>+11.2f}"
        )
        base_wins += round(rb["win_rate"] * rb["n"]); base_n += rb["n"]
        stoch_wins += round(rs["win_rate"] * rs["n"]); stoch_n += rs["n"]
        base_pnl += rb["total_pnl_price"]; stoch_pnl += rs["total_pnl_price"]
        if rb["n"] and rs["n"]:
            win_improved += dwin > 0
            win_worse += dwin < 0

    bw = base_wins / base_n if base_n else 0.0
    sw = stoch_wins / stoch_n if stoch_n else 0.0
    print("-" * len(hdr))
    print(
        f"{'AGGREGATE':<14} | {base_n:>4} {bw:>6.1%} {base_pnl:>11.2f}  (base) | "
        f"{stoch_n:>4} {sw:>6.1%} {stoch_pnl:>11.2f}  (stoch) | "
        f"{sw - bw:>+6.1%} {stoch_pnl - base_pnl:>+11.2f}"
    )
    print(
        f"# trade-weighted win rate {bw:.1%} -> {sw:.1%}; "
        f"symbols where stoch lifted win% : {win_improved}, hurt : {win_worse}; "
        f"total trades {base_n} -> {stoch_n}"
    )


if __name__ == "__main__":
    main()

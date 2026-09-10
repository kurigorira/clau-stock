"""A/B test: does the regression-trendline gate improve a strategy, fleet-wide?

For every data/<symbol>_h1.csv this runs the chosen strategy twice on identical
data — trendline.use=false (base) vs true — and prints win-rate and PnL side by
side, then an aggregate verdict.

The gate fits a straight line to the last `length` closes and admits a long
only when that line rises (fractional slope/bar > slope_min) and fits cleanly
(R² >= r2_min); mirror-image for a short. The distinctive knob is r2_min: it
demands price is actually *tracking a line*, not merely pointed the right way —
something plain EMA slope can't say. The hypothesis: "only trade clean trends."

Base params come from the matching fib_<slug>.yaml (so ATR%/ADX filters match
the main comparison), then strategy is forced to --strategy.

Usage:
    python scripts/ab_trendline.py                          # donchian, all data
    python scripts/ab_trendline.py --strategy fibonacci
    python scripts/ab_trendline.py --strategy macd --length 40
    python scripts/ab_trendline.py --r2-min 0.6 --slope-min 0.0005
    python scripts/ab_trendline.py --sweep-r2 0,0.3,0.5,0.7,0.9   # R² curve
    python scripts/ab_trendline.py --strategy fibonacci data/xauusd_h1.csv
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
    cfg.trendline.length = args.length
    cfg.trendline.slope_min = args.slope_min
    cfg.trendline.r2_min = args.r2_min
    return cfg


def _aggregate(csvs, args, r2_min: float, use: bool):
    """Run every CSV once and return (n, trade-weighted win rate, total PnL)."""
    wins = n = 0
    pnl = 0.0
    for csv_path in csvs:
        cfg = _base_cfg(csv_path, args)
        cfg.trendline.r2_min = r2_min
        cfg.trendline.use = use
        try:
            r = run_backtest(load_csv(csv_path), cfg)
        except Exception:  # noqa: BLE001
            continue
        wins += round(r["win_rate"] * r["n"]); n += r["n"]
        pnl += r["total_pnl_price"]
    return n, (wins / n if n else 0.0), pnl


def _run_sweep(csvs, args) -> None:
    """Base once, then one AGGREGATE row per --sweep-r2 threshold, so the
    win% / PnL trade-off across fit-quality tightness is one readable curve."""
    thresholds = [float(x) for x in args.sweep_r2.split(",") if x.strip()]
    bn, bw, bp = _aggregate(csvs, args, args.r2_min, use=False)
    print(f"# {args.strategy} trendline-gate SWEEP over r2_min  "
          f"(length={args.length}, slope_min={args.slope_min:g}; base = no gate)")
    hdr = f"{'r2_min':>7} | {'n':>5} {'win%':>6} {'pnl':>12} | {'Δn':>5} {'Δwin':>6} {'Δpnl':>12}"
    print(hdr)
    print("-" * len(hdr))
    print(f"{'base':>7} | {bn:>5} {bw:>6.1%} {bp:>12.2f} | {'':>5} {'':>6} {'':>12}")
    for r2 in thresholds:
        n, w, p = _aggregate(csvs, args, r2, use=True)
        print(
            f"{r2:>7g} | {n:>5} {w:>6.1%} {p:>12.2f} | "
            f"{n - bn:>+5} {w - bw:>+6.1%} {p - bp:>+12.2f}"
        )


def main() -> None:
    p = argparse.ArgumentParser(description="regression-trendline-gate A/B")
    p.add_argument("--strategy", default="donchian",
                   choices=("donchian", "fibonacci", "macd"))
    p.add_argument("--data-dir", default="data")
    p.add_argument("--length", type=int, default=50, help="regression window (bars)")
    p.add_argument("--slope-min", type=float, default=0.0,
                   help="required |fractional slope per bar| (0 = any direction)")
    p.add_argument("--r2-min", type=float, default=0.0,
                   help="required regression R^2 in [0,1] (0 = ignore fit quality)")
    p.add_argument("--sweep-r2", default=None,
                   help="comma list of r2_min thresholds, e.g. '0,0.3,0.5,0.7,0.9'; "
                        "one AGGREGATE row each (a win%%/PnL curve).")
    p.add_argument("csvs", nargs="*", help="explicit CSVs (default: data/*_h1.csv)")
    args = p.parse_args()

    csvs = [Path(x) for x in args.csvs] or sorted(Path(args.data_dir).glob("*_h1.csv"))
    if not csvs:
        sys.stderr.write(f"no CSVs in {args.data_dir}/ — run dump_history.py first\n")
        sys.exit(2)

    if args.sweep_r2 is not None:
        _run_sweep(csvs, args)
        return

    hdr = (
        f"{'symbol':<14} | {'n':>4} {'win%':>6} {'pnl':>11}  (base) | "
        f"{'n':>4} {'win%':>6} {'pnl':>11}  (trend) | {'Δwin':>6} {'Δpnl':>11}"
    )
    print(f"# {args.strategy} trendline-gate A/B  "
          f"(length={args.length}, r2_min={args.r2_min:g}, slope_min={args.slope_min:g})")
    print(hdr)
    print("-" * len(hdr))

    base_wins = base_n = t_wins = t_n = 0
    base_pnl = t_pnl = 0.0
    win_improved = win_worse = 0
    for csv_path in csvs:
        symbol = csv_path.stem.replace("_h1", "")
        df = load_csv(csv_path)
        base = copy.deepcopy(_base_cfg(csv_path, args)); base.trendline.use = False
        trend = copy.deepcopy(_base_cfg(csv_path, args)); trend.trendline.use = True
        try:
            rb = run_backtest(df, base)
            rt = run_backtest(df, trend)
        except Exception as exc:  # noqa: BLE001
            print(f"{symbol:<14} | ERROR: {exc}")
            continue
        dwin = rt["win_rate"] - rb["win_rate"]
        dpnl = rt["total_pnl_price"] - rb["total_pnl_price"]
        print(
            f"{symbol:<14} | {rb['n']:>4} {rb['win_rate']:>6.1%} "
            f"{rb['total_pnl_price']:>11.2f}  (base) | "
            f"{rt['n']:>4} {rt['win_rate']:>6.1%} "
            f"{rt['total_pnl_price']:>11.2f}  (trend) | "
            f"{dwin:>+6.1%} {dpnl:>+11.2f}"
        )
        base_wins += round(rb["win_rate"] * rb["n"]); base_n += rb["n"]
        t_wins += round(rt["win_rate"] * rt["n"]); t_n += rt["n"]
        base_pnl += rb["total_pnl_price"]; t_pnl += rt["total_pnl_price"]
        if rb["n"] and rt["n"]:
            win_improved += dwin > 0
            win_worse += dwin < 0

    bw = base_wins / base_n if base_n else 0.0
    tw = t_wins / t_n if t_n else 0.0
    print("-" * len(hdr))
    print(
        f"{'AGGREGATE':<14} | {base_n:>4} {bw:>6.1%} {base_pnl:>11.2f}  (base) | "
        f"{t_n:>4} {tw:>6.1%} {t_pnl:>11.2f}  (trend) | "
        f"{tw - bw:>+6.1%} {t_pnl - base_pnl:>+11.2f}"
    )
    print(
        f"# trade-weighted win rate {bw:.1%} -> {tw:.1%}; "
        f"symbols where trendline lifted win% : {win_improved}, hurt : {win_worse}; "
        f"total trades {base_n} -> {t_n}"
    )


if __name__ == "__main__":
    main()

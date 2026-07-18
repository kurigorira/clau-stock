"""Sweep one strategy parameter, pooling trades across the fleet's symbols.

Reads data/*_h1.csv (from dump_history.py), pools every symbol that runs the
chosen strategy, and prints a train/test table so you can see whether a
parameter change survives out-of-sample. Only adopt a value that improves
BOTH the train and test PF - a train-only gain is overfitting.

Tune at the strategy level (one value for all fib symbols, or all donchian
symbols); do not tune per symbol - single symbols have too few trades.

Usage:
    # sweep the fib retrace floor across all fib-strategy CSVs
    python scripts/sweep_params.py --strategy fibonacci \\
        --param fibonacci.retrace_min --values 0.382,0.5,0.618

    # sweep the donchian stop multiple; restrict to specific CSVs
    python scripts/sweep_params.py --strategy donchian \\
        --param risk.atr_stop_mult --values 2.0,2.5,3.0 \\
        data/xauusd_h1.csv data/usdcad_h1.csv

Note --values is a single COMMA-separated list (not space-separated), so
trailing CSV paths can't be swallowed by the value list.

Without positional CSVs it uses every data/*_h1.csv whose matching preset
(config/fib_<slug>.yaml) declares the chosen strategy.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader.config import Config  # noqa: E402
from gold_trader.data import load_csv  # noqa: E402
from gold_trader.sweep import sweep_param  # noqa: E402

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def _preset_for(csv_path: Path) -> Path | None:
    slug = re.sub(r"[^a-z0-9]", "_", csv_path.stem.removesuffix("_h1").lower())
    p = CONFIG_DIR / f"fib_{slug}.yaml"
    return p if p.exists() else None


def main() -> None:
    parser = argparse.ArgumentParser(description="pooled parameter sweep")
    parser.add_argument("--strategy", required=True, choices=["donchian", "fibonacci"])
    parser.add_argument("--param", required=True, help="dotted path, e.g. fibonacci.retrace_min")
    parser.add_argument("--values", required=True,
                        help="comma-separated values to try, e.g. 2.0,2.5,3.0")
    parser.add_argument("--split", type=float, default=0.7)
    parser.add_argument("--base-config", default=None,
                        help="preset whose filters/params seed the sweep "
                             "(default: loosened Config so FX isn't filtered out)")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("csvs", nargs="*", help="explicit CSVs (default: strategy-matched)")
    args = parser.parse_args()

    csvs = [Path(p) for p in args.csvs] or sorted(Path(args.data_dir).glob("*_h1.csv"))
    frames: dict = {}
    for csv_path in csvs:
        preset = _preset_for(csv_path)
        # if there's a matching preset, only include it when its strategy matches;
        # explicit CSVs with no preset are always included
        if preset is not None and Config.from_yaml(preset).strategy != args.strategy and not args.csvs:
            continue
        frames[csv_path.stem] = load_csv(csv_path)

    if not frames:
        sys.stderr.write("no CSVs matched - run dump_history.py or pass CSV paths\n")
        sys.exit(2)

    # numeric coercion happens inside set_param based on the field type
    values = [v.strip() for v in args.values.split(",") if v.strip()]
    if args.base_config:
        base = Config.from_yaml(args.base_config)
    else:
        # default filters (atr_pct_min 0.3%) block most FX; widen the band so
        # the sweep sees trades regardless of asset class. Override with
        # --base-config to sweep against a specific preset's filters.
        base = Config()
        base.filters.atr_pct_min = 0.0003
        base.filters.atr_pct_max = 0.10
    print(f"sweeping {args.param} over {values}")
    print(f"strategy={args.strategy}, pooled over {len(frames)} symbols, split={args.split}\n")

    scores = sweep_param(frames, base, args.param, values, strategy=args.strategy, split_ratio=args.split)

    hdr = f"{'value':>10} | {'trainPF':>7} {'n':>5} {'trainPnL':>10} | {'testPF':>7} {'n':>5} {'testPnL':>10}"
    print(hdr)
    print("-" * len(hdr))
    best = max(scores, key=lambda s: s.test_pf) if scores else None
    for s in scores:
        star = "  <- best test PF" if s is best else ""
        print(
            f"{str(s.value):>10} | {s.train_pf:>7.2f} {s.train_n:>5} {s.train_pnl:>10.2f} | "
            f"{s.test_pf:>7.2f} {s.test_n:>5} {s.test_pnl:>10.2f}{star}"
        )
    print("\nadopt a value only if BOTH train and test PF beat the current setting.")


if __name__ == "__main__":
    main()

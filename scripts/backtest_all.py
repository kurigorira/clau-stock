"""Compare donchian vs fibonacci across every CSV in data/.

For each data/<symbol>_h1.csv this runs the backtest twice — once with the
matching config forced to strategy=donchian and once forced to
strategy=fibonacci — and prints a side-by-side table so the strategies can
be judged on identical data before rollout.

Usage:
    python scripts/backtest_all.py                       # all data/*.csv, default params
    python scripts/backtest_all.py --config config/fib_xauusd.yaml data/xauusd_h1.csv

Without --config each CSV uses a default Config() (donchian defaults +
fibonacci defaults); pass a config to test tuned per-symbol parameters.
"""
from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader.backtest import run_backtest  # noqa: E402
from gold_trader.config import Config  # noqa: E402
from gold_trader.data import load_csv  # noqa: E402


def _profit_factor(trades) -> float:
    wins = sum(t.pnl_price for t in trades if t.pnl_price > 0)
    losses = -sum(t.pnl_price for t in trades if t.pnl_price < 0)
    return wins / losses if losses > 0 else float("inf") if wins > 0 else 0.0


def _run_both(csv_path: Path, cfg: Config) -> tuple[dict, dict]:
    df = load_csv(csv_path)
    results = []
    for strategy in ("donchian", "fibonacci"):
        c = copy.deepcopy(cfg)
        c.strategy = strategy
        results.append(run_backtest(df, c))
    return results[0], results[1]


def main() -> None:
    parser = argparse.ArgumentParser(description="donchian vs fibonacci comparison")
    parser.add_argument("--config", default=None, help="YAML with tuned params")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("csvs", nargs="*", help="explicit CSVs (default: data/*.csv)")
    args = parser.parse_args()

    cfg = Config.from_yaml(args.config) if args.config else Config()
    csvs = [Path(p) for p in args.csvs] or sorted(Path(args.data_dir).glob("*_h1.csv"))
    if not csvs:
        sys.stderr.write(f"no CSVs found in {args.data_dir}/ — run dump_history.py first\n")
        sys.exit(2)

    hdr = (
        f"{'symbol':<16} | {'strategy':<9} | {'n':>4} | {'win%':>6} | "
        f"{'PF':>6} | {'totPnL':>10} | {'maxDD':>10}"
    )
    print(hdr)
    print("-" * len(hdr))
    for csv_path in csvs:
        symbol = csv_path.stem.replace("_h1", "")
        try:
            don, fib = _run_both(csv_path, cfg)
        except Exception as exc:  # noqa: BLE001
            print(f"{symbol:<16} | ERROR: {exc}")
            continue
        for name, r in (("donchian", don), ("fibonacci", fib)):
            pf = _profit_factor(r["trades"])
            pf_s = f"{pf:6.2f}" if pf != float("inf") else "   inf"
            print(
                f"{symbol:<16} | {name:<9} | {r['n']:>4} | {r['win_rate']:>6.1%} | "
                f"{pf_s} | {r['total_pnl_price']:>10.2f} | "
                f"{r.get('max_drawdown_price', 0.0):>10.2f}"
            )


if __name__ == "__main__":
    main()

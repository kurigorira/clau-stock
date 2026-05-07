"""Backtest the strategy on a CSV of OHLCV bars.

Usage:
    python scripts/run_backtest.py config/example.yaml data/xauusd_h1.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader.backtest import run_backtest  # noqa: E402
from gold_trader.config import Config  # noqa: E402
from gold_trader.data import load_csv  # noqa: E402


def main() -> None:
    if len(sys.argv) != 3:
        print("usage: run_backtest.py <config.yaml> <ohlcv.csv>", file=sys.stderr)
        sys.exit(2)
    cfg = Config.from_yaml(sys.argv[1])
    df = load_csv(sys.argv[2])
    result = run_backtest(df, cfg)
    print(f"trades:        {result['n']}")
    print(f"win rate:      {result['win_rate']:.2%}")
    print(f"total pnl:     {result['total_pnl_price']:.2f}  (price units)")
    if result["n"]:
        print(f"avg win:       {result['avg_win']:.2f}")
        print(f"avg loss:      {result['avg_loss']:.2f}")
        print(f"max drawdown:  {result['max_drawdown_price']:.2f}")


if __name__ == "__main__":
    main()

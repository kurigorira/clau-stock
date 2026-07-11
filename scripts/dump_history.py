"""Dump historical H1 OHLCV bars from MT5 to CSV, one file per symbol.

Run on the Windows box with the target MT5 terminal installed. Output files
feed scripts/backtest_all.py.

Usage:
    # dump 6 months of H1 bars for every symbol in the given configs
    python scripts/dump_history.py --account 1 --months 6 config/fib_*.yaml

    # or name symbols directly
    python scripts/dump_history.py --account 1 --months 6 --symbols XAUUSD EURUSD

CSV columns: time,open,high,low,close,volume  ->  data/<symbol>_h1.csv
(symbol is lowercased; characters unsafe for filenames are replaced with _)
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

from gold_trader.config import Config  # noqa: E402
from gold_trader.mt5_client import MT5Credentials, connect, timeframe  # noqa: E402


def _safe_name(symbol: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", symbol.lower())


def main() -> None:
    parser = argparse.ArgumentParser(description="dump MT5 H1 history to CSV")
    parser.add_argument("--account", default=None, help="env-var suffix (MT5_LOGIN_N ...)")
    parser.add_argument("--months", type=int, default=6, help="how far back to fetch")
    parser.add_argument("--out-dir", default="data", help="output directory")
    parser.add_argument("--symbols", nargs="*", default=[], help="explicit symbol names")
    parser.add_argument("configs", nargs="*", help="YAMLs whose `symbol:` fields to dump")
    args = parser.parse_args()

    load_dotenv()
    symbols = list(dict.fromkeys(
        [Config.from_yaml(p).symbol for p in args.configs] + args.symbols
    ))
    if not symbols:
        sys.stderr.write("nothing to dump: pass configs and/or --symbols\n")
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

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    date_from = datetime.now(timezone.utc) - timedelta(days=args.months * 31)

    with connect(creds) as mt5:
        for sym in symbols:
            mt5.symbol_select(sym, True)
            rates = mt5.copy_rates_range(
                sym, timeframe("H1"), date_from, datetime.now(timezone.utc)
            )
            if rates is None or len(rates) == 0:
                print(f"SKIP {sym}: no rates ({mt5.last_error()})", file=sys.stderr)
                continue
            import pandas as pd  # local so --help works without pandas

            df = pd.DataFrame(rates)
            df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
            df = df.rename(columns={"tick_volume": "volume"})
            df = df[["time", "open", "high", "low", "close", "volume"]]
            out = out_dir / f"{_safe_name(sym)}_h1.csv"
            df.to_csv(out, index=False)
            print(f"OK   {sym}: {len(df)} bars -> {out}")


if __name__ == "__main__":
    main()

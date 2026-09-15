"""One-shot stop-loss sweep: attach an ATR stop to every position without one.

Meant for accounts the bot is NOT managing (e.g. the paused live account 3)
or as a manual safety check. Unlike the executor's built-in sweep this scans
ALL positions on the account regardless of magic number.

Usage:
    python scripts/ensure_sl.py --account 3            # dry-run: report only
    python scripts/ensure_sl.py --account 3 --apply    # actually attach SLs
    python scripts/ensure_sl.py --account 3 --apply --atr-mult 1.5
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader import mt5_client  # noqa: E402
from gold_trader.mt5_client import MT5Credentials, connect  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="attach SL to unprotected positions")
    parser.add_argument("--account", default=None, help="env-var suffix (MT5_LOGIN_N ...)")
    parser.add_argument("--apply", action="store_true",
                        help="actually modify positions (default: dry-run report)")
    parser.add_argument("--atr-mult", type=float, default=2.0,
                        help="stop distance in ATR(14) multiples (H1)")
    args = parser.parse_args()

    load_dotenv()
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

    with connect(creds) as mt5:
        positions = mt5.positions_get() or []
        unprotected = [p for p in positions if not p.sl or p.sl <= 0]
        print(f"{len(positions)} open position(s), {len(unprotected)} without a stop-loss")
        for p in unprotected:
            side = "buy" if p.type == mt5.POSITION_TYPE_BUY else "sell"
            df = mt5_client.fetch_ohlcv(p.symbol, "H1", 100)
            closed = df.iloc[:-1]
            tr = (closed["high"] - closed["low"]).rolling(14).mean()
            atr = float(tr.iloc[-1])
            close = float(closed["close"].iloc[-1])
            stop = close - args.atr_mult * atr if side == "buy" else close + args.atr_mult * atr
            print(
                f"  {p.symbol} ticket={p.ticket} {side} vol={p.volume} "
                f"entry={p.price_open} -> SL {stop:.5f} "
                f"({'APPLYING' if args.apply else 'dry-run'})"
            )
            if args.apply:
                try:
                    mt5_client.modify_position_sl(p, stop)
                    print("    OK")
                except Exception as exc:  # noqa: BLE001
                    print(f"    FAILED: {exc}")
        if unprotected and not args.apply:
            print("\nre-run with --apply to attach these stops")


if __name__ == "__main__":
    main()

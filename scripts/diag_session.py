"""What hours does this broker actually trade these symbols?

The fleet's session window (13:30-21:00 UTC) is derived from US cash-equity
hours, but a CFD venue can quote a narrower or shifted window, and a wrong
guess shows up as a stream of "Market closed" rejections during what should be
the trading day. MT5 publishes the answer: symbol_info_session_quote /
session_trade give the declared sessions per weekday, in the *server's*
timezone.

This prints them alongside the server-vs-UTC offset so the config window can be
set from the broker's own data instead of an assumption. It also prints the
current tick and whether the symbol is flagged tradeable right now, which
distinguishes "outside hours" from "this account cannot trade this symbol".

Usage:
    python scripts/diag_session.py --account 1 --symbols BMY HOOD WFC
    python scripts/diag_session.py --account 1 config/us_fleet/*.yaml
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader.cli_util import expand_paths  # noqa: E402
from gold_trader.config import Config  # noqa: E402
from gold_trader.mt5_client import MT5Credentials, connect  # noqa: E402

_DAYS = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")


def _sessions(mt5, symbol: str, getter) -> dict:
    """{'Mon': ['13:30-20:00', ...]} from MT5's per-weekday session API."""
    out: dict[str, list[str]] = {}
    for day in range(7):
        ranges = []
        for i in range(8):  # a weekday can declare several sessions
            try:
                got = getter(symbol, day, i)
            except Exception:  # noqa: BLE001
                break
            if not got:
                break
            frm, to = got
            ranges.append(f"{frm.strftime('%H:%M')}-{to.strftime('%H:%M')}")
        if ranges:
            out[_DAYS[day]] = ranges
    return out


def main() -> None:
    p = argparse.ArgumentParser(description="show the broker's declared sessions")
    p.add_argument("--account", default=None, help="env-var suffix (MT5_LOGIN_N ...)")
    p.add_argument("--symbols", nargs="*", default=[])
    p.add_argument("configs", nargs="*", help="configs whose symbols to inspect")
    args = p.parse_args()

    symbols = list(args.symbols)
    for path in expand_paths(args.configs):
        symbols.append(Config.from_yaml(path).symbol)
    symbols = list(dict.fromkeys(symbols))[:12]   # a dozen is plenty to see the pattern
    if not symbols:
        sys.stderr.write("pass --symbols and/or config paths\n")
        sys.exit(2)

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
        now_utc = datetime.now(timezone.utc)
        tick_any = mt5.symbol_info_tick(symbols[0])
        if tick_any is not None and getattr(tick_any, "time", 0):
            server_now = datetime.fromtimestamp(tick_any.time, tz=timezone.utc)
            offset_h = round((server_now - now_utc).total_seconds() / 3600.0)
            print(f"# server clock is UTC{offset_h:+d} (from {symbols[0]} tick time)"
                  " — session times below are in SERVER time, so shift by this to"
                  " get the UTC window for config `session:`")
        print(f"# now {now_utc:%Y-%m-%d %H:%M} UTC ({_DAYS[(now_utc.weekday() + 1) % 7]})")
        print()

        for sym in symbols:
            mt5.symbol_select(sym, True)
            info = mt5.symbol_info(sym)
            if info is None:
                print(f"{sym}: symbol_info unavailable")
                continue
            tick = mt5.symbol_info_tick(sym)
            mode = getattr(info, "trade_mode", None)
            quotes = (f"bid={tick.bid} ask={tick.ask}" if tick else "no tick")
            print(f"{sym}: trade_mode={mode} {quotes}")
            trade = _sessions(mt5, sym, mt5.symbol_info_session_trade)
            quote = _sessions(mt5, sym, mt5.symbol_info_session_quote)
            print(f"   trade sessions: {trade or '(none declared)'}")
            if quote != trade:
                print(f"   quote sessions: {quote or '(none declared)'}")

        print()
        print("# trade_mode 0 = disabled, 4 = full. A symbol with sessions but"
              " mode 0 cannot be traded on this account at all — that is a"
              " different problem from being outside the hours.")


if __name__ == "__main__":
    main()

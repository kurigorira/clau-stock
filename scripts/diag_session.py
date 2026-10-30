"""What hours does this broker actually trade these symbols?

A stream of "Market closed" rejections has two very different causes: the bot
ran outside the venue's hours, or the account cannot trade those symbols at
all. This tells them apart from the broker's own data.

For each symbol it prints trade_mode (0 = disabled for this account, 4 = full),
the live bid/ask, and — most usefully — how stale the last tick is. A quote
from hours ago means the venue is simply shut; a fresh quote alongside a
rejection means something else is wrong.

MT5's symbol_info_session_trade / session_quote give the declared per-weekday
sessions when the installed build exposes them (several releases do not), in
server time.

Times printed here are UTC. Note that your shell's log timestamps are LOCAL
time — mistaking one for the other is exactly how a bot ends up looking like
it ran mid-session when it ran overnight.

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


def _sessions(mt5, symbol: str, getter) -> dict | None:
    """{'Mon': ['13:30-20:00', ...]} from MT5's per-weekday session API.

    None when this MetaTrader5 build doesn't expose the session functions —
    they are absent in several releases, so the caller falls back to the tick
    clock rather than crashing."""
    if getter is None:
        return None
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
        print(f"# now {now_utc:%Y-%m-%d %H:%M} UTC "
              f"({_DAYS[(now_utc.weekday() + 1) % 7]}) — note your shell prints "
              "local time, which is NOT this")
        print("# session times below are in SERVER time when MT5 reports them")
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
            # tick.time is a unix instant, so this is how STALE the last quote
            # is — the most direct evidence of whether the venue is trading now.
            age = ""
            if tick is not None and getattr(tick, "time", 0):
                last = datetime.fromtimestamp(tick.time, tz=timezone.utc)
                hours = (now_utc - last).total_seconds() / 3600.0
                age = (f" last tick {last:%m-%d %H:%M} UTC "
                       f"({hours:.1f}h ago{' — CLOSED' if hours > 0.5 else ' — live'})")
            print(f"{sym}: trade_mode={mode} {quotes}{age}")
            trade = _sessions(mt5, sym, getattr(mt5, "symbol_info_session_trade", None))
            quote = _sessions(mt5, sym, getattr(mt5, "symbol_info_session_quote", None))
            if trade is None and quote is None:
                print("   sessions: this MetaTrader5 build does not expose "
                      "symbol_info_session_* — use the tick age above, or read "
                      "Specification in the terminal (right-click the symbol)")
                continue
            print(f"   trade sessions: {trade or '(none declared)'}")
            if quote != trade:
                print(f"   quote sessions: {quote or '(none declared)'}")

        print()
        print("# trade_mode 0 = disabled, 4 = full. A symbol with sessions but"
              " mode 0 cannot be traded on this account at all — that is a"
              " different problem from being outside the hours.")


if __name__ == "__main__":
    main()

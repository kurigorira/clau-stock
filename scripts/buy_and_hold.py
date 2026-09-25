"""Hold the universe. No signals, no stops, no bot.

Buy and hold is not a strategy the trading loop can run - it is a portfolio
state. This builds that state: one equal-weight position per symbol, sized to
a target exposure, topping up whatever is missing. Then nothing. There is no
exit rule, so there is nothing to poll for; run it once, and again only when
you want to rebalance or after a deposit.

It refuses to trade unless --execute is passed. The default prints the plan,
which for a 100-symbol fleet is 100 orders you want to read before sending.

    python scripts/buy_and_hold.py --account 1 config/us_fleet/*.yaml
    python scripts/buy_and_hold.py --account 1 --exposure 1.0 --execute \\
        config/us_fleet/*.yaml

Two costs sizing cannot remove, which belong in the decision:

  financing  A CFD pays swap on the full notional every night it is held.
             Held forever, that is paid forever - and on leverage if exposure
             is above 1. A cash share or an ETF pays none of it, so if the
             aim is simply to own the market, a CFD is an expensive way.
  drawdown   Nothing here sets a stop. At exposure 1.0 the book falls with
             the market; at 2.0 it falls twice as fast and meets a margin
             call on the way.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader import mt5_client  # noqa: E402
from gold_trader.buyhold import BUYHOLD_MAGIC, plan_targets  # noqa: E402
from gold_trader.cli_util import expand_paths  # noqa: E402
from gold_trader.config import Config  # noqa: E402
from gold_trader.mt5_client import (  # noqa: E402
    MarketClosedError,
    MT5Credentials,
    OrderRejected,
    UnknownSymbolError,
    connect,
)


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    p = argparse.ArgumentParser(description="equal-weight buy and hold")
    p.add_argument("configs", nargs="+", help="fleet YAMLs; only `symbol:` is used")
    p.add_argument("--account", default=None, help="env-var suffix (MT5_LOGIN_N ...)")
    p.add_argument("--exposure", type=float, default=1.0,
                   help="total notional as a multiple of equity (default 1.0 = "
                        "unlevered). This is the entire risk decision: there are "
                        "no stops")
    p.add_argument("--magic", type=int, default=BUYHOLD_MAGIC,
                   help="magic number stamped on every position, so the reports "
                        "can tell this book from the retired ones")
    p.add_argument("--execute", action="store_true",
                   help="actually send the orders; without it the plan is printed")
    args = p.parse_args()

    load_dotenv()
    cfgs = [Config.from_yaml(x) for x in expand_paths(args.configs)]
    symbols = sorted({c.symbol for c in cfgs})
    if not symbols:
        sys.stderr.write("no symbols in those configs\n")
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

    with connect(creds):
        equity = mt5_client.account_equity()
        quotes: dict = {}
        unavailable: list[str] = []
        for symbol in symbols:
            try:
                if not mt5_client.ensure_symbol_visible(symbol):
                    unavailable.append(symbol)
                    continue
                tick = mt5_client.symbol_tick(symbol)
                meta = mt5_client.symbol_meta(symbol)
            except (UnknownSymbolError, RuntimeError):
                unavailable.append(symbol)
                continue
            ask = tick[1] if tick else 0.0
            if not ask or ask <= 0:
                unavailable.append(symbol)
                continue
            quotes[symbol] = (float(ask), meta)

        held: dict[str, float] = {}
        for symbol in quotes:
            for pos in mt5_client.open_positions(symbol, args.magic):
                held[symbol] = held.get(symbol, 0.0) + float(pos.volume)

        plan = plan_targets(quotes, equity, exposure=args.exposure, held=held)

        print(f"equal-weight buy and hold - account {args.account}")
        print(f"equity {equity:,.0f}   exposure {args.exposure:g}x   "
              f"{len(quotes)}/{len(symbols)} symbols quoted   magic {args.magic}")
        if unavailable:
            print(f"  not quoted, skipped: {', '.join(unavailable[:10])}"
                  f"{' ...' if len(unavailable) > 10 else ''}")
        print()
        print(f"  {'symbol':<12} {'price':>10} {'target':>9} {'held':>9} "
              f"{'to buy':>9} {'notional':>12}  note")
        buys = [t for t in plan if t.to_buy > 0]
        for t in plan:
            print(f"  {t.symbol:<12} {t.price:>10.2f} {t.volume:>9.2f} "
                  f"{t.held:>9.2f} {t.to_buy:>9.2f} {t.notional:>12,.0f}  {t.skip}")
        total = sum(t.notional for t in plan)
        currency = mt5_client.account_currency()
        print()
        if equity:
            print(f"  target notional {total:,.0f} {currency} = "
                  f"{total / equity:.2f}x equity ({equity:,.0f} {currency})")
        print(f"  orders to send: {len(buys)}")

        # The first version sized a JPY account against USD prices and printed
        # a 150x book as "1.00x". Both figures now come from the same currency
        # by construction, so this can only trip on something new - which is
        # exactly when it should stop rather than send a hundred orders.
        if equity and total > equity * (args.exposure + 0.05):
            sys.stderr.write(
                f"\nREFUSING: the plan totals {total / equity:.2f}x equity but "
                f"--exposure is {args.exposure:g}. Sizing and equity are "
                f"supposed to be in the same currency; they are not. "
                f"Nothing sent.\n"
            )
            sys.exit(3)

        if not args.execute:
            print()
            print("dry run - nothing sent. Re-run with --execute to place these.")
            print("Remember: swap is charged on the full notional every night this")
            print("is held, and nothing here sets a stop.")
            return

        sent = failed = 0
        # 99 orders failing for one reason scrolls that reason off the screen,
        # so keep a tally and repeat it at the end. The symbol name is the
        # part that differs; the cause is the part worth reading.
        reasons: dict[str, list[str]] = {}

        def note(symbol: str, reason: str) -> None:
            reasons.setdefault(reason, []).append(symbol)

        for t in buys:
            try:
                mt5_client.market_order(
                    symbol=t.symbol, side="buy", volume=t.to_buy,
                    sl=None, tp=None, magic=args.magic, deviation=20,
                    comment="buyhold",
                )
                sent += 1
                print(f"  bought {t.symbol} {t.to_buy:g}")
            except MarketClosedError:
                failed += 1
                note(t.symbol, "market closed - run again while it trades")
                print(f"  {t.symbol}: market closed, run again while it trades")
            except OrderRejected as exc:
                failed += 1
                # describe() deliberately carries no per-order detail, so a
                # hundred orders refused for one reason group into one line
                note(t.symbol, exc.describe())
                print(f"  {t.symbol}: {exc}")
            except Exception as exc:  # noqa: BLE001
                failed += 1
                note(t.symbol, str(exc).replace(t.symbol, "<symbol>"))
                print(f"  {t.symbol}: {exc}")
        print()
        print(f"sent {sent}, failed {failed}. Re-run to top up anything missed; "
              f"symbols already at target are skipped.")

        if failed:
            print()
            print("why they failed:")
            for reason, symbols in sorted(
                reasons.items(), key=lambda kv: -len(kv[1])
            ):
                shown = ", ".join(symbols[:5])
                more = f" ... +{len(symbols) - 5}" if len(symbols) > 5 else ""
                print(f"  {len(symbols):>3}x  {reason}")
                print(f"       {shown}{more}")
            if sent == 0:
                print()
                print("Nothing was sent at all, so this is one condition, not "
                      "99 unlucky symbols. Check, in order:")
                print("  1. Is the US market open? (JST 22:30-06:00)")
                print("  2. Is AutoTrading enabled in this terminal? The "
                      "toolbar button must be green - turning it off to stop "
                      "the bots also blocks these orders.")
                print("  3. Does the terminal allow algorithmic trading? "
                      "Tools > Options > Expert Advisors.")


if __name__ == "__main__":
    main()

"""Scan the broker's symbol list for instruments that fit the strategies.

Reverses the usual workflow: instead of hand-picking symbols and testing
them, this walks every symbol MT5 exposes (optionally filtered by group),
backtests BOTH strategies on a train/test split with spread-aware slippage,
and reports only the symbols whose winner clears the gate on both segments.

Usage (on the Windows box, MT5 terminal logged in):
    # everything the broker offers (slow: minutes to an hour depending on count)
    python scripts/screen_symbols.py --account 1 --months 6

    # only some Market Watch groups (see MT5 Symbols dialog for group paths)
    python scripts/screen_symbols.py --account 1 --months 6 --groups "Forex*"
    python scripts/screen_symbols.py --account 2 --months 6 --groups "*Stock*,*Share*"

    # emit candidate YAMLs for the passers (config/candidate_<slug>.yaml)
    python scripts/screen_symbols.py --account 1 --months 6 --emit-configs

Gate defaults: train PF >= 1.2 with >= 10 trades, then test PF >= 1.0 with
>= 4 trades on the held-out 30%. Tune via flags. Candidates still deserve a
look before joining start.bat — screening across hundreds of symbols will
always surface a few survivors by chance.
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
from gold_trader.screener import existing_symbols, passes_gate, score_symbol  # noqa: E402


CANDIDATE_TEMPLATE = """\
# {symbol} CANDIDATE preset from scripts/screen_symbols.py.
# Winner: {strategy} (train PF {train_pf:.2f}/n={train_n}, test PF {test_pf:.2f}/n={test_n}).
# Review before adding to start.bat - screening many symbols surfaces some
# survivors by chance. Inherits defaults from src/gold_trader/config.py.
symbol: {symbol}
timeframe: H1
strategy: {strategy}

risk:
  per_trade_pct: 0.3
  atr_stop_mult: 2.0
  max_positions: 1

filters:
  atr_pct_min: 0.0003
  atr_pct_max: 0.10

daily_guard:
  max_consecutive_losses: 2
  max_loss_pct: 2.0

execution:
  magic_number: {magic}
  deviation_points: 20
  comment: "cand_{slug}"
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="screen broker symbols for strategy fit")
    parser.add_argument("--account", default=None, help="env-var suffix (MT5_LOGIN_N ...)")
    parser.add_argument("--months", type=int, default=6)
    parser.add_argument("--groups", default="*", help="comma-separated MT5 group patterns")
    parser.add_argument("--split", type=float, default=0.7, help="train fraction")
    parser.add_argument("--min-train-trades", type=int, default=10)
    parser.add_argument("--min-train-pf", type=float, default=1.2)
    parser.add_argument("--min-test-trades", type=int, default=4)
    parser.add_argument("--min-test-pf", type=float, default=1.0)
    parser.add_argument("--min-bars", type=int, default=1500, help="skip thin histories")
    parser.add_argument("--limit", type=int, default=0, help="stop after N symbols (0 = all)")
    parser.add_argument("--top", type=int, default=0,
                        help="keep only the N best passers by test PF (0 = all)")
    parser.add_argument("--include-existing", action="store_true",
                        help="also scan symbols that already have a preset in config/ "
                             "(default: skip them - the fleet and benched symbols are settled)")
    parser.add_argument("--emit-configs", action="store_true",
                        help="write config/candidate_<slug>.yaml for each passer")
    parser.add_argument("--magic-base", type=int, default=20260800,
                        help="first magic_number for emitted candidate configs")
    parser.add_argument("--symbols", nargs="*", default=[],
                        help="scan exactly these symbols (bypasses --groups AND the "
                             "settled-symbol filter; use to re-validate candidates)")
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

    cfg = Config()
    cfg.filters.atr_pct_min = 0.0003   # class-agnostic wide band; spread cost
    cfg.filters.atr_pct_max = 0.10     # does the real gatekeeping

    date_from = datetime.now(timezone.utc) - timedelta(days=args.months * 31)
    passers = []
    scanned = 0

    with connect(creds) as mt5:
        import pandas as pd

        if args.symbols:
            # explicit re-validation list: no group scan, no settled filter
            tradeable = []
            for name in args.symbols:
                mt5.symbol_select(name, True)
                info = mt5.symbol_info(name)
                if info is None:
                    print(f"  {name}: unknown symbol, skipped", flush=True)
                    continue
                tradeable.append(info)
            skipped_settled = 0
        else:
            symbols = []
            for pattern in args.groups.split(","):
                symbols.extend(mt5.symbols_get(group=pattern.strip()) or [])
            settled = set() if args.include_existing else existing_symbols(
                Path(__file__).resolve().parents[1] / "config"
            )
            # dedupe, tradeable only, skip already-settled symbols
            seen = set()
            tradeable = []
            skipped_settled = 0
            for s in symbols:
                if s.name in seen:
                    continue
                seen.add(s.name)
                if s.name in settled:
                    skipped_settled += 1
                    continue
                if s.trade_mode == mt5.SYMBOL_TRADE_MODE_FULL:
                    tradeable.append(s)
        print(f"scanning {len(tradeable)} tradeable symbols "
              f"({skipped_settled} already settled in config/ skipped; "
              f"groups={args.groups}, {args.months} months, split={args.split})",
              flush=True)

        for i, info in enumerate(tradeable, 1):
            if args.limit and scanned >= args.limit:
                break
            sym = info.name
            rates = mt5.copy_rates_range(
                sym, timeframe("H1"), date_from, datetime.now(timezone.utc)
            )
            if rates is None or len(rates) < args.min_bars:
                continue
            df = pd.DataFrame(rates)
            df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
            df = df.set_index("time").rename(columns={"tick_volume": "volume"})
            df = df[["open", "high", "low", "close", "volume"]]
            scanned += 1

            # Floating-spread symbols report spread=0 in symbol_info; fall
            # back to the live tick's ask-bid so slippage stays realistic.
            spread_pts = float(info.spread)
            if spread_pts <= 0 and info.point > 0:
                tick = mt5.symbol_info_tick(sym)
                if tick and tick.ask > 0 and tick.bid > 0 and tick.ask >= tick.bid:
                    spread_pts = (tick.ask - tick.bid) / info.point

            try:
                result = score_symbol(
                    sym, df, cfg,
                    spread_points=spread_pts,
                    point=float(info.point),
                    split_ratio=args.split,
                )
            except Exception as exc:  # noqa: BLE001
                print(f"  {sym}: ERROR {exc}", flush=True)
                continue

            best = None
            for score in result.scores:
                if passes_gate(
                    score,
                    min_train_trades=args.min_train_trades,
                    min_train_pf=args.min_train_pf,
                    min_test_trades=args.min_test_trades,
                    min_test_pf=args.min_test_pf,
                ) and (best is None or score.test_pf > best.test_pf):
                    best = score
            if best is not None:
                passers.append((result, best))
                print(
                    f"  PASS {sym}: {best.strategy} "
                    f"train PF {best.train_pf:.2f} (n={best.train_n}) / "
                    f"test PF {best.test_pf:.2f} (n={best.test_n}) "
                    f"spread={info.spread}pt",
                    flush=True,
                )
            if i % 25 == 0:
                print(f"  ... {i}/{len(tradeable)} scanned, {len(passers)} passers", flush=True)

    print()
    passers.sort(key=lambda rb: rb[1].test_pf, reverse=True)
    if args.top and len(passers) > args.top:
        print(f"keeping top {args.top} of {len(passers)} passers by test PF")
        passers = passers[: args.top]
    hdr = (
        f"{'symbol':<20} | {'strategy':<9} | {'trainPF':>7} | {'n':>4} | "
        f"{'testPF':>7} | {'n':>4} | {'spread':>6}"
    )
    print(hdr)
    print("-" * len(hdr))
    for result, best in passers:
        print(
            f"{result.symbol:<20} | {best.strategy:<9} | {best.train_pf:>7.2f} | "
            f"{best.train_n:>4} | {best.test_pf:>7.2f} | {best.test_n:>4} | "
            f"{result.spread_points:>6.0f}"
        )
    print(f"\n{scanned} symbols scanned, {len(passers)} passed the gate")

    if args.emit_configs and passers:
        out_dir = Path(__file__).resolve().parents[1] / "config"
        for offset, (result, best) in enumerate(passers):
            slug = re.sub(r"[^a-z0-9]", "_", result.symbol.lower())
            path = out_dir / f"candidate_{slug}.yaml"
            path.write_text(
                CANDIDATE_TEMPLATE.format(
                    symbol=result.symbol, strategy=best.strategy,
                    train_pf=best.train_pf, train_n=best.train_n,
                    test_pf=best.test_pf, test_n=best.test_n,
                    magic=args.magic_base + offset, slug=slug,
                ),
                encoding="utf-8",
            )
            print(f"wrote {path.name}")
        print("review the candidates, then add chosen ones to start.bat")


if __name__ == "__main__":
    main()

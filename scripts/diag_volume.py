"""Why is live volume low? Per-symbol sizing dry-run against a real account.

For every config YAML (or --symbols with default params) this connects to the
account, pulls equity + symbol metadata + current H1 ATR, and walks the exact
sizing chain the executor uses (risk.position_volume):

    risk_amount   = equity * per_trade_pct%
    money_per_lot = stop_distance / tick_size * tick_value
    raw lots      = risk_amount / money_per_lot   -> floor to volume_step
    ZEROED if that lands below the broker's volume_min  <- silent trade killer

The last rule matters most: when equity * risk%% can't afford one minimum lot
at the current ATR stop, the executor skips the entry entirely (logged, but
easy to miss). High-priced stocks hit this first. The table shows, per symbol,
the final lots and — when ZEROED — the per_trade_pct or equity needed to
actually trade it.

Usage:
    python scripts/diag_volume.py --account 1 config/macd_breadth.yaml
    python scripts/diag_volume.py --account 1 --symbols AAPL NVIDIA COST UNH
    python scripts/diag_volume.py --account 2 --symbols AAPL --risk-pct 0.5
"""
from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader.cli_util import expand_paths  # noqa: E402
from gold_trader.config import Config  # noqa: E402
from gold_trader.mt5_client import MT5Credentials, connect, timeframe  # noqa: E402
from gold_trader.risk import position_volume  # noqa: E402
from gold_trader.strategy import _atr  # noqa: E402

import pandas as pd  # noqa: E402


def _frame(rates) -> pd.DataFrame:
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("time").rename(columns={"tick_volume": "volume"})
    return df[["open", "high", "low", "close", "volume"]]


def main() -> None:
    p = argparse.ArgumentParser(description="live position-sizing diagnosis")
    p.add_argument("--account", default=None, help="env-var suffix (MT5_LOGIN_N ...)")
    p.add_argument("--symbols", nargs="*", default=[], help="explicit symbols "
                   "(diagnosed with default Config params)")
    p.add_argument("--risk-pct", type=float, default=None,
                   help="override per_trade_pct for a what-if run")
    p.add_argument("configs", nargs="*", help="YAMLs to diagnose (symbol + risk params)")
    args = p.parse_args()

    try:
        config_paths = expand_paths(args.configs)  # PowerShell passes globs literally
    except FileNotFoundError as exc:
        sys.stderr.write(f"{exc}\n")
        sys.exit(2)
    jobs: list[Config] = [Config.from_yaml(c) for c in config_paths]
    for sym in args.symbols:
        cfg = Config()
        cfg.symbol = sym
        jobs.append(cfg)
    if not jobs:
        sys.stderr.write("nothing to diagnose: pass configs and/or --symbols\n")
        sys.exit(2)
    if args.risk_pct is not None:
        for cfg in jobs:
            cfg.risk.per_trade_pct = args.risk_pct

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
        acct = mt5.account_info()
        if acct is None:
            sys.stderr.write("account_info unavailable\n")
            sys.exit(2)
        equity = float(acct.equity)
        print(f"# account {acct.login} ({acct.server})  equity={equity:.2f} "
              f"{acct.currency}")
        hdr = (f"{'symbol':<12} {'risk%':>5} {'price':>9} {'stop':>8} "
               f"{'min':>6} {'raw':>8} {'lots':>7}  status")
        print(hdr)
        print("-" * len(hdr))

        zeroed = 0
        for cfg in jobs:
            sym = cfg.symbol
            mt5.symbol_select(sym, True)
            info = mt5.symbol_info(sym)
            if info is None:
                print(f"{sym:<12} ERROR: symbol_info unavailable")
                continue
            n = cfg.risk.atr_length * 3 + 10
            rates = mt5.copy_rates_from_pos(sym, timeframe("H1"), 0, n)
            if rates is None or len(rates) < cfg.risk.atr_length + 2:
                print(f"{sym:<12} ERROR: no H1 rates ({mt5.last_error()})")
                continue
            closed = _frame(rates).iloc[:-1]
            atr = float(_atr(closed, cfg.risk.atr_length).iloc[-1])
            price = float(closed["close"].iloc[-1])
            stop = cfg.risk.atr_stop_mult * atr
            pct = cfg.risk.per_trade_pct
            tick_value = float(info.trade_tick_value)
            tick_size = float(info.trade_tick_size)
            vmin, vmax = float(info.volume_min), float(info.volume_max)
            vstep = float(info.volume_step)

            money_per_lot = (stop / tick_size) * tick_value if tick_size > 0 else 0.0
            risk_amount = equity * pct / 100.0
            raw = risk_amount / money_per_lot if money_per_lot > 0 else 0.0
            lots = position_volume(
                equity=equity, risk_pct=pct, stop_distance_price=stop,
                tick_value=tick_value, tick_size=tick_size,
                volume_min=vmin, volume_max=vmax, volume_step=vstep,
            )
            if lots <= 0:
                zeroed += 1
                need_risk = (vmin * money_per_lot / equity * 100.0
                             if equity > 0 and money_per_lot > 0 else float("inf"))
                need_equity = (vmin * money_per_lot / (pct / 100.0)
                               if pct > 0 and money_per_lot > 0 else float("inf"))
                status = (f"ZEROED — need risk>={need_risk:.2f}% "
                          f"or equity>={need_equity:.0f}")
            elif lots >= vmax:
                status = "clamped to volume_max"
            else:
                over = lots / raw if raw > 0 else 1.0
                status = "OK" + (f" (min-lot = {over:.1f}x target risk)"
                                 if lots == vmin and over > 1.05 else "")
            print(f"{sym:<12} {pct:>5.2f} {price:>9.2f} {stop:>8.2f} "
                  f"{vmin:>6g} {raw:>8.3f} {lots:>7g}  {status}")

        print("-" * len(hdr))
        print(f"# {zeroed}/{len(jobs)} symbols ZEROED at current equity/risk — "
              "these produce signals but never orders.")
        print("# fix: raise risk.per_trade_pct, add equity, or drop the symbol; "
              "re-run with --risk-pct X to preview.")


if __name__ == "__main__":
    main()

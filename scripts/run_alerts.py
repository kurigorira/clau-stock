"""Price-change alert loop.

Polls M1 bars for each configured symbol and emails NOTIFY_TO whenever
``|close[-1] - close[-1 - window_minutes]| / close[-1 - window_minutes]``
exceeds ``threshold_pct`` (configured in ``config/watchlist.yaml``).

Usage:
    # Picks up the union of (config/watchlist.yaml extra_symbols) and the
    # `symbol:` field from each of the 13 trading-preset YAMLs passed after it.
    python scripts/run_alerts.py --account 1 \\
        config/watchlist.yaml \\
        config/example.yaml config/eurusd.yaml ... config/eurusd_small.yaml

Like ``run_live.py`` this binds to ONE MT5 terminal (whichever account's
MT5_LOGIN_N is set), so the chosen account must have Market Watch access to
every symbol you want to monitor. Account 1's terminal usually covers all of
them on Vantage; if a symbol shows as ``unknown symbol`` the broker doesn't
expose it on that account and you should drop it from extra_symbols.
"""
from __future__ import annotations

import argparse
import os
import sys
import time as time_mod
from pathlib import Path

import yaml
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader import alerts, mt5_client, notify  # noqa: E402
from gold_trader.cli_util import expand_paths  # noqa: E402
from gold_trader.config import Config  # noqa: E402
from gold_trader.logger import setup_logging  # noqa: E402
from gold_trader.mt5_client import MT5Credentials, connect  # noqa: E402


def _load_watchlist(path: str) -> dict:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return {
        "threshold_pct": float(raw.get("threshold_pct", 2.0)),
        "window_minutes": int(raw.get("window_minutes", 10)),
        "poll_seconds": int(raw.get("poll_seconds", 30)),
        "throttle_sec": int(raw.get("throttle_sec", 1800)),
        "extra_symbols": list(raw.get("extra_symbols") or []),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="clau-stock price-change alerts")
    parser.add_argument(
        "--account",
        default=None,
        help="env-var suffix (e.g. --account 1 reads MT5_LOGIN_1, MT5_PASSWORD_1, ...)",
    )
    parser.add_argument("watchlist", help="path to watchlist.yaml")
    parser.add_argument(
        "configs",
        nargs="*",
        help="optional per-symbol trading YAMLs; their `symbol:` fields are merged in",
    )
    args = parser.parse_args()

    load_dotenv()
    watch = _load_watchlist(args.watchlist)
    preset_symbols = [Config.from_yaml(p).symbol for p in expand_paths(args.configs)]
    # Preserve insertion order, drop dupes
    symbols = list(dict.fromkeys(preset_symbols + watch["extra_symbols"]))
    if not symbols:
        sys.stderr.write("no symbols to watch (empty extra_symbols and no configs)\n")
        sys.exit(2)

    log_file_default = (
        f"logs/alerts{args.account}.log" if args.account else "logs/alerts.log"
    )
    log = setup_logging(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        log_file=os.environ.get("LOG_FILE") or log_file_default,
    )

    suffix = f"_{args.account}" if args.account else ""
    try:
        creds = MT5Credentials(
            login=int(os.environ[f"MT5_LOGIN{suffix}"]),
            password=os.environ[f"MT5_PASSWORD{suffix}"],
            server=os.environ[f"MT5_SERVER{suffix}"],
            path=os.environ.get(f"MT5_PATH{suffix}") or None,
        )
    except KeyError as missing:
        sys.stderr.write(
            f"missing env var {missing}. Did you set MT5_LOGIN{suffix} etc. in .env?\n"
        )
        sys.exit(2)

    log.info(
        "alerts: watching %d symbols at %.2f%% / %dmin (throttle %ds)",
        len(symbols),
        watch["threshold_pct"],
        watch["window_minutes"],
        watch["throttle_sec"],
    )
    log.info("alerts: symbols = %s", ", ".join(symbols))

    n_bars = watch["window_minutes"] + 2  # 1 extra to drop the still-forming bar
    # A symbol the terminal can never serve (not in this account's catalog,
    # no M1 history) would otherwise raise on every poll forever. Warn once
    # per symbol, then retire it after MAX_FAILS consecutive failures so the
    # log stays readable and the poll cycle stays fast.
    MAX_FAILS = 5
    fails: dict[str, int] = {}
    with connect(creds):
        while True:
            for sym in list(symbols):
                try:
                    raw = mt5_client.fetch_ohlcv(sym, "M1", n_bars)
                    fails.pop(sym, None)
                    closed = raw.iloc[:-1]  # drop the still-forming M1 bar
                    change = alerts.evaluate_change(sym, closed, watch["window_minutes"])
                    if change is None:
                        continue
                    if not alerts.should_alert(change.change_pct, watch["threshold_pct"]):
                        continue
                    notify.send_alert_mail(
                        symbol=change.symbol,
                        change_pct=change.change_pct,
                        current_price=change.current_price,
                        prev_price=change.prev_price,
                        window_minutes=watch["window_minutes"],
                        threshold_pct=watch["threshold_pct"],
                        throttle_sec=watch["throttle_sec"],
                        log=log,
                    )
                except Exception as exc:  # noqa: BLE001
                    n = fails[sym] = fails.get(sym, 0) + 1
                    if n == 1:
                        log.warning("alerts: poll failed for %s: %s", sym, exc)
                    if n >= MAX_FAILS:
                        symbols.remove(sym)
                        log.warning(
                            "alerts: dropping %s after %d consecutive failures "
                            "(not tradable/visible on account %s?)",
                            sym, n, args.account,
                        )
            if not symbols:
                log.error("alerts: no watchable symbols left, exiting")
                return
            time_mod.sleep(watch["poll_seconds"])


if __name__ == "__main__":
    main()

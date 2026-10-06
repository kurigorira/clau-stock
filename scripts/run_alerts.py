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
        # Multi-day streak alert, independent of the intraday one above.
        "streak_threshold_pct": float(raw.get("streak_threshold_pct", 5.0)),
        "streak_days": int(raw.get("streak_days", 2)),
        "streak_same_direction": bool(raw.get("streak_same_direction", True)),
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
    log.info(
        "alerts: streak = %d consecutive daily closes >= %.2f%% (%s)",
        watch["streak_days"],
        watch["streak_threshold_pct"],
        "same direction" if watch["streak_same_direction"] else "either direction",
    )
    log.info("alerts: symbols = %s", ", ".join(symbols))

    n_bars = watch["window_minutes"] + 2  # 1 extra to drop the still-forming bar
    # A symbol the terminal can never serve (not in this account's catalog,
    # no M1 history) would otherwise raise on every poll forever. Warn once
    # per symbol, then retire it after MAX_FAILS consecutive failures so the
    # log stays readable and the poll cycle stays fast.
    MAX_FAILS = 5
    fails: dict[str, int] = {}
    # Daily bars: days + 1 closes to get `days` changes, +1 for the bar still
    # forming today, which is sliced off - a partial day is not a day.
    n_days = watch["streak_days"] + 2
    # A daily condition stays true until the next bar closes, so a clock
    # throttle would re-send it all day. Key on the bar instead: one mail per
    # symbol per completed daily bar, which is the rate the signal changes at.
    streak_sent: dict[str, object] = {}
    # Separate from `fails`: a symbol the broker serves on M1 but not D1 keeps
    # its intraday alert and only loses the streak check.
    d1_fails: dict[str, int] = {}
    no_daily: set[str] = set()
    with connect(creds):
        while True:
            for sym in list(symbols):
                # The two checks are independent: a symbol can be quiet
                # intraday and still be two days into a run, so neither may
                # skip the other. They also fail independently - no daily
                # history must not cost a symbol the intraday alert that
                # already works for it.
                try:
                    raw = mt5_client.fetch_ohlcv(sym, "M1", n_bars)
                    fails.pop(sym, None)
                    closed = raw.iloc[:-1]  # drop the still-forming M1 bar
                    change = alerts.evaluate_change(sym, closed, watch["window_minutes"])
                    if change is not None and alerts.should_alert(
                        change.change_pct, watch["threshold_pct"]
                    ):
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
                        continue  # gone from the watchlist; nothing left to check

                if sym in no_daily:
                    continue
                try:
                    raw_d = mt5_client.fetch_ohlcv(sym, "D1", n_days)
                    d1_fails.pop(sym, None)
                    closed_d = raw_d.iloc[:-1]  # drop today's partial bar
                    if closed_d.empty:
                        continue
                    streak = alerts.evaluate_streak(
                        sym,
                        closed_d,
                        watch["streak_threshold_pct"],
                        days=watch["streak_days"],
                        same_direction=watch["streak_same_direction"],
                    )
                    if streak is None:
                        continue
                    bar = closed_d.index[-1]
                    if streak_sent.get(sym) == bar:
                        continue      # already reported for this daily bar
                    if notify.send_streak_mail(
                        symbol=streak.symbol,
                        changes=streak.changes,
                        total_pct=streak.total_pct,
                        current_price=streak.current_price,
                        start_price=streak.start_price,
                        threshold_pct=watch["streak_threshold_pct"],
                        log=log,
                    ):
                        streak_sent[sym] = bar
                except Exception as exc:  # noqa: BLE001
                    n = d1_fails[sym] = d1_fails.get(sym, 0) + 1
                    if n == 1:
                        log.warning("alerts: daily bars failed for %s: %s", sym, exc)
                    if n >= MAX_FAILS:
                        no_daily.add(sym)
                        log.warning(
                            "alerts: no streak checks for %s after %d failures; "
                            "its intraday alert is unaffected", sym, n,
                        )
            if not symbols:
                log.error("alerts: no watchable symbols left, exiting")
                return
            time_mod.sleep(watch["poll_seconds"])


if __name__ == "__main__":
    main()

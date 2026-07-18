"""Live-vs-backtest scorecard email.

For each launched symbol: pull the last N days of closed MT5 deals (live),
run the backtest on its data/*_h1.csv over the same recent window
(backtest), and compare profit factors. Flags symbols whose live edge has
decayed well below the backtest - the ones to review or drop.

Run weekly once ~30 days of live history exists (before that most rows read
"too-few"). Meant for Task Scheduler alongside review_fleet.bat.

Usage:
    python scripts/scorecard.py --account 1 --days 30
    python scripts/scorecard.py --account 1 --days 30 --dry-run
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader import report, scorecard  # noqa: E402
from gold_trader.backtest import run_backtest  # noqa: E402
from gold_trader.config import Config  # noqa: E402
from gold_trader.data import load_csv  # noqa: E402
from gold_trader.mt5_client import MT5Credentials, connect  # noqa: E402
from gold_trader.notify import _send_via_gmail  # noqa: E402
from gold_trader.screener import launched_strategies  # noqa: E402

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"
DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def _csv_for(symbol: str) -> Path | None:
    slug = re.sub(r"[^a-z0-9]", "_", symbol.lower())
    p = DATA_DIR / f"{slug}_h1.csv"
    return p if p.exists() else None


def _preset_for(symbol: str) -> Path | None:
    slug = re.sub(r"[^a-z0-9]", "_", symbol.lower())
    p = CONFIG_DIR / f"fib_{slug}.yaml"
    return p if p.exists() else None


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="live-vs-backtest scorecard")
    parser.add_argument("--account", default="1")
    parser.add_argument("--days", type=int, default=30, help="live history window")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_dotenv()
    log = logging.getLogger("scorecard")
    logging.basicConfig(level="INFO", format="%(asctime)s | %(levelname)-7s | %(message)s")

    repo_root = Path(__file__).resolve().parents[1]
    magic_index = report.load_magic_index(CONFIG_DIR)
    fleet = launched_strategies(repo_root)

    def strategy_of(magic: int) -> str:
        return report.strategy_of(magic, magic_index)

    suffix = f"_{args.account}"
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
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=args.days)
        deals = mt5.history_deals_get(start, now + timedelta(hours=1)) or []
        out_deals = [d for d in deals if d.entry == mt5.DEAL_ENTRY_OUT]

    live = scorecard.live_stats_from_deals(out_deals, strategy_of)

    # Backtest each live symbol over the same recent window from its CSV.
    backtest: dict[str, dict] = {}
    for s in live:
        csv = _csv_for(s.symbol)
        preset = _preset_for(s.symbol)
        if csv is None or preset is None:
            continue
        df = load_csv(csv)
        recent = df[df.index >= (df.index.max() - timedelta(days=args.days))]
        if len(recent) < 50:
            continue
        cfg = Config.from_yaml(preset)
        backtest[s.symbol] = run_backtest(recent, cfg)

    rows = scorecard.build_scorecard(live, backtest)
    window = f"{args.days}d to {now.strftime('%Y-%m-%d')} (acc{args.account})"
    subject, body = scorecard.format_scorecard(rows, window)
    print(body)

    if args.dry_run:
        print("[dry-run] email not sent")
        return
    sent = _send_via_gmail(subject, body, log)
    print("email sent" if sent else "email NOT sent (check GMAIL_* env vars)")


if __name__ == "__main__":
    main()

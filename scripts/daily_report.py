"""Twice-daily status email: balances, today's PnL, open positions, and a
strategy breakdown across all configured accounts.

Meant for Windows Task Scheduler (see README "Daily status email"), running
at 06:00 (overnight/US-session wrap-up) and 21:00 (pre-US-open snapshot).
Independent of the trading bots - reads live account state over MT5, so it
still reports on paused accounts (e.g. account 3) and on manually-placed
positions (magic 0 / unrecognized magics show up as "manual"/"unknown").

Usage:
    python scripts/daily_report.py                  # all of 1,2,3; sends email
    python scripts/daily_report.py --accounts 1 2
    python scripts/daily_report.py --dry-run         # print, don't send
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader import report  # noqa: E402
from gold_trader.mt5_client import MT5Credentials, connect  # noqa: E402
from gold_trader.notify import _send_via_gmail  # noqa: E402
from gold_trader.report import AccountReport  # noqa: E402


def _gather_account_report(account_id: str, creds: MT5Credentials, magic_index) -> AccountReport:
    with connect(creds) as mt5:
        info = mt5.account_info()
        if info is None:
            return AccountReport(account=account_id, error="account_info unavailable")
        equity, balance = float(info.equity), float(info.balance)

        positions_raw = mt5.positions_get() or []
        positions = [report.to_position_snapshot(p, magic_index) for p in positions_raw]
        unprotected = [p for p in positions if not p.sl or p.sl <= 0]

        now = datetime.now(timezone.utc)
        window_start = now - timedelta(days=2)
        deals = mt5.history_deals_get(window_start, now + timedelta(hours=1)) or []
        today_start_unix = int(
            now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        )
        out_deals = [
            d for d in deals if d.entry == mt5.DEAL_ENTRY_OUT and d.time >= today_start_unix
        ]
        closed_groups = report.group_closed_deals(out_deals, magic_index, equity)

    return AccountReport(
        account=account_id,
        equity=equity,
        balance=balance,
        realized_pnl_today=sum(g.pnl for g in closed_groups),
        trades_today=sum(g.trades for g in closed_groups),
        closed_groups=closed_groups,
        open_positions=positions,
        unprotected_positions=unprotected,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="clau-stock twice-daily status email")
    parser.add_argument("--accounts", nargs="*", default=["1", "2", "3"])
    parser.add_argument("--dry-run", action="store_true", help="print the report, don't email it")
    args = parser.parse_args()

    load_dotenv()
    log = logging.getLogger("daily_report")
    logging.basicConfig(level="INFO", format="%(asctime)s | %(levelname)-7s | %(message)s")

    repo_root = Path(__file__).resolve().parents[1]
    magic_index = report.load_magic_index(repo_root / "config")

    reports: list[AccountReport] = []
    for account_id in args.accounts:
        suffix = f"_{account_id}"
        try:
            creds = MT5Credentials(
                login=int(os.environ[f"MT5_LOGIN{suffix}"]),
                password=os.environ[f"MT5_PASSWORD{suffix}"],
                server=os.environ[f"MT5_SERVER{suffix}"],
                path=os.environ.get(f"MT5_PATH{suffix}") or None,
            )
        except KeyError as missing:
            reports.append(AccountReport(account=account_id, error=f"missing env var {missing}"))
            continue

        try:
            reports.append(_gather_account_report(account_id, creds, magic_index))
        except Exception as exc:  # noqa: BLE001
            log.exception(f"account {account_id} failed: {exc}")
            reports.append(AccountReport(account=account_id, error=str(exc)))

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    subject, body = report.format_report_email(reports, generated_at)
    print(body)

    if args.dry_run:
        print("[dry-run] email not sent")
        return

    sent = _send_via_gmail(subject, body, log)
    print("email sent" if sent else "email NOT sent (check GMAIL_* env vars)")


if __name__ == "__main__":
    main()

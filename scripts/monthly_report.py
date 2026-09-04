"""Monthly operating statistics for every Vantage account.

For each account: closed trades per calendar month (JST), win rate, profit
factor, gross profit/loss, net PnL, deposits/withdrawals, and reconstructed
end-of-month balances, plus a per-strategy breakdown. A closed position
counts as ONE trade (partial closes collapse) and its PnL includes
commission and swap on every deal of the position.

Each account's MT5 terminal must be running and logged in (they normally
are - the bots keep them open; start.bat opens the live terminal too).

Usage:
    python scripts/monthly_report.py                     # accounts 1 2 3 4
    python scripts/monthly_report.py --accounts 1 4
    python scripts/monthly_report.py --months 3
    python scripts/monthly_report.py --csv logs/monthly.csv
    python scripts/monthly_report.py --email             # send via GMAIL_*
"""
from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader import monthly, report  # noqa: E402
from gold_trader.monthly import JST, AccountMonthly  # noqa: E402
from gold_trader.mt5_client import MT5Credentials, connect  # noqa: E402
from gold_trader.notify import _send_via_gmail  # noqa: E402


def _window_start(months_back: int) -> datetime:
    """First day (JST midnight) of the month `months_back - 1` months ago,
    so --months 6 covers the current month plus the five before it."""
    now = datetime.now(JST)
    y, m = now.year, now.month
    for _ in range(months_back - 1):
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return datetime(y, m, 1, tzinfo=JST)


def _gather(account_id: str, creds: MT5Credentials, magic_index, start: datetime) -> AccountMonthly:
    with connect(creds) as mt5:
        info = mt5.account_info()
        if info is None:
            return AccountMonthly(account=account_id, error="account_info unavailable")
        balance = float(info.balance)
        login = int(info.login)
        deals = mt5.history_deals_get(
            start.astimezone(timezone.utc),
            datetime.now(timezone.utc) + timedelta(hours=1),
        ) or []

    trades, balance_ops = monthly.build_trades(list(deals), magic_index)
    months = monthly.monthly_stats(trades, balance_ops, balance_now=balance)
    return AccountMonthly(account=account_id, login=login, balance=balance, months=months)


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="clau-stock monthly operating statistics")
    parser.add_argument("--accounts", nargs="*", default=["1", "2", "3", "4"])
    parser.add_argument("--months", type=int, default=6, help="how many months back (default 6)")
    parser.add_argument("--csv", default=None, help="also write tidy per-month rows to this CSV")
    parser.add_argument(
        "--markdown",
        nargs="?",
        const="reports/monthly.md",
        default=None,
        metavar="PATH",
        help="also write a Markdown report (default path reports/monthly.md). "
        "Account logins are masked - see --show-logins",
    )
    parser.add_argument(
        "--show-logins",
        action="store_true",
        help="write full account numbers into the Markdown report instead of "
        "masking them. A login plus the server name identifies the account to "
        "anyone holding the password; leave this off for anything you publish",
    )
    parser.add_argument("--email", action="store_true", help="send the report via GMAIL_* env vars")
    args = parser.parse_args()

    load_dotenv()
    log = logging.getLogger("monthly_report")
    logging.basicConfig(level="INFO", format="%(asctime)s | %(levelname)-7s | %(message)s")

    repo_root = Path(__file__).resolve().parents[1]
    magic_index = report.load_magic_index(repo_root / "config")
    for sub in ("us_fleet", "us_fleet_a2", "us_fleet_a4"):
        d = repo_root / "config" / sub
        if d.is_dir():
            magic_index.update(report.load_magic_index(d))

    start = _window_start(args.months)
    reports: list[AccountMonthly] = []
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
            reports.append(AccountMonthly(account=account_id, error=f"missing env var {missing}"))
            continue
        try:
            reports.append(_gather(account_id, creds, magic_index, start))
        except Exception as exc:  # noqa: BLE001
            log.exception(f"account {account_id} failed: {exc}")
            reports.append(AccountMonthly(account=account_id, error=str(exc)))

    generated_at = datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")
    body = monthly.format_monthly_report(reports, generated_at)
    print(body)

    if args.csv:
        rows = monthly.monthly_csv_rows(reports)
        out = Path(args.csv)
        out.parent.mkdir(parents=True, exist_ok=True)
        fields = [
            "account", "login", "month", "trades", "wins", "win_rate_pct",
            "profit_factor", "gross_profit", "gross_loss", "net_pnl",
            "balance_ops", "end_balance",
        ]
        with out.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
        print(f"csv written: {out} ({len(rows)} rows)")

    if args.markdown:
        md = monthly.format_monthly_markdown(
            reports, generated_at, mask_logins=not args.show_logins
        )
        out = Path(args.markdown)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(md + "\n", encoding="utf-8")
        print(f"markdown written: {out}")

    if args.email:
        ok = [r for r in reports if r.error is None]
        subject = (
            f"[clau-stock monthly] {generated_at} | "
            f"{len(ok)}/{len(reports)} accounts OK"
        )
        sent = _send_via_gmail(subject, body, log)
        print("email sent" if sent else "email NOT sent (check GMAIL_* env vars)")


if __name__ == "__main__":
    main()

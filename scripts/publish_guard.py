"""Bookkeeping for scripts/publish_report.bat: once a day, and loudly when not.

The publisher used to run once, at 06:30. If the PC was asleep or an MT5
terminal was closed at that minute, that day simply had no report - and when
it failed every day for three weeks, nothing said so. This gives it two
things a batch file is bad at:

    is-done          exit 0 if today's report is already published, else 1.
                     Lets hourly retries do nothing once one run succeeds,
                     instead of committing the same report again.
    done             record that today's report is published (or was
                     already current).
    fail REASON      a run failed. After noon, if nothing has been published
                     today, email that fact - once per day - with the tail of
                     the log, so a stalled publisher is noticed the same day
                     rather than three weeks later.

Dates are the machine's local calendar day, which is what "today's report"
means to the person reading it.
"""
from __future__ import annotations

import logging
import sys
from datetime import date, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LOGS = REPO / "logs"
DONE = LOGS / "publish_done.txt"      # date of the last successful publish
MAILED = LOGS / "publish_mailed.txt"  # date a failure was last reported
LOG = LOGS / "publish_report.log"

# Before this hour a failure is not news: the 06:30 run can miss because a
# terminal was still starting, and the next retry usually succeeds. Mail only
# once the morning's retries have had their chance.
ALERT_FROM_HOUR = 12


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")


def is_done(today: date) -> bool:
    return _read(DONE) == today.isoformat()


def mark_done(today: date) -> None:
    _write(DONE, today.isoformat())


def log_tail(lines: int = 25) -> str:
    try:
        with LOG.open("rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - 16_000))
            text = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return "(no publish_report.log)"
    return "\n".join(text.splitlines()[-lines:])


def should_mail(now: datetime) -> bool:
    """A failure is worth an email once per day, after noon, if unpublished."""
    today = now.date()
    if now.hour < ALERT_FROM_HOUR:
        return False
    if is_done(today):
        return False           # an earlier run already published today
    return _read(MAILED) != today.isoformat()


def report_failure(reason: str, now: datetime, send=None) -> bool:
    """Email the failure if it is news. Returns True iff a mail went out."""
    if not should_mail(now):
        return False
    if send is None:
        from dotenv import load_dotenv
        sys.path.insert(0, str(REPO / "src"))
        from gold_trader.notify import _send_via_gmail

        load_dotenv(REPO / ".env")
        send = _send_via_gmail
    last = _read(DONE) or "never"
    subject = f"[clau-stock] daily report NOT published today ({now:%m/%d})"
    body = (
        f"The daily monthly-report publish has not succeeded today.\n\n"
        f"latest failure : {reason}\n"
        f"last published : {last}\n"
        f"retries        : hourly until 22:00 - this mail is sent once per day\n\n"
        f"How to read the log below:\n"
        f"  'cannot pull'        -> a tracked file has local edits (git status)\n"
        f"  'generation failed'  -> an MT5 terminal is closed or logged out\n"
        f"  'push failed'        -> network or GitHub credentials\n\n"
        f"--- tail of logs/publish_report.log ---\n{log_tail()}\n"
    )
    sent = send(subject, body, logging.getLogger("publish_guard"))
    if sent:
        _write(MAILED, now.date().isoformat())
    return bool(sent)


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    cmd, now = argv[0], datetime.now()
    if cmd == "is-done":
        return 0 if is_done(now.date()) else 1
    if cmd == "done":
        mark_done(now.date())
        return 0
    if cmd == "fail":
        reason = " ".join(argv[1:]) or "unspecified"
        if report_failure(reason, now):
            print("[publish_guard] failure mailed")
        return 0
    print(f"unknown command {cmd!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

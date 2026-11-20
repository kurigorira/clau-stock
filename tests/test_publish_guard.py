"""Once a day, and loudly when not.

The publisher ran once at 06:30 and failed silently for three weeks. These
pin the two behaviours that replaced that: retries that stop once a day's
report is out, and exactly one email when a day goes unpublished.
"""
import importlib.util
from datetime import datetime
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "publish_guard.py"


@pytest.fixture
def g(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("publish_guard", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "DONE", tmp_path / "publish_done.txt")
    monkeypatch.setattr(mod, "MAILED", tmp_path / "publish_mailed.txt")
    monkeypatch.setattr(mod, "LOG", tmp_path / "publish_report.log")
    return mod


MORNING = datetime(2026, 10, 27, 7, 0)
AFTERNOON = datetime(2026, 10, 27, 13, 0)


class Outbox:
    def __init__(self, ok=True):
        self.ok, self.sent = ok, []

    def __call__(self, subject, body, log):
        self.sent.append((subject, body))
        return self.ok


# --- once a day -------------------------------------------------------------

def test_nothing_is_done_before_the_first_publish(g):
    assert g.is_done(MORNING.date()) is False


def test_a_publish_marks_the_day_done(g):
    g.mark_done(MORNING.date())
    assert g.is_done(MORNING.date()) is True


def test_yesterdays_publish_does_not_count_for_today(g):
    g.mark_done(datetime(2026, 10, 26).date())
    assert g.is_done(MORNING.date()) is False


# --- loudly when not --------------------------------------------------------

def test_a_morning_failure_is_not_news(g):
    # the 06:30 run misses when a terminal is still starting; the 07:00
    # retry usually succeeds, so mailing now would be a false alarm
    out = Outbox()
    assert g.report_failure("generation failed", MORNING, send=out) is False
    assert out.sent == []


def test_an_afternoon_failure_with_nothing_published_is_mailed(g):
    out = Outbox()
    assert g.report_failure("generation failed", AFTERNOON, send=out) is True
    subject, body = out.sent[0]
    assert "NOT published" in subject
    assert "generation failed" in body


def test_it_is_mailed_once_per_day_not_once_per_retry(g):
    out = Outbox()
    g.report_failure("x", AFTERNOON, send=out)
    g.report_failure("x", AFTERNOON.replace(hour=14), send=out)
    g.report_failure("x", AFTERNOON.replace(hour=22), send=out)
    assert len(out.sent) == 1


def test_a_new_day_can_be_mailed_again(g):
    out = Outbox()
    g.report_failure("x", AFTERNOON, send=out)
    g.report_failure("x", datetime(2026, 10, 28, 13, 0), send=out)
    assert len(out.sent) == 2


def test_no_mail_once_an_earlier_run_published(g):
    # a failing retry after a successful run is harmless - today is covered
    g.mark_done(AFTERNOON.date())
    out = Outbox()
    assert g.report_failure("x", AFTERNOON, send=out) is False


def test_a_mail_that_did_not_send_is_tried_again_next_failure(g):
    # Gmail down or unconfigured: do not record it as reported
    first = Outbox(ok=False)
    g.report_failure("x", AFTERNOON, send=first)
    second = Outbox()
    assert g.report_failure("x", AFTERNOON.replace(hour=14), send=second) is True


def test_the_mail_carries_the_log_tail(g):
    g.LOG.write_text("line 1\ncannot pull with rebase\n", encoding="utf-8")
    out = Outbox()
    g.report_failure("git pull failed", AFTERNOON, send=out)
    assert "cannot pull with rebase" in out.sent[0][1]


def test_the_mail_says_when_it_last_worked(g):
    g.mark_done(datetime(2026, 10, 20).date())
    out = Outbox()
    g.report_failure("x", AFTERNOON, send=out)
    assert "2026-10-20" in out.sent[0][1]


# --- the command line the batch file uses -----------------------------------

def test_is_done_exit_codes(g):
    assert g.main(["is-done"]) == 1
    g.main(["done"])
    assert g.main(["is-done"]) == 0


def test_an_unknown_command_is_an_error(g):
    assert g.main(["nope"]) == 2

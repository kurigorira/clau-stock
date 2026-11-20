"""One mail per move.

A user got seventeen identical "BKNG +3.30% in 5min" mails: after the close
no new bar arrives, so the same window stayed at +3.30% and was mailed again
every time the cooldown expired, all night. These pin the fix.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader.alerts import MoveGate  # noqa: E402

T = 3.0


def bar(minute):
    return pd.Timestamp("2026-11-09 20:00", tz="UTC") + pd.Timedelta(minutes=minute)


def test_the_same_bars_all_night_are_mailed_once():
    # the screenshot: market closed, the last window frozen at +3.30%
    g = MoveGate()
    mails = sum(g.is_news("BKNG", bar(0), 3.30, T) for _ in range(1000))
    assert mails == 1


def test_a_move_that_persists_over_new_bars_is_mailed_once():
    # the 5-minute window slides with the move, so it stays over the
    # threshold for several bars - that is still one move
    g = MoveGate()
    mails = sum(g.is_news("BKNG", bar(i), 3.3 + i * 0.1, T) for i in range(10))
    assert mails == 1


def test_after_the_move_fades_the_next_one_is_mailed():
    g = MoveGate()
    assert g.is_news("BKNG", bar(0), 3.3, T) is True
    assert g.is_news("BKNG", bar(1), 1.0, T) is False    # back under: re-armed
    assert g.is_news("BKNG", bar(2), 3.5, T) is True     # a new move


def test_a_reversal_is_a_new_move():
    g = MoveGate()
    assert g.is_news("BKNG", bar(0), 3.3, T) is True
    assert g.is_news("BKNG", bar(1), -3.4, T) is True


def test_a_small_move_is_never_mailed():
    g = MoveGate()
    assert not any(g.is_news("BKNG", bar(i), 1.0, T) for i in range(10))


def test_symbols_are_independent():
    g = MoveGate()
    assert g.is_news("BKNG", bar(0), 3.3, T) is True
    assert g.is_news("NVDA", bar(0), 3.3, T) is True
    assert g.is_news("BKNG", bar(1), 3.3, T) is False


def test_not_enough_bars_is_not_news_and_does_not_block_later():
    g = MoveGate()
    assert g.is_news("BKNG", bar(0), None, T) is False
    assert g.is_news("BKNG", bar(1), 3.3, T) is True

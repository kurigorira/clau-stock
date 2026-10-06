"""Two days in a row, each moving 5%: a run, not a wobble.

The intraday alert answers "did this just jump?". This answers "has this
been going somewhere for days?", which is a different question and must not
be able to suppress or be suppressed by the other.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader.alerts import (  # noqa: E402
    daily_changes,
    evaluate_streak,
)


def _bars(*closes):
    """Daily bars from a list of closes (oldest first)."""
    idx = pd.date_range("2026-10-01", periods=len(closes), freq="D")
    return pd.DataFrame({"close": list(closes)}, index=idx)


def _streak(*closes, threshold=5.0, days=2, same=True):
    return evaluate_streak("X", _bars(*closes), threshold, days=days,
                           same_direction=same)


# --- daily_changes ----------------------------------------------------------

def test_changes_are_close_to_close():
    # an overnight gap is part of the day's move for anyone holding through it
    assert daily_changes(_bars(100.0, 110.0, 99.0)) == pytest.approx([10.0, -10.0])


def test_a_zero_close_yields_nan_rather_than_a_division_error():
    assert pd.isna(daily_changes(_bars(0.0, 100.0))[0])


# --- the streak itself ------------------------------------------------------

def test_two_days_up_over_the_threshold_fires():
    s = _streak(100.0, 106.0, 112.0)
    assert s is not None
    assert s.days == 2
    assert s.direction == "up"
    assert s.changes == pytest.approx([6.0, 5.66], abs=0.01)


def test_two_days_down_over_the_threshold_fires():
    s = _streak(100.0, 94.0, 88.0)
    assert s is not None and s.direction == "down"


def test_one_big_day_is_not_a_streak():
    assert _streak(100.0, 100.5, 110.0) is None


def test_a_day_under_the_threshold_breaks_it():
    # 6% then 4%: the run stopped, which is the point of asking
    assert _streak(100.0, 106.0, 110.24) is None


def test_up_then_down_is_volatility_not_a_run():
    # +6% then -6% nets out near zero; alerting on it would be noise
    assert _streak(100.0, 106.0, 99.64) is None


def test_up_then_down_does_fire_when_direction_is_not_required():
    assert _streak(100.0, 106.0, 99.64, same=False) is not None


def test_exactly_at_the_threshold_counts():
    s = _streak(100.0, 105.0, 110.25)
    assert s is not None


# --- the total --------------------------------------------------------------

def test_the_total_compounds_rather_than_summing():
    # two +5% days are +10.25%, not +10%: the second is on the bigger number
    s = _streak(100.0, 105.0, 110.25)
    assert s.total_pct == pytest.approx(10.25)
    assert s.total_pct != pytest.approx(sum(s.changes))


def test_the_total_is_measured_from_before_the_streak_began():
    s = _streak(50.0, 100.0, 106.0, 112.36)
    assert s.start_price == 100.0      # not 50.0, which is outside the run
    assert s.total_pct == pytest.approx(12.36)


# --- shape and guards -------------------------------------------------------

def test_a_longer_streak_is_configurable():
    assert _streak(100.0, 106.0, 112.0, days=3) is None
    assert _streak(100.0, 106.0, 112.0, 119.0, days=3) is not None


def test_not_enough_bars_is_silent_rather_than_an_error():
    assert _streak(100.0) is None
    assert _streak(100.0, 106.0, days=2) is None


def test_a_gap_in_the_data_does_not_fire():
    assert _streak(0.0, 106.0, 112.0) is None


def test_zero_days_is_refused():
    assert _streak(100.0, 106.0, 112.0, days=0) is None


def test_only_the_last_n_days_are_judged():
    # a quiet week before the run must not break it
    s = _streak(100.0, 100.1, 100.2, 106.2, 112.6)
    assert s is not None and s.days == 2

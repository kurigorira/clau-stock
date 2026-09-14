import sys
from math import sqrt
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader.phenomena import (  # noqa: E402
    cross_sectional_reversal,
    expected_max_sharpe,
    overnight_intraday,
    session_frame,
    summarize,
)


def _sessions(closes, opens=None, start="2026-01-05", bars=7):
    """One symbol: `bars` H1 bars per weekday, given per-session open/close."""
    opens = opens if opens is not None else closes
    days = pd.bdate_range(start, periods=len(closes), tz="UTC")
    idx, o, h, lo, c = [], [], [], [], []
    for d, op, cl in zip(days, opens, closes):
        for k in range(bars):
            idx.append(d + pd.Timedelta(hours=14 + k))
            first, last = k == 0, k == bars - 1
            price = op if first else cl
            o.append(op if first else price)
            c.append(cl if last else price)
            h.append(max(op, cl) + 0.5)
            lo.append(min(op, cl) - 0.5)
    return pd.DataFrame({"open": o, "high": h, "low": lo, "close": c,
                         "volume": 100}, index=pd.DatetimeIndex(idx))


# --- summarize --------------------------------------------------------------

def test_summarize_basic_moments():
    s = summarize([0.01, -0.01, 0.02, 0.0], periods_per_year=252)
    assert s.n == 4
    assert s.mean == pytest.approx(0.005)
    assert s.win_rate == 0.5              # zero is not a win
    assert s.total == pytest.approx(0.02)


def test_summarize_t_and_sharpe_relate_as_expected():
    rng = np.random.default_rng(0)
    r = rng.normal(0.001, 0.01, 500)
    s = summarize(r, periods_per_year=252)
    assert s.t_stat == pytest.approx(s.mean / (s.std / sqrt(s.n)))
    assert s.sharpe == pytest.approx(s.mean / s.std * sqrt(252))


def test_summarize_handles_empty_and_constant():
    assert summarize([]).n == 0
    flat = summarize([0.01, 0.01, 0.01])
    assert flat.std == 0.0 and flat.t_stat == 0.0 and flat.sharpe == 0.0


def test_summarize_drops_nan():
    assert summarize([0.01, float("nan"), 0.03]).n == 2


# --- the multiple-testing bar ----------------------------------------------

def test_more_trials_raise_the_bar():
    a = expected_max_sharpe(5, 500)
    b = expected_max_sharpe(50, 500)
    assert 0 < a < b


def test_more_data_lowers_the_bar():
    short = expected_max_sharpe(20, 100)
    long = expected_max_sharpe(20, 2000)
    assert short > long > 0


def test_a_single_trial_sets_no_bar():
    assert expected_max_sharpe(1, 500) == 0.0
    assert expected_max_sharpe(20, 1) == 0.0


def test_the_bar_is_reached_by_noise():
    # the whole point: run N worthless variants and the best one clears zero
    rng = np.random.default_rng(7)
    n_obs, n_trials = 400, 20
    best = max(summarize(rng.normal(0, 0.01, n_obs)).sharpe for _ in range(n_trials))
    bar = expected_max_sharpe(n_trials, n_obs)
    assert best > 0                       # pure noise still looks profitable
    assert abs(best - bar) < bar          # and lands in the region the bar predicts


# --- session decomposition --------------------------------------------------

def test_session_frame_splits_the_two_legs():
    #        day1        day2
    # open   100         110
    # close  105         120
    s = session_frame(_sessions(closes=[105, 120], opens=[100, 110]))
    assert len(s) == 2
    assert s["intraday"].iloc[0] == pytest.approx(105 / 100 - 1)
    assert s["overnight"].iloc[0] == pytest.approx(110 / 105 - 1)
    assert np.isnan(s["overnight"].iloc[-1])   # no next session to pair with


def test_session_frame_on_empty_input():
    assert session_frame(pd.DataFrame()).empty


def test_overnight_leg_is_isolated_from_the_intraday_one():
    # price only ever moves overnight: intraday must measure exactly zero
    opens = [100, 110, 120, 130]
    s = overnight_intraday({"X": _sessions(closes=opens, opens=opens)})
    over, intra, _ = s
    assert intra.mean == pytest.approx(0.0)
    assert over.mean > 0


def test_costs_are_charged_on_both_sides():
    opens = [100, 110, 120, 130]
    frames = {"X": _sessions(closes=opens, opens=opens)}
    free, _, _ = overnight_intraday(frames, cost_bp=0.0)
    paid, _, _ = overnight_intraday(frames, cost_bp=5.0)
    assert free.mean - paid.mean == pytest.approx(2 * 5.0 / 10_000)


# --- cross-sectional reversal ----------------------------------------------

def _reverting_universe(n_days=60, n_sym=10, seed=1):
    """Yesterday's move is undone today: reversal must find it."""
    rng = np.random.default_rng(seed)
    shocks = rng.normal(0, 0.02, (n_days, n_sym))
    px = np.full((n_days, n_sym), 100.0)
    for d in range(1, n_days):
        px[d] = px[d - 1] * (1 + shocks[d] - 0.9 * shocks[d - 1])
    return {f"S{j}": _sessions(closes=px[:, j].tolist(),
                               opens=px[:, j].tolist()) for j in range(n_sym)}


def test_reversal_is_found_where_it_exists():
    st, n_sym = cross_sectional_reversal(_reverting_universe())
    assert n_sym == 10
    assert st.n > 40
    assert st.mean > 0 and st.t_stat > 2


def test_reversal_is_absent_from_a_random_walk():
    rng = np.random.default_rng(4)
    px = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, (80, 10)), axis=0))
    frames = {f"S{j}": _sessions(closes=px[:, j].tolist(), opens=px[:, j].tolist())
              for j in range(10)}
    st, _ = cross_sectional_reversal(frames)
    assert abs(st.t_stat) < 2.5           # nothing to find


def test_reversal_needs_a_universe():
    st, n = cross_sectional_reversal({"A": _sessions([100, 101, 102])})
    assert st.n == 0 and n == 0


def test_reversal_costs_reduce_every_day():
    frames = _reverting_universe()
    free, _ = cross_sectional_reversal(frames, cost_bp=0.0)
    paid, _ = cross_sectional_reversal(frames, cost_bp=5.0)
    assert free.mean - paid.mean == pytest.approx(2 * 5.0 / 10_000)
    assert paid.n == free.n

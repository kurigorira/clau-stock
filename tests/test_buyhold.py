import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader.buyhold import plan_targets, round_volume  # noqa: E402


def _meta(step=0.01, vmin=0.01, vmax=1000.0, size=1.0):
    return {"volume_step": step, "volume_min": vmin, "volume_max": vmax,
            "contract_size": size}


# --- round_volume -----------------------------------------------------------

def test_rounds_down_to_the_step():
    # 1.237 lots on a 0.1 step is 1.2, never 1.3: across 100 symbols every
    # rounding-up would add exposure that was never asked for
    assert round_volume(1.237, _meta(step=0.1, vmin=0.1)) == pytest.approx(1.2)


def test_an_exact_multiple_survives():
    assert round_volume(1.5, _meta(step=0.5, vmin=0.5)) == pytest.approx(1.5)
    assert round_volume(0.3, _meta(step=0.1, vmin=0.1)) == pytest.approx(0.3)


def test_below_the_minimum_is_zero_not_the_minimum():
    # a symbol too expensive for its slot is skipped, not overweighted
    assert round_volume(0.004, _meta(step=0.01, vmin=0.01)) == 0.0


def test_the_maximum_caps_it():
    assert round_volume(5000.0, _meta(step=1.0, vmin=1.0, vmax=100.0)) == 100.0


def test_degenerate_inputs():
    assert round_volume(0.0, _meta()) == 0.0
    assert round_volume(-1.0, _meta()) == 0.0
    assert round_volume(1.0, {"volume_step": 0}) == 0.0


# --- plan_targets -----------------------------------------------------------

def test_equal_weight_splits_the_exposure():
    quotes = {"A": (100.0, _meta()), "B": (50.0, _meta()), "C": (25.0, _meta())}
    plan = plan_targets(quotes, equity=30_000.0)
    # 10,000 per symbol at 1.0x
    by = {t.symbol: t for t in plan}
    assert by["A"].volume == pytest.approx(100.0)
    assert by["B"].volume == pytest.approx(200.0)
    assert by["C"].volume == pytest.approx(400.0)
    for t in plan:
        assert t.notional == pytest.approx(10_000.0)


def test_exposure_scales_the_whole_book():
    quotes = {"A": (100.0, _meta()), "B": (100.0, _meta())}
    one = sum(t.notional for t in plan_targets(quotes, 10_000.0, exposure=1.0))
    two = sum(t.notional for t in plan_targets(quotes, 10_000.0, exposure=2.0))
    assert one == pytest.approx(10_000.0)
    assert two == pytest.approx(20_000.0)


def test_contract_size_is_part_of_the_notional():
    # 1 lot = 100 shares: a 10,000 slot buys a tenth of what it would at 1:1
    quotes = {"A": (100.0, _meta(size=100.0))}
    t = plan_targets(quotes, 10_000.0)[0]
    assert t.volume == pytest.approx(1.0)
    assert t.notional == pytest.approx(10_000.0)


def test_existing_holdings_are_topped_up_not_doubled():
    quotes = {"A": (100.0, _meta())}
    t = plan_targets(quotes, 10_000.0, held={"A": 40.0})[0]
    assert t.volume == pytest.approx(100.0)   # target unchanged
    assert t.to_buy == pytest.approx(60.0)    # only the gap


def test_a_position_at_target_buys_nothing():
    quotes = {"A": (100.0, _meta())}
    t = plan_targets(quotes, 10_000.0, held={"A": 100.0})[0]
    assert t.to_buy == 0.0
    assert t.skip == "already at target"


def test_an_overweight_position_is_not_sold():
    # this builds a book, it does not trim one; selling is a decision to make
    # deliberately rather than a side effect of a re-run
    quotes = {"A": (100.0, _meta())}
    t = plan_targets(quotes, 10_000.0, held={"A": 500.0})[0]
    assert t.to_buy == 0.0


def test_a_symbol_too_expensive_for_its_slot_is_skipped_with_a_reason():
    # one lot costs 50,000; the slot is 1,000
    quotes = {"BIG": (500.0, _meta(step=100.0, vmin=100.0))}
    t = plan_targets(quotes, 1_000.0)[0]
    assert t.volume == 0.0 and t.to_buy == 0.0
    assert "one lot" in t.skip


def test_a_dead_quote_is_reported_not_sized():
    t = plan_targets({"X": (0.0, _meta())}, 10_000.0)[0]
    assert t.volume == 0.0 and t.skip == "no quote"


def test_no_equity_and_no_symbols_plan_nothing():
    assert plan_targets({}, 10_000.0) == []
    assert plan_targets({"A": (100.0, _meta())}, 0.0) == []

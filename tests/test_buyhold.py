import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader.buyhold import plan_targets, round_volume  # noqa: E402


def _meta(step=0.01, vmin=0.01, vmax=1000.0, size=1.0):
    """`size` is the ACCOUNT-currency value of 1.0 of price, per lot.

    Expressed the way the broker gives it: one lot moving by tick_size earns
    tick_value in the account currency, so tick_value/tick_size == size. The
    contract size alone is in the symbol's QUOTE currency and sizing a JPY
    account with it asked for 150x the intended book.
    """
    return {"volume_step": step, "volume_min": vmin, "volume_max": vmax,
            "trade_tick_size": 0.01, "trade_tick_value": 0.01 * size}


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


def test_the_per_lot_value_is_part_of_the_notional():
    # 1 lot = 100 units: a 10,000 slot buys a tenth of what it would at 1:1
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


# --- currency: the bug that asked for 150x the account ----------------------

def test_sizing_uses_the_account_currency_not_the_quote_currency():
    # A JPY account, a USD-priced symbol at 500, USDJPY 150. One lot moves
    # 1.0 of price -> 150 JPY, so a 7,500 JPY slot buys 0.1 lots, NOT the
    # 15 lots that dividing 7,500 by the raw USD price would give.
    meta = _meta(step=0.01, vmin=0.01)
    meta["trade_tick_size"] = 0.01
    meta["trade_tick_value"] = 1.5          # 0.01 of price -> 1.5 JPY
    t = plan_targets({"A": (500.0, meta)}, 7_500.0)[0]
    assert t.volume == pytest.approx(0.1)
    assert t.notional == pytest.approx(7_500.0)


def test_the_whole_book_stays_at_the_requested_exposure():
    # the failure was a book 150x equity that the plan printed as "1.00x"
    metas = {}
    for name, px in (("A", 503.76), ("B", 223.61), ("C", 42.0)):
        m = _meta(step=0.01, vmin=0.01)
        m["trade_tick_size"], m["trade_tick_value"] = 0.01, 1.5
        metas[name] = (px, m)
    equity = 700_000.0
    plan = plan_targets(metas, equity, exposure=1.0)
    total = sum(t.notional for t in plan)
    # rounding down to the lot step can only undershoot, never overshoot
    assert total <= equity * 1.0 + 1e-6
    assert total > equity * 0.95


def test_a_symbol_with_no_tick_value_is_skipped_and_says_why():
    # no conversion means no way to know what a lot costs in this account's
    # money; guessing is exactly how the 150x happened
    meta = _meta()
    meta["trade_tick_value"] = 0
    t = plan_targets({"A": (100.0, meta)}, 10_000.0)[0]
    assert t.volume == 0.0 and t.to_buy == 0.0
    assert "tick value" in t.skip


# --- the slot: a skipped symbol must not take its budget with it ------------

def _px(price, unit=150.0, vmin=0.01, step=0.01):
    m = _meta(step=step, vmin=vmin, size=unit)
    return (price, m)


def test_an_unaffordable_symbol_does_not_strand_its_share():
    # one name needs a whole 1,000-unit lot; the other two are cheap. The
    # expensive one is skipped either way - but its share must go to the
    # two that can use it, not sit in cash.
    quotes = {
        "BIG": _px(500.0, unit=150.0, vmin=1.0, step=1.0),   # 1 lot = 75,000
        "A": _px(100.0), "B": _px(50.0),
    }
    plan = plan_targets(quotes, 30_000.0, exposure=1.0)
    by = {t.symbol: t for t in plan}
    assert by["BIG"].volume == 0.0          # still unaffordable
    total = sum(t.notional for t in plan)
    # 30,000 over the two that fit, not 30,000 over three with a third lost
    assert total > 30_000.0 * 0.95
    assert by["A"].notional == pytest.approx(by["B"].notional, rel=0.02)


def test_the_book_never_exceeds_the_requested_exposure():
    quotes = {f"S{i}": _px(100.0 + i) for i in range(20)}
    for exposure in (0.5, 1.0, 2.0):
        total = sum(t.notional for t in
                    plan_targets(quotes, 500_000.0, exposure=exposure))
        assert total <= 500_000.0 * exposure + 1e-6


def test_equal_weight_still_holds_among_the_symbols_bought():
    quotes = {"A": _px(100.0), "B": _px(50.0), "C": _px(25.0)}
    plan = plan_targets(quotes, 30_000.0)
    notionals = [t.notional for t in plan if t.volume > 0]
    assert len(notionals) == 3
    assert max(notionals) == pytest.approx(min(notionals), rel=0.02)


def test_when_nothing_is_affordable_nothing_is_bought():
    quotes = {"BIG": _px(500.0, unit=150.0, vmin=10.0, step=10.0)}
    plan = plan_targets(quotes, 1_000.0)
    assert all(t.volume == 0.0 for t in plan)
    assert sum(t.notional for t in plan) == 0.0

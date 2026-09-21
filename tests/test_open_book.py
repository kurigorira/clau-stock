"""The open book: what a report of closed trades alone cannot show.

Buy and hold closes nothing, so every realized-PnL table reads "0 trades"
forever while swap is charged on the full notional every night. These cover
the aggregation and, more importantly, the refusals: no contract size means
no notional rather than a guessed one, and a position too new to have paid a
rollover does not get averaged into the financing rate.
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader.config import Config  # noqa: E402
from gold_trader.monthly import (  # noqa: E402
    JST,
    AccountMonthly,
    build_open_positions,
    format_monthly_markdown,
    format_monthly_report,
    group_open,
    swap_drag,
)

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=JST)


# a magic with no special meaning: BUYHOLD_MAGIC is reserved and would make
# these read as the held book rather than as an arbitrary preset
def _pos(symbol="AAPL", magic=4242, volume=1.0, days_ago=10.0,
         profit=0.0, swap=0.0, price=100.0):
    opened = NOW - timedelta(days=days_ago)
    return SimpleNamespace(
        symbol=symbol, magic=magic, volume=volume,
        time=int(opened.timestamp()), profit=profit, swap=swap,
        price_current=price,
    )


def _cfg(strategy):
    return SimpleNamespace(strategy=strategy)


# --- build_open_positions ---------------------------------------------------

def test_unrealised_is_profit_plus_swap():
    # MT5 reports position.profit WITHOUT swap; closing now would net both
    rows = build_open_positions([_pos(profit=500.0, swap=-120.0)], {})
    assert rows[0].profit == 500.0
    assert rows[0].swap == -120.0
    assert rows[0].unrealised == 380.0


def test_notional_uses_the_contract_size():
    rows = build_open_positions(
        [_pos(volume=2.0, price=150.0)], {}, {"AAPL": 100.0}
    )
    assert rows[0].notional == 2.0 * 100.0 * 150.0


def test_an_unknown_contract_size_gives_no_notional_not_a_guess():
    # a wrong contract size is wrong by whatever factor the broker uses;
    # reporting "-" is honest, reporting volume*price would not be
    rows = build_open_positions([_pos(volume=2.0, price=150.0)], {}, {})
    assert rows[0].notional == 0.0


def test_strategy_comes_from_the_symbol_and_magic_pair():
    index = {("AAPL", 4242): _cfg("donchian")}
    rows = build_open_positions([_pos()], index)
    assert rows[0].strategy == "donchian"


def test_a_magic_owned_by_another_symbol_does_not_claim_this_one():
    # the collision that corrupted the reports once already: same magic,
    # different symbol, and it must not inherit the strategy
    index = {("MSFT", 4242): _cfg("donchian")}
    rows = build_open_positions([_pos(symbol="AAPL")], index)
    assert rows[0].strategy == "unknown"


def test_balance_entries_are_not_positions():
    assert build_open_positions([SimpleNamespace(symbol="", magic=0)], {}) == []


# --- group_open -------------------------------------------------------------

def test_groups_sum_per_strategy_and_keep_the_oldest():
    index = {("AAPL", 1): _cfg("buyhold"), ("MSFT", 1): _cfg("buyhold")}
    rows = build_open_positions(
        [
            _pos(symbol="AAPL", magic=1, profit=100.0, swap=-10.0, days_ago=30),
            _pos(symbol="MSFT", magic=1, profit=-40.0, swap=-5.0, days_ago=3),
        ],
        index,
        {"AAPL": 1.0, "MSFT": 1.0},
    )
    groups = group_open(rows)
    assert len(groups) == 1
    g = groups[0]
    assert g.strategy == "buyhold" and g.positions == 2
    assert g.profit == 60.0 and g.swap == -15.0
    assert g.unrealised == 45.0
    assert g.oldest == NOW - timedelta(days=30)


def test_distinct_strategies_stay_apart_and_sort():
    index = {("AAPL", 1): _cfg("buyhold"), ("MSFT", 2): _cfg("macd")}
    rows = build_open_positions(
        [_pos(symbol="MSFT", magic=2), _pos(symbol="AAPL", magic=1)], index
    )
    assert [g.strategy for g in group_open(rows)] == ["buyhold", "macd"]


# --- swap_drag --------------------------------------------------------------

def test_the_daily_rate_is_the_swap_over_the_days_held():
    rows = build_open_positions(
        [_pos(swap=-100.0, days_ago=10.0)], {}, {"AAPL": 1.0}
    )
    d = swap_drag(rows, NOW)
    assert d.counted == 1 and d.too_new == 0
    assert d.per_day == -10.0
    assert d.annual == -3650.0


def test_a_position_too_new_to_have_paid_is_excluded_not_averaged_in():
    # opened this morning: swap 0 because no rollover has happened, and
    # averaging that in would report the book as cheaper than it is
    rows = build_open_positions(
        [_pos(swap=-100.0, days_ago=10.0), _pos(swap=0.0, days_ago=0.2)],
        {}, {"AAPL": 1.0},
    )
    d = swap_drag(rows, NOW)
    assert d.counted == 1 and d.too_new == 1
    assert d.per_day == -10.0  # not -5.0


def test_annual_pct_is_against_the_notional_it_is_charged_on():
    rows = build_open_positions(
        [_pos(volume=1.0, price=1000.0, swap=-73.0, days_ago=10.0)],
        {}, {"AAPL": 1.0},
    )
    d = swap_drag(rows, NOW)
    # -7.3/day * 365 = -2,664.50 on a 1,000 notional
    assert d.notional == 1000.0
    assert d.annual_pct is not None
    assert d.annual_pct == pytest.approx(-266.45)


def test_no_notional_means_no_percentage_rather_than_a_division_by_zero():
    rows = build_open_positions([_pos(swap=-10.0, days_ago=5.0)], {}, {})
    assert swap_drag(rows, NOW).annual_pct is None


def test_an_all_new_book_reports_nothing_measurable():
    rows = build_open_positions([_pos(days_ago=0.1)], {}, {"AAPL": 1.0})
    d = swap_drag(rows, NOW)
    assert d.counted == 0 and d.too_new == 1


# --- rendering --------------------------------------------------------------

def _account_with_open():
    index = {("AAPL", 1): _cfg("buyhold")}
    rows = build_open_positions(
        [_pos(symbol="AAPL", magic=1, profit=900.0, swap=-100.0, days_ago=10.0)],
        index, {"AAPL": 1.0},
    )
    return AccountMonthly(
        account="1", login=100001, balance=50_000.0, months=[],
        open_groups=group_open(rows), drag=swap_drag(rows, NOW),
    )


def test_the_text_report_shows_the_open_book_and_its_financing():
    out = format_monthly_report([_account_with_open()], "now")
    assert "open positions" in out
    assert "buyhold" in out
    assert "financing" in out


def test_the_markdown_says_the_open_book_is_not_in_the_tables_above():
    md = format_monthly_markdown([_account_with_open()], "now")
    assert "Open positions" in md
    assert "not" in md and "realized" in md
    assert "Financing" in md


def test_an_account_with_nothing_open_gains_no_section():
    plain = AccountMonthly(account="1", login=100001, balance=1.0, months=[])
    assert "open positions" not in format_monthly_report([plain], "now")
    assert "Open positions" not in format_monthly_markdown([plain], "now")


def test_the_markdown_still_masks_the_login_in_the_open_section():
    md = format_monthly_markdown([_account_with_open()], "now")
    assert "100001" not in md
    assert "***001" in md


def test_the_buy_and_hold_magic_has_a_name_of_its_own():
    # nothing in config/ describes this book, so without an explicit name
    # every held position would report as "unknown" - the exact blind spot
    # this section exists to remove
    from gold_trader.buyhold import BUYHOLD_MAGIC

    rows = build_open_positions([_pos(symbol="AAPL", magic=BUYHOLD_MAGIC)], {})
    assert rows[0].strategy == "buyhold"


def test_a_real_preset_still_wins_over_the_buyhold_default():
    from gold_trader.buyhold import BUYHOLD_MAGIC

    index = {("AAPL", BUYHOLD_MAGIC): _cfg("macd")}
    rows = build_open_positions([_pos(symbol="AAPL", magic=BUYHOLD_MAGIC)], index)
    assert rows[0].strategy == "macd"

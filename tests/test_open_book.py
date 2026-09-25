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
    carry_rows,
    unit_value,
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


def test_notional_uses_the_account_currency_conversion():
    rows = build_open_positions(
        [_pos(volume=2.0, price=150.0)], {}, {"AAPL": 100.0}
    )
    assert rows[0].notional == 2.0 * 100.0 * 150.0


def test_an_unknown_conversion_gives_no_notional_not_a_guess():
    # a notional in the wrong currency is wrong by whatever the FX rate is;
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
    # 100,000 notional paying 20/day -> 7,300/yr -> 7.3%, a rate a broker
    # could plausibly charge
    rows = build_open_positions(
        [_pos(volume=1.0, price=100_000.0, swap=-200.0, days_ago=10.0)],
        {}, {"AAPL": 1.0},
    )
    d = swap_drag(rows, NOW)
    assert d.notional == 100_000.0
    assert d.annual_pct == pytest.approx(-7.3)


def test_no_notional_means_no_percentage_rather_than_a_division_by_zero():
    rows = build_open_positions([_pos(swap=-10.0, days_ago=5.0)], {}, {})
    assert swap_drag(rows, NOW).annual_pct is None


def test_an_impossible_rate_is_withheld_rather_than_published():
    # the first version divided a JPY swap by a USD notional and published
    # -536%/yr as though it were a fact. No broker charges that; such a
    # number means the two figures are in different currencies.
    rows = build_open_positions(
        [_pos(volume=1.0, price=1_000.0, swap=-73.0, days_ago=10.0)],
        {}, {"AAPL": 1.0},
    )
    d = swap_drag(rows, NOW)
    assert d.notional == 1_000.0      # a notional does exist
    assert d.annual_pct is None       # but the rate it implies is impossible
    assert d.rate_withheld is True


def test_a_missing_notional_is_not_reported_as_a_withheld_rate():
    # nothing to divide by is a different condition from an absurd answer,
    # and only the second one signals a data problem worth naming
    rows = build_open_positions([_pos(swap=-10.0, days_ago=5.0)], {}, {})
    assert swap_drag(rows, NOW).rate_withheld is False


def test_the_report_says_when_it_withheld_the_rate():
    rows = build_open_positions(
        [_pos(volume=1.0, price=1_000.0, swap=-73.0, days_ago=10.0)],
        {}, {"AAPL": 1.0},
    )
    r = AccountMonthly(account="1", login=100001, balance=50_000.0, months=[],
                       open_groups=group_open(rows), drag=swap_drag(rows, NOW))
    assert "withheld" in format_monthly_report([r], "now")
    assert "withheld" in format_monthly_markdown([r], "now")


# --- unit_value -------------------------------------------------------------

def test_unit_value_converts_via_the_brokers_own_tick_value():
    # one lot moving by tick_size earns tick_value in the ACCOUNT currency,
    # so tick_value/tick_size is the account-currency exposure per 1.0 of
    # price - conversion and contract size in one number
    assert unit_value({"trade_tick_value": 150.0, "trade_tick_size": 0.01}) == 15_000.0


def test_unit_value_refuses_to_guess_when_the_broker_gives_nothing():
    for meta in ({}, {"trade_tick_value": 0, "trade_tick_size": 0.01},
                 {"trade_tick_value": 150.0, "trade_tick_size": 0},
                 {"trade_tick_value": None, "trade_tick_size": None}):
        assert unit_value(meta) == 0.0


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


# --- swap as evidence, not the clock ----------------------------------------

def test_a_position_that_has_paid_swap_is_counted_whatever_the_clock_says():
    # the broker only charges swap at a rollover, so a nonzero swap IS one.
    # The report once claimed nothing had been charged while the swap column
    # filled up, because it went by apparent age alone.
    rows = build_open_positions(
        [_pos(swap=-50.0, days_ago=0.4)], {}, {"AAPL": 1.0}
    )
    d = swap_drag(rows, NOW)
    assert d.counted == 1 and d.too_new == 0
    assert d.per_day == pytest.approx(-125.0)   # -50 over 0.4 days


def test_a_young_position_with_no_swap_is_still_too_new():
    rows = build_open_positions(
        [_pos(swap=0.0, days_ago=0.4)], {}, {"AAPL": 1.0}
    )
    d = swap_drag(rows, NOW)
    assert d.counted == 0 and d.too_new == 1


def test_an_old_position_with_no_swap_counts_as_genuinely_free():
    # held for days and charged nothing: that is a swap-free symbol, and
    # excluding it would overstate the book's cost
    rows = build_open_positions(
        [_pos(swap=0.0, days_ago=9.0)], {}, {"AAPL": 1.0}
    )
    d = swap_drag(rows, NOW)
    assert d.counted == 1 and d.per_day == 0.0


def test_the_age_of_the_oldest_position_is_reported():
    rows = build_open_positions(
        [_pos(swap=0.0, days_ago=0.1), _pos(swap=0.0, days_ago=0.6)],
        {}, {"AAPL": 1.0},
    )
    d = swap_drag(rows, NOW)
    assert d.counted == 0 and d.too_new == 2
    assert d.oldest_days == pytest.approx(0.6)


def test_the_not_measurable_line_says_how_old_the_book_actually_is():
    # a book plainly days old must not be able to claim it is hours old
    rows = build_open_positions([_pos(swap=0.0, days_ago=0.5)], {}, {"AAPL": 1.0})
    r = AccountMonthly(account="1", login=100001, balance=1.0, months=[],
                       open_groups=group_open(rows), drag=swap_drag(rows, NOW))
    assert "0.5 day" in format_monthly_report([r], "now")
    assert "0.5 day" in format_monthly_markdown([r], "now")


# --- cost of carry ----------------------------------------------------------

def _acct(account, notional, balance, unrealised, swap, days=10.0):
    meta_unit = 1.0
    price = 100.0
    vol = notional / (price * meta_unit) if notional else 0.0
    p = _pos(symbol="X", magic=1, volume=vol, days_ago=days,
             profit=unrealised - swap, swap=swap, price=price)
    rows = build_open_positions([p], {}, {"X": meta_unit})
    return AccountMonthly(
        account=account, login=100001, balance=balance, months=[],
        open_groups=group_open(rows), drag=swap_drag(rows, NOW),
    )


def test_carry_uses_equity_not_balance():
    # a floating loss is already backing the margin, so the balance alone
    # overstates the cover the account actually has
    r = _acct("1", 100_000.0, 50_000.0, -10_000.0, -100.0)
    c = carry_rows([r])[0]
    assert c.equity == pytest.approx(40_000.0)
    assert c.leverage == pytest.approx(2.5)


def test_financing_is_reported_against_the_account_as_well():
    # -3,650/yr on a 10,000 account is 36.5% of it, whatever the rate on
    # notional looks like
    r = _acct("1", 1_000_000.0, 10_000.0, 0.0, -100.0, days=10.0)
    c = carry_rows([r])[0]
    assert c.annual == pytest.approx(-3_650.0)
    assert c.pct_of_equity == pytest.approx(-36.5)


def test_an_account_with_nothing_open_has_no_carry_row():
    assert carry_rows([AccountMonthly(account="1", balance=1.0)]) == []


def test_a_failed_account_has_no_carry_row():
    assert carry_rows([AccountMonthly(account="9", error="boom")]) == []


def test_no_equity_gives_no_leverage_rather_than_a_division_by_zero():
    r = _acct("1", 100_000.0, 0.0, 0.0, -100.0)
    c = carry_rows([r])[0]
    assert c.leverage is None and c.pct_of_equity is None


def test_the_markdown_carries_a_cost_of_carry_table():
    md = format_monthly_markdown([_acct("1", 100_000.0, 50_000.0, 0.0, -100.0)],
                                 "now")
    assert "Cost of carry" in md
    assert "leverage" in md


def test_financing_beyond_the_whole_account_is_called_out():
    # -36,500/yr against a 10,000 account: the arithmetic, not a forecast
    md = format_monthly_markdown(
        [_acct("5", 2_000_000.0, 10_000.0, 0.0, -1_000.0, days=10.0)], "now")
    assert "exceeds the whole account" in md


def test_an_unmeasured_book_is_not_given_a_number():
    r = _acct("1", 100_000.0, 50_000.0, 0.0, 0.0, days=0.2)  # too new
    c = carry_rows([r])[0]
    assert c.measured is False
    assert "not measured yet" in format_monthly_markdown([r], "now")


# --- the triple-swap night: a part-week reads too expensive -----------------

def test_a_book_younger_than_a_week_is_provisional():
    # the weekend is billed on one night at triple rate, so five charged
    # nights carry seven days of financing; a part-week straddling that
    # night reads ~40% too expensive
    rows = build_open_positions(
        [_pos(swap=-100.0, days_ago=3.5)], {}, {"AAPL": 1.0}
    )
    d = swap_drag(rows, NOW)
    assert d.counted == 1
    assert d.settled is False


def test_a_book_past_a_week_is_settled():
    rows = build_open_positions(
        [_pos(swap=-100.0, days_ago=8.0)], {}, {"AAPL": 1.0}
    )
    assert swap_drag(rows, NOW).settled is True


def test_the_report_marks_a_provisional_rate_as_such():
    rows = build_open_positions(
        [_pos(volume=1.0, price=100_000.0, swap=-200.0, days_ago=3.5)],
        {}, {"AAPL": 1.0},
    )
    r = AccountMonthly(account="1", login=100001, balance=500_000.0, months=[],
                       open_groups=group_open(rows), drag=swap_drag(rows, NOW))
    text = format_monthly_report([r], "now")
    md = format_monthly_markdown([r], "now")
    assert "PROVISIONAL" in text
    assert "provisional" in md.lower()
    assert "triple" in md.lower()
    assert "3.5 day" in md


def test_a_settled_rate_carries_no_warning():
    rows = build_open_positions(
        [_pos(volume=1.0, price=100_000.0, swap=-200.0, days_ago=9.0)],
        {}, {"AAPL": 1.0},
    )
    r = AccountMonthly(account="1", login=100001, balance=500_000.0, months=[],
                       open_groups=group_open(rows), drag=swap_drag(rows, NOW))
    assert "PROVISIONAL" not in format_monthly_report([r], "now")
    assert "provisional" not in format_monthly_markdown([r], "now").lower()


def test_the_carry_table_flags_a_provisional_row():
    rows = build_open_positions(
        [_pos(volume=1.0, price=100_000.0, swap=-200.0, days_ago=3.5)],
        {}, {"AAPL": 1.0},
    )
    r = AccountMonthly(account="1", login=100001, balance=500_000.0, months=[],
                       open_groups=group_open(rows), drag=swap_drag(rows, NOW))
    assert carry_rows([r])[0].settled is False
    md = format_monthly_markdown([r], "now")
    assert "Provisional" in md

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader.reconcile import (  # noqa: E402
    LiveEntry,
    Signal,
    format_reconciliation,
    match_signals,
)

H = timedelta(hours=1)


def t(hour, day=1):
    return datetime(2026, 9, day, hour, 0, tzinfo=timezone.utc)


def sig(sym, hour, side="buy", day=1):
    return Signal(symbol=sym, side=side, bar_time=t(hour, day))


def live(sym, hour, side="buy", day=1, minute=3, magic=1):
    return LiveEntry(symbol=sym, side=side,
                     time=t(hour, day).replace(minute=minute), magic=magic)


def test_fill_in_the_next_bar_matches():
    # signal on the 14:00 bar -> the bot sees it at 15:00 and fills at 15:03
    r = match_signals([sig("AAPL", 14)], [live("AAPL", 15)])
    assert len(r.matched) == 1
    assert not r.backtest_only and not r.live_only
    assert r.match_rate == 1.0


def test_fill_in_the_same_bar_does_not_match():
    # a fill at 14:03 precedes the close of the 14:00 bar: it cannot be that
    # signal, and treating it as one would hide a look-ahead bug
    r = match_signals([sig("AAPL", 14)], [live("AAPL", 14)])
    assert not r.matched
    assert len(r.backtest_only) == 1 and len(r.live_only) == 1


def test_retry_one_bar_later_matches_within_slack():
    r = match_signals([sig("AAPL", 14)], [live("AAPL", 16)], slack_bars=1)
    assert len(r.matched) == 1
    # ... but not two bars late when no slack is allowed
    r0 = match_signals([sig("AAPL", 14)], [live("AAPL", 16)], slack_bars=0)
    assert not r0.matched


def test_symbol_and_side_must_agree():
    r = match_signals(
        [sig("AAPL", 14), sig("MSFT", 14, "sell")],
        [live("MSFT", 15), live("AAPL", 15, "sell")],
    )
    assert not r.matched
    assert len(r.backtest_only) == 2 and len(r.live_only) == 2


def test_each_live_entry_is_claimed_once():
    # two signals on consecutive bars, one fill: only one can match
    r = match_signals([sig("AAPL", 14), sig("AAPL", 15)], [live("AAPL", 16)])
    assert len(r.matched) == 1
    assert len(r.backtest_only) == 1
    assert not r.live_only


def test_live_only_entry_is_reported():
    r = match_signals([], [live("NVDA", 15)])
    assert not r.matched and not r.backtest_only
    assert len(r.live_only) == 1
    assert r.n_live == 1 and r.n_backtest == 0


def test_counts_and_rate():
    signals = [sig("AAPL", 14), sig("MSFT", 14), sig("NVDA", 14)]
    entries = [live("AAPL", 15), live("MSFT", 15)]
    r = match_signals(signals, entries)
    assert r.n_backtest == 3 and r.n_live == 2
    assert len(r.matched) == 2
    assert abs(r.match_rate - 2 / 3) < 1e-12


# --- verdicts ---------------------------------------------------------------

def test_verdict_clean_run():
    signals = [sig(f"S{i}", 14) for i in range(10)]
    entries = [live(f"S{i}", 15) for i in range(10)]
    text = format_reconciliation(match_signals(signals, entries))
    assert "implementation agrees with the backtest" in text


def test_verdict_calls_an_unexplained_entry_a_bug():
    signals = [sig(f"S{i}", 14) for i in range(10)]
    entries = [live(f"S{i}", 15) for i in range(10)] + [live("GHOST", 15)]
    text = format_reconciliation(match_signals(signals, entries))
    assert "no backtest signal behind them" in text
    assert "GHOST" in text


def test_verdict_flags_wholesale_disagreement():
    signals = [sig(f"S{i}", 14) for i in range(10)]
    entries = [live(f"X{i}", 15) for i in range(10)]
    text = format_reconciliation(match_signals(signals, entries))
    assert "largely disagree in BOTH directions" in text
    assert "implementation bug" in text


def test_verdict_explains_skipping_without_crying_bug():
    signals = [sig(f"S{i}", 14) for i in range(10)]
    entries = [live(f"S{i}", 15) for i in range(4)]
    text = format_reconciliation(match_signals(signals, entries))
    assert "skipped 6 of 10" in text
    assert "position cap" in text


def test_verdict_on_empty_window():
    assert "nothing to compare" in format_reconciliation(match_signals([], []))

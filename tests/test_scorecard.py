import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader import scorecard  # noqa: E402
from gold_trader.scorecard import LiveStats  # noqa: E402


@dataclass
class FakeDeal:
    symbol: str
    magic: int
    profit: float
    commission: float
    swap: float


def _strategy_of(mapping):
    return lambda magic: mapping.get(magic, "unknown")


# ---------------------------------------------------------------------------
# live_stats_from_deals
# ---------------------------------------------------------------------------


def test_live_stats_aggregates_win_rate_and_pf():
    deals = [
        FakeDeal("XAUUSD", 111, 100.0, -2.0, 0.0),   # net +98 win
        FakeDeal("XAUUSD", 111, -50.0, -2.0, 0.0),   # net -52 loss
        FakeDeal("XAUUSD", 111, 30.0, 0.0, 0.0),     # net +30 win
    ]
    stats = scorecard.live_stats_from_deals(deals, _strategy_of({111: "donchian"}))
    assert len(stats) == 1
    s = stats[0]
    assert s.n == 3
    assert abs(s.win_rate - 2 / 3) < 1e-9
    assert s.strategy == "donchian"
    assert abs(s.total_pnl - (98 - 52 + 30)) < 1e-9
    assert abs(s.profit_factor - (128.0 / 52.0)) < 1e-9


def test_live_stats_pf_infinite_when_no_losses():
    deals = [FakeDeal("EURUSD", 5, 10.0, 0.0, 0.0)]
    stats = scorecard.live_stats_from_deals(deals, _strategy_of({}))
    assert stats[0].profit_factor == float("inf")


def test_live_stats_separates_symbols():
    deals = [
        FakeDeal("XAUUSD", 111, 10.0, 0.0, 0.0),
        FakeDeal("EURUSD", 222, -5.0, 0.0, 0.0),
    ]
    stats = scorecard.live_stats_from_deals(deals, _strategy_of({}))
    assert {s.symbol for s in stats} == {"XAUUSD", "EURUSD"}


# ---------------------------------------------------------------------------
# build_scorecard verdicts
# ---------------------------------------------------------------------------


def _bt(n, trades_pnls):
    @dataclass
    class T:
        pnl_price: float
    return {"n": n, "win_rate": 0.5, "trades": [T(p) for p in trades_pnls]}


def _live(symbol="XAUUSD", n=10, pf=1.5, pnl=100.0):
    return LiveStats(symbol=symbol, strategy="donchian", n=n, win_rate=0.5,
                     total_pnl=pnl, profit_factor=pf)


def test_verdict_too_few_when_below_min_trades():
    rows = scorecard.build_scorecard([_live(n=3)], {"XAUUSD": _bt(20, [10, -5])},
                                     min_live_trades=5)
    assert rows[0].verdict == "too-few"


def test_verdict_no_backtest_when_missing():
    rows = scorecard.build_scorecard([_live(n=10)], {})
    assert rows[0].verdict == "no-backtest"


def test_verdict_underperforming_when_live_pf_far_below_backtest():
    # backtest PF = 2.0 (gross win 20 / gross loss 10); live PF 0.5 < 0.6*2.0
    rows = scorecard.build_scorecard(
        [_live(n=10, pf=0.5)], {"XAUUSD": _bt(30, [20.0, -10.0])},
        pf_tolerance=0.6,
    )
    assert rows[0].verdict == "underperforming"


def test_verdict_ok_when_live_holds_up():
    rows = scorecard.build_scorecard(
        [_live(n=10, pf=1.8)], {"XAUUSD": _bt(30, [20.0, -10.0])},
        pf_tolerance=0.6,
    )
    assert rows[0].verdict == "ok"


def test_build_scorecard_sorts_underperformers_first():
    live = [_live("A", n=10, pf=1.8, pnl=100.0), _live("B", n=10, pf=0.3, pnl=-50.0)]
    bt = {"A": _bt(30, [20.0, -10.0]), "B": _bt(30, [20.0, -10.0])}
    rows = scorecard.build_scorecard(live, bt, pf_tolerance=0.6)
    assert rows[0].symbol == "B"
    assert rows[0].verdict == "underperforming"


# ---------------------------------------------------------------------------
# format_scorecard
# ---------------------------------------------------------------------------


def test_format_scorecard_counts_underperformers_in_subject():
    live = [_live("A", n=10, pf=0.2, pnl=-99.0)]
    bt = {"A": _bt(30, [20.0, -10.0])}
    rows = scorecard.build_scorecard(live, bt, pf_tolerance=0.6)
    subject, body = scorecard.format_scorecard(rows, "30d")
    assert "1 underperforming" in subject
    assert "A" in body
    assert "underperforming" in body

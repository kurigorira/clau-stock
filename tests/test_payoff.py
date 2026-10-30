import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader.payoff import (  # noqa: E402
    PayoffStats,
    diagnose,
    format_block,
    stats_from_pnls,
)


def test_basic_shape():
    s = stats_from_pnls([100.0, -50.0, -50.0, 200.0])
    assert s.n == 4 and s.wins == 2
    assert s.win_rate == 0.5
    assert s.avg_win == 150.0
    assert s.avg_loss == 50.0          # positive magnitude
    assert s.payoff_ratio == 3.0
    assert s.expectancy == 50.0


def test_zero_pnl_counts_as_a_loss():
    # it occupied a slot and its costs are already inside the number
    s = stats_from_pnls([0.0, 10.0])
    assert s.wins == 1 and s.win_rate == 0.5
    assert s.avg_loss == 0.0


def test_breakeven_identities():
    s = stats_from_pnls([3.0] * 3 + [-1.0] * 7)   # 30% win rate, payoff 3.0
    assert s.win_rate == 0.3
    assert s.payoff_ratio == 3.0
    # break-even payoff at a 30% win rate is (1-0.3)/0.3
    assert abs(s.breakeven_payoff - 7.0 / 3.0) < 1e-12
    # break-even win rate at payoff 3 is 1/(1+3)
    assert abs(s.breakeven_win_rate - 0.25) < 1e-12
    # sitting above both thresholds means a positive expectancy
    assert s.expectancy > 0


def test_breakeven_at_the_edge_is_flat():
    s = stats_from_pnls([2.0] * 2 + [-1.0] * 4)   # 33.3% win, payoff 2.0
    assert abs(s.expectancy) < 1e-12
    assert abs(s.payoff_ratio - s.breakeven_payoff) < 1e-12


def test_degenerate_sets():
    empty = stats_from_pnls([])
    assert empty.n == 0 and empty.win_rate == 0.0 and empty.expectancy == 0.0
    assert empty.breakeven_payoff == float("inf")

    all_wins = stats_from_pnls([1.0, 2.0])
    assert all_wins.payoff_ratio == float("inf")
    assert all_wins.breakeven_win_rate == 0.0

    all_losses = stats_from_pnls([-1.0, -2.0])
    assert all_losses.payoff_ratio == 0.0
    assert all_losses.breakeven_payoff == float("inf")


def test_median_hold_from_hours():
    s = stats_from_pnls([1.0, -1.0, 1.0], hours=[2.0, 10.0, 6.0])
    assert s.median_hours == 6.0
    even = stats_from_pnls([1.0, -1.0], hours=[2.0, 8.0])
    assert even.median_hours == 5.0


# --- diagnose ---------------------------------------------------------------

def _mk(n, wins, avg_win, avg_loss, hours=None):
    pnls = [avg_win] * wins + [-avg_loss] * (n - wins)
    return stats_from_pnls(pnls, hours)


def test_diagnose_names_the_payoff_gap_not_just_the_loss():
    back = _mk(100, 31, 3.0, 1.0)          # 31% win, payoff 3.0 -> profitable
    live = _mk(100, 31, 1.3, 1.0)          # same win rate, payoff collapsed
    msgs = " | ".join(diagnose(live, back))
    assert "payoff ratio below backtest" in msgs
    assert "win rate" not in msgs.split("payoff")[0]  # win rate matched


def test_diagnose_flags_the_structural_case():
    back = _mk(100, 31, 3.0, 1.0)
    live = _mk(100, 18, 1.3, 1.0)
    msgs = " | ".join(diagnose(live, back))
    # the finding that does not depend on sample size
    assert "structural" in msgs
    assert "STILL lose" in msgs


def test_diagnose_flags_short_holds():
    back = _mk(50, 20, 2.0, 1.0, hours=[40.0] * 50)
    live = _mk(50, 20, 2.0, 1.0, hours=[5.0] * 50)
    assert any("close far sooner" in m for m in diagnose(live, back))


def test_diagnose_quiet_when_shapes_agree():
    back = _mk(80, 32, 2.5, 1.0)
    live = _mk(80, 31, 2.4, 1.0)
    assert diagnose(live, back) == ["live and backtest shapes agree within tolerance"]


def test_diagnose_handles_empty_side():
    assert diagnose(stats_from_pnls([]), _mk(10, 5, 1.0, 1.0)) == [
        "not enough trades on one side to compare"
    ]


def test_format_block_renders_without_backtest():
    text = format_block("macd", _mk(10, 2, 2.0, 1.0), None)
    assert "macd" in text and "backtest" in text
    assert "needs payoff >=" in text


def test_format_block_includes_diagnosis():
    text = format_block("macd", _mk(100, 18, 1.3, 1.0), _mk(100, 31, 3.0, 1.0))
    assert "->" in text and "structural" in text

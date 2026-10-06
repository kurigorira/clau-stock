import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader.cli_util import expand_paths  # noqa: E402


def test_plain_paths_pass_through(tmp_path):
    # literal args are untouched, even if they don't exist (from_yaml errors later)
    assert expand_paths(["a.yaml", "b.yaml"]) == ["a.yaml", "b.yaml"]


def test_glob_expanded_and_sorted(tmp_path):
    for name in ("c.yaml", "a.yaml", "b.yaml", "x.txt"):
        (tmp_path / name).write_text("symbol: X\n")
    got = expand_paths([str(tmp_path / "*.yaml")])
    assert [Path(p).name for p in got] == ["a.yaml", "b.yaml", "c.yaml"]


def test_mix_of_glob_and_literal(tmp_path):
    (tmp_path / "a.yaml").write_text("symbol: X\n")
    got = expand_paths([str(tmp_path / "*.yaml"), "plain.yaml"])
    assert [Path(p).name for p in got] == ["a.yaml", "plain.yaml"]


def test_unmatched_glob_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        expand_paths([str(tmp_path / "nope" / "*.yaml")])


# --- rank_by_spread (fleet selection by tradeability, not alphabet) ---------

from gold_trader.cli_util import rank_by_spread  # noqa: E402


def _quotes(table):
    def fn(name):
        return table.get(name)
    return fn


def test_rank_orders_by_spread_not_alphabet():
    # AA sorts first alphabetically but is the widest; MSFT must outrank it
    table = {"AA": (10.0, 10.05), "MSFT": (400.0, 400.04), "ZZZ": (50.0, 50.01)}
    ranked, dropped = rank_by_spread(list(table), _quotes(table))
    assert [n for n, _ in ranked] == ["MSFT", "ZZZ", "AA"]
    assert dropped == []
    assert 0.99 < ranked[0][1] < 1.01             # 0.04/400.02 ~= 1bp


def test_rank_drops_unquotable_and_wide():
    table = {
        "GOOD": (100.0, 100.02),      # 2bp
        "WIDE": (10.0, 10.30),        # ~296bp
        "DEAD": (0.0, 0.0),           # no market
        "CROSS": (10.0, 9.0),         # crossed book
        "NONE": None,
    }
    ranked, dropped = rank_by_spread(list(table), _quotes(table), max_spread_bp=20)
    assert [n for n, _ in ranked] == ["GOOD"]
    assert {n for n, _ in dropped} == {"WIDE", "DEAD", "CROSS", "NONE"}


def test_rank_prefers_curated_on_ties():
    table = {"UNKNOWN": (100.0, 100.01), "AAPL": (100.0, 100.01)}
    ranked, _ = rank_by_spread(list(table), _quotes(table), prefer={"aapl"})
    assert [n for n, _ in ranked] == ["AAPL", "UNKNOWN"]


def test_rank_survives_a_throwing_quote():
    def fn(name):
        if name == "BOOM":
            raise RuntimeError("terminal hiccup")
        return (100.0, 100.02)
    ranked, dropped = rank_by_spread(["BOOM", "OK"], fn)
    assert [n for n, _ in ranked] == ["OK"]
    assert dropped[0][0] == "BOOM"

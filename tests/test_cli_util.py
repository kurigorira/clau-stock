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

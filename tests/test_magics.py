import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader.magics import (  # noqa: E402
    ConfigMagic,
    find_collisions,
    format_collisions,
    scan_magics,
)


def _write(tmp_path, name, symbol, magic, strategy="macd"):
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        f"symbol: {symbol}\nstrategy: {strategy}\n"
        f"execution:\n  magic_number: {magic}\n",
        encoding="utf-8",
    )
    return p


# --- scanning ---------------------------------------------------------------

def test_scan_reads_symbol_magic_and_strategy(tmp_path):
    _write(tmp_path, "a.yaml", "AAPL", 100, "macd")
    entries = scan_magics([str(p) for p in tmp_path.glob("*.yaml")])
    assert len(entries) == 1
    assert (entries[0].symbol, entries[0].magic, entries[0].strategy) == (
        "AAPL", 100, "macd"
    )


def test_scan_skips_files_that_cannot_own_a_position(tmp_path):
    (tmp_path / "watchlist.yaml").write_text(
        "threshold_pct: 2.0\nextra_symbols: [AAPL]\n", encoding="utf-8"
    )
    (tmp_path / "nomagic.yaml").write_text("symbol: MSFT\n", encoding="utf-8")
    (tmp_path / "broken.yaml").write_text("symbol: [unclosed\n", encoding="utf-8")
    (tmp_path / "scalar.yaml").write_text("just-a-string\n", encoding="utf-8")
    assert scan_magics([str(p) for p in tmp_path.glob("*.yaml")]) == []


def test_scan_is_deduplicated_and_ordered(tmp_path):
    p = _write(tmp_path, "a.yaml", "AAPL", 100)
    entries = scan_magics([str(p), str(p)])
    assert len(entries) == 1


# --- collisions -------------------------------------------------------------

def test_no_collision_when_magics_are_unique():
    entries = [
        ConfigMagic("a.yaml", "AAPL", 100),
        ConfigMagic("b.yaml", "MSFT", 101),
    ]
    assert find_collisions(entries) == []
    assert format_collisions([]) == "no magic-number collisions"


def test_different_symbol_collision_is_reporting_only():
    entries = [
        ConfigMagic("us_fleet/macd_aapl.yaml", "AAPL", 20260701, "macd"),
        ConfigMagic("fib_gbpusd.yaml", "GBPUSD", 20260701, "fibonacci"),
    ]
    c = find_collisions(entries)
    assert len(c) == 1
    assert c[0].same_symbol is False
    assert sorted(c[0].symbols) == ["AAPL", "GBPUSD"]
    text = format_collisions(c)
    assert "different symbols" in text
    assert "SAME SYMBOL" not in text


def test_same_symbol_collision_is_the_dangerous_one():
    entries = [
        ConfigMagic("us_fleet/macd_intel.yaml", "INTEL", 20260735, "macd"),
        ConfigMagic("fib_intel.yaml", "INTEL", 20260735, "fibonacci"),
    ]
    c = find_collisions(entries)
    assert len(c) == 1 and c[0].same_symbol is True
    text = format_collisions(c)
    assert "SAME SYMBOL" in text
    assert "close one position" in text
    assert "fib_intel.yaml" in text and "us_fleet/macd_intel.yaml" in text


def test_dangerous_collisions_sort_first():
    entries = [
        ConfigMagic("a.yaml", "AAPL", 10), ConfigMagic("b.yaml", "MSFT", 10),
        ConfigMagic("c.yaml", "NVDA", 20), ConfigMagic("d.yaml", "NVDA", 20),
    ]
    c = find_collisions(entries)
    assert [x.magic for x in c] == [20, 10]
    assert c[0].same_symbol and not c[1].same_symbol


def test_three_way_collision_counts_once():
    entries = [
        ConfigMagic("a.yaml", "AAPL", 10),
        ConfigMagic("b.yaml", "MSFT", 10),
        ConfigMagic("c.yaml", "NVDA", 10),
    ]
    c = find_collisions(entries)
    assert len(c) == 1 and len(c[0].entries) == 3
    assert c[0].same_symbol is False


def test_end_to_end_on_files(tmp_path):
    _write(tmp_path, "fib_intel.yaml", "INTEL", 555, "fibonacci")
    _write(tmp_path, "us_fleet/macd_intel.yaml", "INTEL", 555, "macd")
    _write(tmp_path, "us_fleet/macd_aapl.yaml", "AAPL", 556, "macd")
    entries = scan_magics([str(p) for p in tmp_path.rglob("*.yaml")])
    assert len(entries) == 3
    c = find_collisions(entries)
    assert len(c) == 1 and c[0].same_symbol

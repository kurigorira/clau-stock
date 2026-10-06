"""watchlist.yaml: one set of rules for the app that writes it and the loop
that reads it, and a writer that keeps every comment."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader import watchlist as w  # noqa: E402

REAL = Path(__file__).resolve().parents[1] / "config" / "watchlist.yaml"


@pytest.fixture
def wl(tmp_path):
    p = tmp_path / "watchlist.yaml"
    p.write_text(REAL.read_text(encoding="utf-8"), encoding="utf-8")
    return p


def _good(**over):
    v = {f.key: f.default for f in w.FIELDS}
    v["extra_symbols"] = []
    v.update(over)
    return v


# --- load -------------------------------------------------------------------

def test_the_committed_file_loads_and_validates(wl):
    clean, errors = w.validate(w.load(wl))
    assert errors == {}


def test_missing_keys_take_their_defaults(tmp_path):
    p = tmp_path / "w.yaml"
    p.write_text("threshold_pct: 3.0\n", encoding="utf-8")
    got = w.load(p)
    assert got["threshold_pct"] == 3.0
    assert got["streak_days"] == 2 and got["extra_symbols"] == []


def test_an_unreadable_file_is_a_settings_error(tmp_path):
    p = tmp_path / "w.yaml"
    p.write_text("threshold_pct: [unclosed\n", encoding="utf-8")
    with pytest.raises(w.SettingsError):
        w.load(p)


# --- validate ---------------------------------------------------------------

def test_values_outside_their_range_are_named():
    _, errors = w.validate(_good(streak_days=0, poll_seconds=1))
    assert set(errors) == {"streak_days", "poll_seconds"}


def test_half_a_day_is_a_typo_not_a_setting():
    _, errors = w.validate(_good(streak_days=2.5))
    assert "streak_days" in errors


def test_numbers_typed_as_text_are_accepted():
    # the page sends form values as strings
    clean, errors = w.validate(_good(threshold_pct="3.5", streak_days="3"))
    assert errors == {}
    assert clean["threshold_pct"] == 3.5 and clean["streak_days"] == 3


def test_booleans_from_text():
    assert w.validate(_good(streak_same_direction="false"))[0]["streak_same_direction"] is False
    assert w.validate(_good(streak_same_direction="maybe"))[1]


def test_symbols_are_checked_deduplicated_and_kept_in_order():
    clean, errors = w.validate(_good(extra_symbols=["GOOGL", "NVIDIA.24H", "GOOGL", "Cocoa-Cr"]))
    assert errors == {}
    assert clean["extra_symbols"] == ["GOOGL", "NVIDIA.24H", "Cocoa-Cr"]


def test_a_symbol_with_spaces_or_punctuation_is_refused():
    _, errors = w.validate(_good(extra_symbols=["GOOGL", "AA PL", "X;rm"]))
    assert "extra_symbols" in errors


# --- save -------------------------------------------------------------------

def test_saving_keeps_every_comment(wl):
    before = [l for l in wl.read_text(encoding="utf-8").splitlines() if l.strip().startswith("#")]
    clean, _ = w.validate(_good(threshold_pct=3.0, streak_days=3,
                                streak_same_direction=False,
                                extra_symbols=["GOOGL"]))
    w.save(wl, clean)
    after = [l for l in wl.read_text(encoding="utf-8").splitlines() if l.strip().startswith("#")]
    assert after == before


def test_saving_changes_exactly_the_values(wl):
    clean, _ = w.validate(_good(threshold_pct=3.0, streak_days=3, extra_symbols=["GOOGL", "AAPL"]))
    w.save(wl, clean)
    got = w.load(wl)
    assert got["threshold_pct"] == 3.0 and got["streak_days"] == 3
    assert got["extra_symbols"] == ["GOOGL", "AAPL"]
    assert got["window_minutes"] == 10  # untouched


def test_the_trailing_comment_stays_on_its_line(wl):
    clean, _ = w.validate(_good(threshold_pct=3.0))
    w.save(wl, clean)
    line = next(l for l in wl.read_text(encoding="utf-8").splitlines()
                if l.startswith("threshold_pct:"))
    assert line.startswith("threshold_pct: 3.0") and "# |change| >= this" in line


def test_symbols_can_go_from_a_list_back_to_empty(wl):
    w.save(wl, w.validate(_good(extra_symbols=["GOOGL", "AAPL"]))[0])
    w.save(wl, w.validate(_good(extra_symbols=[]))[0])
    assert w.load(wl)["extra_symbols"] == []
    # the commented examples ("  # - GOOGL") stay; live list items must not
    items = [l for l in wl.read_text(encoding="utf-8").splitlines()
             if l.lstrip().startswith("- ")]
    assert items == []


def test_a_missing_key_is_appended_rather_than_lost(tmp_path):
    p = tmp_path / "w.yaml"
    p.write_text("# old file\nthreshold_pct: 2.0\n", encoding="utf-8")
    w.save(p, w.validate(_good(streak_days=4))[0])
    assert w.load(p)["streak_days"] == 4
    assert p.read_text(encoding="utf-8").startswith("# old file")


def test_the_previous_file_is_kept_as_a_backup(wl):
    original = wl.read_text(encoding="utf-8")
    w.save(wl, w.validate(_good(threshold_pct=3.0))[0])
    assert (wl.parent / "watchlist.yaml.bak").read_text(encoding="utf-8") == original


def test_a_write_that_does_not_read_back_leaves_the_file_alone(wl, monkeypatch):
    original = wl.read_text(encoding="utf-8")
    real_load = w.load

    def lying_load(path):
        got = real_load(path)
        if str(path).endswith(".tmp"):
            got["threshold_pct"] = 99.0   # as if the edit landed wrongly
        return got

    monkeypatch.setattr(w, "load", lying_load)
    with pytest.raises(w.SettingsError):
        w.save(wl, w.validate(_good(threshold_pct=3.0))[0])
    assert wl.read_text(encoding="utf-8") == original
    assert not (wl.parent / "watchlist.yaml.tmp").exists()


# --- the alert loop's side: refuse bad edits, keep retired symbols retired ---

def _run_alerts():
    import importlib.util
    path = Path(__file__).resolve().parents[1] / "scripts" / "run_alerts.py"
    spec = importlib.util.spec_from_file_location("run_alerts", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_loop_refuses_an_edit_the_app_would_refuse(tmp_path):
    # a hand edit to poll_seconds: 0 would spin the loop flat out; it is
    # refused, and the loop keeps the settings it had
    ra = _run_alerts()
    p = tmp_path / "w.yaml"
    p.write_text("poll_seconds: 0\n", encoding="utf-8")
    settings, why = ra._read_settings(str(p))
    assert settings is None and "poll_seconds" in why


def test_the_loop_accepts_what_the_app_writes(wl):
    ra = _run_alerts()
    w.save(wl, w.validate(_good(streak_days=3, extra_symbols=["GOOGL"]))[0])
    settings, why = ra._read_settings(str(wl))
    assert why == "" and settings["streak_days"] == 3


def test_a_reload_does_not_resurrect_a_retired_symbol():
    ra = _run_alerts()
    got = ra._symbol_list(["AAPL", "MSFT"], ["GOOGL", "AAPL"], retired={"MSFT"})
    assert got == ["AAPL", "GOOGL"]

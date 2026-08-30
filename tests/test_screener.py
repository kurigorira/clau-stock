import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader.config import Config  # noqa: E402
from gold_trader.screener import (  # noqa: E402
    StrategyScore,
    existing_symbols,
    launched_symbols,
    passes_gate,
    score_symbol,
    split_frame,
)


def _h1(n: int, start: float = 1000.0, step: float = 0.5) -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=n, freq="h", tz="UTC")
    close = start + np.arange(n) * step
    return pd.DataFrame(
        {
            "open": close - 0.2,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 100,
        },
        index=idx,
    )


def _score(**kw) -> StrategyScore:
    base = dict(
        strategy="fibonacci",
        train_n=20, train_pf=1.5, train_pnl=10.0,
        test_n=6, test_pf=1.3, test_pnl=4.0,
    )
    base.update(kw)
    return StrategyScore(**base)


def test_split_frame_ratio_and_order():
    df = _h1(100)
    train, test = split_frame(df, 0.7)
    assert len(train) == 70
    assert len(test) == 30
    assert train.index[-1] < test.index[0]  # chronological, no overlap


def test_split_frame_rejects_bad_ratio():
    with pytest.raises(ValueError):
        split_frame(_h1(10), 1.5)


def test_passes_gate_accepts_solid_result():
    assert passes_gate(_score()) is True


def test_passes_gate_rejects_thin_train_sample():
    assert passes_gate(_score(train_n=5)) is False


def test_passes_gate_rejects_weak_train_pf():
    assert passes_gate(_score(train_pf=1.1)) is False


def test_passes_gate_rejects_out_of_sample_failure():
    assert passes_gate(_score(test_pf=0.8)) is False
    assert passes_gate(_score(test_n=2)) is False


def test_passes_gate_custom_thresholds():
    s = _score(train_pf=1.05, test_pf=1.0)
    assert passes_gate(s, min_train_pf=1.0) is True
    assert passes_gate(s, min_train_pf=1.1) is False


def test_score_symbol_returns_both_strategies():
    cfg = Config()
    result = score_symbol("TEST", _h1(800), cfg, spread_points=20.0, point=0.01)
    assert result.symbol == "TEST"
    assert {s.strategy for s in result.scores} == {"donchian", "fibonacci", "macd"}
    assert result.spread_points == 20.0


def test_existing_symbols_collects_symbol_fields(tmp_path):
    (tmp_path / "fib_xauusd.yaml").write_text("symbol: XAUUSD\n", encoding="utf-8")
    (tmp_path / "legacy.yaml").write_text("symbol: EURUSD\ntimeframe: H1\n", encoding="utf-8")
    (tmp_path / "watchlist.yaml").write_text("extra_symbols: [GOOG]\n", encoding="utf-8")
    (tmp_path / "broken.yaml").write_text(":\n  - not: [valid", encoding="utf-8")
    syms = existing_symbols(tmp_path)
    assert syms == {"XAUUSD", "EURUSD"}  # no symbol key / broken files skipped


def test_existing_symbols_covers_real_config_dir():
    config_dir = Path(__file__).resolve().parents[1] / "config"
    syms = existing_symbols(config_dir)
    # fleet + benched symbols must be treated as settled
    for expected in ("XAUUSD", "BTCUSD", "GBPUSD", "EXXON", "GOOG", "PFIZER"):
        assert expected in syms


def _fake_repo(tmp_path, bat_lines):
    (tmp_path / "start.bat").write_text("\n".join(bat_lines), encoding="utf-8")
    fleet = tmp_path / "config" / "us_fleet"
    fleet.mkdir(parents=True)
    (fleet / "macd_aapl.yaml").write_text(
        "symbol: AAPL\nstrategy: macd\n", encoding="utf-8"
    )
    (fleet / "macd_msft.yaml").write_text(
        "symbol: MSFT\nstrategy: macd\n", encoding="utf-8"
    )
    cfg = tmp_path / "config"
    (cfg / "fib_gold.yaml").write_text(
        "symbol: XAUUSD\nstrategy: fibonacci\n", encoding="utf-8"
    )
    (cfg / "fib_benched.yaml").write_text(  # exists but never referenced
        "symbol: GOOG\nstrategy: fibonacci\n", encoding="utf-8"
    )
    return tmp_path


def test_launched_symbols_reflects_start_bat(tmp_path):
    repo = _fake_repo(tmp_path, [
        r"start x cmd /k python scripts\run_live.py --account 1 config\us_fleet\*.yaml",
        r"start x cmd /k python scripts\run_live.py --account 2 config\fib_gold.yaml",
        r"REM start x cmd /k python scripts\run_live.py --account 3 config\fib_benched.yaml",
    ])
    fleet = launched_symbols(repo)
    assert fleet == {"AAPL", "MSFT", "XAUUSD"}
    # fib_benched.yaml exists in config/ but is only on a REM'd line
    assert "GOOG" not in fleet


def test_launched_strategies_maps_symbol_to_strategy(tmp_path):
    from gold_trader.screener import launched_strategies

    repo = _fake_repo(tmp_path, [
        r"start x cmd /k python scripts\run_live.py --account 1 config\us_fleet\*.yaml",
        r"start x cmd /k python scripts\run_live.py --account 2 config\fib_gold.yaml",
    ])
    strats = launched_strategies(repo)
    assert strats["AAPL"] == "macd"
    assert strats["MSFT"] == "macd"
    assert strats["XAUUSD"] == "fibonacci"


def test_launched_symbols_real_repo_missing_fleet_dirs_is_empty():
    # the us_fleet dirs are machine-generated and absent from the repo/CI;
    # parsing the real start.bat must not crash and yields no symbols here
    repo_root = Path(__file__).resolve().parents[1]
    assert launched_symbols(repo_root) == set()


def test_launched_symbols_missing_bat_returns_empty(tmp_path):
    assert launched_symbols(tmp_path) == set()


def test_score_symbol_split_respected():
    # ensure the test segment really is evaluated on unseen bars: with a tiny
    # frame the test half has too few bars for any trade
    cfg = Config()
    result = score_symbol("TEST", _h1(300), cfg, spread_points=0.0, point=0.01)
    for s in result.scores:
        assert s.test_n == 0  # 90 test bars < warmup -> no trades possible

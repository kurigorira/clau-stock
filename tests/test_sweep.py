import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader.config import Config  # noqa: E402
from gold_trader.sweep import PooledScore, set_param, sweep_param  # noqa: E402


def _h1(n: int, start: float = 1000.0, step: float = 0.5) -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=n, freq="h", tz="UTC")
    close = start + np.arange(n) * step
    return pd.DataFrame(
        {"open": close - 0.2, "high": close + 1.0, "low": close - 1.0,
         "close": close, "volume": 100},
        index=idx,
    )


def test_set_param_sets_nested_float():
    cfg = set_param(Config(), "fibonacci.retrace_min", 0.5)
    assert cfg.fibonacci.retrace_min == 0.5


def test_set_param_coerces_string_to_field_type():
    cfg = set_param(Config(), "risk.atr_stop_mult", "2.5")
    assert cfg.risk.atr_stop_mult == 2.5
    assert isinstance(cfg.risk.atr_stop_mult, float)


def test_set_param_coerces_int_field():
    cfg = set_param(Config(), "fibonacci.bounce_bars", "3")
    assert cfg.fibonacci.bounce_bars == 3
    assert isinstance(cfg.fibonacci.bounce_bars, int)


def test_set_param_coerces_bool_field():
    cfg = set_param(Config(), "fibonacci.use_macd", "false")
    assert cfg.fibonacci.use_macd is False


def test_set_param_rejects_unknown_path():
    with pytest.raises(AttributeError):
        set_param(Config(), "risk.nonexistent", 1.0)


def test_set_param_does_not_mutate_original():
    base = Config()
    original = base.risk.atr_stop_mult
    set_param(base, "risk.atr_stop_mult", 99.0)
    assert base.risk.atr_stop_mult == original


def test_sweep_param_returns_one_score_per_value():
    frames = {"A": _h1(400), "B": _h1(400, start=2000.0)}
    scores = sweep_param(
        frames, Config(), "risk.atr_stop_mult", [2.0, 3.0],
        strategy="donchian", split_ratio=0.7,
    )
    assert len(scores) == 2
    assert all(isinstance(s, PooledScore) for s in scores)
    assert [s.value for s in scores] == [2.0, 3.0]


def test_sweep_param_pools_trades_across_symbols():
    # pooled n must equal the sum of per-symbol n for the same config
    from gold_trader.backtest import run_backtest
    from gold_trader.screener import split_frame

    frames = {"A": _h1(400), "B": _h1(400, start=1500.0, step=0.7)}
    cfg = set_param(Config(), "risk.atr_stop_mult", 2.0)
    cfg.strategy = "donchian"
    expected_train = 0
    for df in frames.values():
        train, _ = split_frame(df, 0.7)
        expected_train += run_backtest(train, cfg)["n"]

    scores = sweep_param(frames, Config(), "risk.atr_stop_mult", [2.0],
                         strategy="donchian", split_ratio=0.7)
    assert scores[0].train_n == expected_train

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader.config import Config  # noqa: E402
from gold_trader.screener import (  # noqa: E402
    StrategyScore,
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
    assert {s.strategy for s in result.scores} == {"donchian", "fibonacci"}
    assert result.spread_points == 20.0


def test_score_symbol_split_respected():
    # ensure the test segment really is evaluated on unseen bars: with a tiny
    # frame the test half has too few bars for any trade
    cfg = Config()
    result = score_symbol("TEST", _h1(300), cfg, spread_points=0.0, point=0.01)
    for s in result.scores:
        assert s.test_n == 0  # 90 test bars < warmup -> no trades possible

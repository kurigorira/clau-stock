import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader.config import Config  # noqa: E402
from gold_trader.strategy import add_indicators, evaluate_last_bar  # noqa: E402


def _ramp(n: int, start: float = 1800.0, step: float = 1.0) -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=n, freq="h", tz="UTC")
    close = start + np.arange(n) * step
    return pd.DataFrame(
        {
            "open": close - 0.5,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 100,
        },
        index=idx,
    )


def _cfg() -> Config:
    cfg = Config()
    cfg.trend.ema_length = 20
    cfg.breakout.donchian_length = 10
    return cfg


def test_uptrend_breakout_signals_buy():
    cfg = _cfg()
    data = add_indicators(_ramp(60, start=1800.0, step=1.0), cfg)
    sig = evaluate_last_bar(data, cfg)
    assert sig.side == "buy"
    assert sig.stop < sig.entry_ref


def test_downtrend_breakout_signals_sell():
    cfg = _cfg()
    data = add_indicators(_ramp(60, start=2000.0, step=-1.0), cfg)
    sig = evaluate_last_bar(data, cfg)
    assert sig.side == "sell"
    assert sig.stop > sig.entry_ref


def test_choppy_no_signal():
    cfg = _cfg()
    n = 60
    idx = pd.date_range("2025-01-01", periods=n, freq="h", tz="UTC")
    close = 1900 + np.sin(np.arange(n) / 3.0) * 2
    df = pd.DataFrame(
        {
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 100,
        },
        index=idx,
    )
    sig = evaluate_last_bar(add_indicators(df, cfg), cfg)
    assert sig.side is None


def test_insufficient_data_returns_none():
    cfg = Config()
    sig = evaluate_last_bar(add_indicators(_ramp(5), cfg), cfg)
    assert sig.side is None

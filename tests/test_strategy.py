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
    """Loose config for the legacy breakout-direction tests.

    The new ADX / ATR%% / EMA-slope / buffer filters are disabled here so the
    tests focus on basic breakout sign detection. Filter behaviour is covered
    by dedicated tests below.
    """
    cfg = Config()
    cfg.trend.ema_length = 20
    cfg.trend.ema_slope_lookback = 5
    cfg.breakout.donchian_length = 10
    cfg.breakout.atr_buffer_mult = 0.0
    cfg.filters.adx_min = 0.0
    cfg.filters.atr_pct_min = 0.0
    cfg.filters.atr_pct_max = 1.0
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


def test_flat_no_signal():
    cfg = _cfg()
    n = 60
    idx = pd.date_range("2025-01-01", periods=n, freq="h", tz="UTC")
    close = np.full(n, 1900.0)
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


def test_atr_buffer_blocks_marginal_breakout():
    cfg = _cfg()
    cfg.breakout.atr_buffer_mult = 100.0   # require an absurdly wide breach
    data = add_indicators(_ramp(60, start=1800.0, step=1.0), cfg)
    sig = evaluate_last_bar(data, cfg)
    assert sig.side is None


def test_adx_filter_blocks_signal():
    cfg = _cfg()
    cfg.filters.adx_min = 1000.0           # impossible threshold
    data = add_indicators(_ramp(60, start=1800.0, step=1.0), cfg)
    sig = evaluate_last_bar(data, cfg)
    assert sig.side is None


def test_atr_pct_filter_blocks_signal():
    cfg = _cfg()
    cfg.filters.atr_pct_min = 0.5          # require >50%% ATR/close
    data = add_indicators(_ramp(60, start=1800.0, step=1.0), cfg)
    sig = evaluate_last_bar(data, cfg)
    assert sig.side is None


def test_ema_slope_lookback_too_long_blocks():
    cfg = _cfg()
    cfg.trend.ema_slope_lookback = 10_000  # exceeds available history -> NaN slope
    data = add_indicators(_ramp(60, start=1800.0, step=1.0), cfg)
    sig = evaluate_last_bar(data, cfg)
    assert sig.side is None

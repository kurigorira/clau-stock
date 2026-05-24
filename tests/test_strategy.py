import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader.config import Config  # noqa: E402
from gold_trader.strategy import add_indicators, evaluate_last_bar, h4_trend_dir  # noqa: E402


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


# ---------------------------------------------------------------------------
# MTF (H4 filter + H1 entry) tests
# ---------------------------------------------------------------------------


def _mtf_cfg() -> Config:
    """Like _cfg() but with the H4 higher_timeframe filter active."""
    cfg = _cfg()
    cfg.trend.higher_timeframe = "H4"
    return cfg


def test_h4_uptrend_h1_break_allows_buy():
    cfg = _mtf_cfg()
    h1 = add_indicators(_ramp(60, start=1800.0, step=1.0), cfg)
    h4 = add_indicators(_ramp(60, start=1800.0, step=4.0), cfg)
    sig = evaluate_last_bar(h1, cfg, h4)
    assert sig.side == "buy"
    assert sig.h4_trend_dir == 1


def test_h4_downtrend_blocks_h1_buy_break():
    cfg = _mtf_cfg()
    h1 = add_indicators(_ramp(60, start=1800.0, step=1.0), cfg)  # H1 says buy
    h4 = add_indicators(_ramp(60, start=2000.0, step=-4.0), cfg)  # H4 says down
    sig = evaluate_last_bar(h1, cfg, h4)
    assert sig.side is None
    assert sig.h4_trend_dir == -1


def test_h4_downtrend_h1_sell_break_allows_sell():
    cfg = _mtf_cfg()
    h1 = add_indicators(_ramp(60, start=2000.0, step=-1.0), cfg)
    h4 = add_indicators(_ramp(60, start=2000.0, step=-4.0), cfg)
    sig = evaluate_last_bar(h1, cfg, h4)
    assert sig.side == "sell"
    assert sig.h4_trend_dir == -1


def test_h4_high_adx_required_for_trend_dir():
    cfg = _mtf_cfg()
    cfg.filters.adx_min = 1000.0  # H4 will never qualify as trending
    h1 = add_indicators(_ramp(60, start=1800.0, step=1.0), cfg)
    h4 = add_indicators(_ramp(60, start=1800.0, step=4.0), cfg)
    # H1 itself also fails ADX, so signal is None; but verify h4_dir==0 too
    assert h4_trend_dir(h4, cfg) == 0


def test_mtf_disabled_when_higher_timeframe_blank():
    cfg = _cfg()
    cfg.trend.higher_timeframe = ""
    h1 = add_indicators(_ramp(60, start=1800.0, step=1.0), cfg)
    h4 = add_indicators(_ramp(60, start=2000.0, step=-4.0), cfg)
    # H4 says down, but filter is off => H1 breakout wins
    sig = evaluate_last_bar(h1, cfg, h4)
    assert sig.side == "buy"


def test_df_h4_none_preserves_legacy_behaviour():
    cfg = _mtf_cfg()  # higher_timeframe = "H4", but we pass df_h4=None
    h1 = add_indicators(_ramp(60, start=1800.0, step=1.0), cfg)
    sig = evaluate_last_bar(h1, cfg, None)
    assert sig.side == "buy"

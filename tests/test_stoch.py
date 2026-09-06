"""Shared stochastic-gate tests for the donchian and fibonacci strategies.

The gate (strategy.stoch_blocks) rejects a long once slow %K >= overbought and
a short once %K <= oversold. These tests pin the threshold to a degenerate
value (0 -> always block, >100 -> never block) so the wiring is verified
independently of the exact %K a given fixture produces. MACD wiring lives in
test_macd.py.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader import backtest as bt  # noqa: E402
from gold_trader.config import Config  # noqa: E402
from gold_trader.strategy import (  # noqa: E402
    add_indicators,
    evaluate_fib_entry,
    evaluate_last_bar,
    fib_zone,
    stoch_blocks,
    swing_range,
)


# --- donchian fixtures ------------------------------------------------------

def _ramp(n: int, start: float, step: float) -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=n, freq="h", tz="UTC")
    close = start + np.arange(n) * step
    return pd.DataFrame(
        {"open": close - 0.5, "high": close + 0.5, "low": close - 0.5,
         "close": close, "volume": 100},
        index=idx,
    )


def _donch_cfg() -> Config:
    cfg = Config()
    cfg.trend.ema_length = 20
    cfg.trend.ema_slope_lookback = 5
    cfg.breakout.donchian_length = 10
    cfg.breakout.atr_buffer_mult = 0.0
    cfg.filters.adx_min = 0.0
    cfg.filters.atr_pct_min = 0.0
    cfg.filters.atr_pct_max = 1.0
    return cfg


def test_donchian_stoch_off_by_default_no_column():
    cfg = _donch_cfg()
    assert cfg.stoch.use is False
    data = add_indicators(_ramp(60, 1800.0, 1.0), cfg)
    assert "stoch_k" not in data.columns


def test_donchian_stoch_blocks_overbought_breakout():
    # a clean uptrend breakout that fires a buy without the gate...
    cfg = _donch_cfg()
    assert evaluate_last_bar(add_indicators(_ramp(60, 1800.0, 1.0), cfg), cfg).side == "buy"
    # ...is rejected once the gate is on with an always-trip threshold
    cfg.stoch.use = True
    cfg.stoch.overbought = 0.0
    data = add_indicators(_ramp(60, 1800.0, 1.0), cfg)
    assert not np.isnan(data["stoch_k"].iloc[-1])  # gate actually evaluated
    assert evaluate_last_bar(data, cfg).side is None


def _wavy(n: int) -> pd.DataFrame:
    # rising trend with oscillation so donchian breakouts actually fire in a
    # backtest and %K varies bar to bar
    idx = pd.date_range("2025-01-01", periods=n, freq="h", tz="UTC")
    t = np.arange(n)
    close = 1800.0 + t * 0.8 + 15.0 * np.sin(t / 6.0)
    return pd.DataFrame(
        {"open": close, "high": close + 1.0, "low": close - 1.0,
         "close": close, "volume": 100},
        index=idx,
    )


def test_donchian_backtest_respects_gate():
    # regression: the donchian backtest inlines entry logic separately from
    # evaluate_last_bar, so the gate must be wired there too. An always-trip
    # threshold must strictly reduce the trade count.
    cfg = _donch_cfg()
    df = _wavy(400)
    base = bt.run_backtest(df, cfg)
    cfg.stoch.use = True
    cfg.stoch.overbought = 0.0
    cfg.stoch.oversold = 100.0
    gated = bt.run_backtest(df, cfg)
    assert base["n"] > 0
    assert gated["n"] < base["n"]


def test_donchian_stoch_allows_when_threshold_unreachable():
    cfg = _donch_cfg()
    cfg.stoch.use = True
    cfg.stoch.overbought = 101.0   # %K in [0,100] can never reach this
    data = add_indicators(_ramp(60, 1800.0, 1.0), cfg)
    assert evaluate_last_bar(data, cfg).side == "buy"


def test_donchian_stoch_blocks_oversold_short():
    cfg = _donch_cfg()
    cfg.stoch.use = True
    cfg.stoch.oversold = 100.0     # any %K <= 100 trips -> every short blocked
    data = add_indicators(_ramp(60, 2000.0, -1.0), cfg)
    assert evaluate_last_bar(data, cfg).side is None


# --- fibonacci fixtures -----------------------------------------------------

def _fib_cfg() -> Config:
    cfg = Config()
    cfg.strategy = "fibonacci"
    cfg.trend.higher_timeframe = "H4"
    cfg.trend.ema_length = 20
    cfg.trend.ema_slope_lookback = 5
    cfg.filters.adx_min = 0.0
    cfg.filters.atr_pct_min = 0.0
    cfg.filters.atr_pct_max = 1.0
    return cfg


def _h4_ramp(n: int, start: float, step: float) -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=n, freq="4h", tz="UTC")
    close = start + np.arange(n) * step
    return pd.DataFrame(
        {"open": close - 0.5, "high": close + 0.5, "low": close - 0.5,
         "close": close, "volume": 100},
        index=idx,
    )


def _h1_frame(closes, volumes) -> pd.DataFrame:
    n = len(closes)
    idx = pd.date_range("2025-02-01", periods=n, freq="h", tz="UTC")
    c = np.asarray(closes, dtype=float)
    return pd.DataFrame(
        {"open": c - 0.2, "high": c + 0.5, "low": c - 0.5, "close": c,
         "volume": volumes},
        index=idx,
    )


def _fib_buy(cfg: Config):
    h4 = add_indicators(_h4_ramp(60, start=1800.0, step=4.0), cfg)
    swing_high, swing_low = swing_range(h4, cfg.fibonacci.swing_lookback)
    zone_low, zone_high = fib_zone(
        swing_high, swing_low, 1, cfg.fibonacci.retrace_min, cfg.fibonacci.retrace_max
    )
    target = (zone_low + zone_high) / 2
    decline = np.linspace(target + 40.0, target - 3.0, 58)
    closes = list(decline) + [target - 1.5, target]
    volumes = [100.0] * 59 + [300.0]
    return add_indicators(_h1_frame(closes, volumes), cfg), h4


def test_fibonacci_stoch_blocks_and_allows():
    cfg = _fib_cfg()
    h1, h4 = _fib_buy(cfg)
    assert evaluate_fib_entry(h1, h4, cfg).side == "buy"   # baseline fires

    cfg.stoch.use = True
    cfg.stoch.overbought = 0.0                              # always trip
    h1, h4 = _fib_buy(cfg)
    assert evaluate_fib_entry(h1, h4, cfg).side is None

    cfg.stoch.overbought = 101.0                            # never trip
    h1, h4 = _fib_buy(cfg)
    assert evaluate_fib_entry(h1, h4, cfg).side == "buy"


# --- helper unit ------------------------------------------------------------

def test_stoch_blocks_helper_semantics():
    cfg = Config()
    cfg.stoch.overbought = 80.0
    cfg.stoch.oversold = 20.0
    assert stoch_blocks("buy", pd.Series({"stoch_k": 85.0}), cfg) is True
    assert stoch_blocks("buy", pd.Series({"stoch_k": 50.0}), cfg) is False
    assert stoch_blocks("sell", pd.Series({"stoch_k": 15.0}), cfg) is True
    assert stoch_blocks("sell", pd.Series({"stoch_k": 50.0}), cfg) is False
    # NaN / missing %K blocks either side (unconfirmed)
    assert stoch_blocks("buy", pd.Series({"stoch_k": np.nan}), cfg) is True
    assert stoch_blocks("sell", pd.Series({"close": 1.0}), cfg) is True

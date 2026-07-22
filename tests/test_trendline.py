import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader import backtest as bt  # noqa: E402
from gold_trader.config import Config  # noqa: E402
from gold_trader.strategy import _regression_trend, trendline_blocks  # noqa: E402


def _series(y) -> pd.Series:
    idx = pd.date_range("2025-01-01", periods=len(y), freq="h", tz="UTC")
    return pd.Series(np.asarray(y, dtype=float), index=idx)


# --- _regression_trend ------------------------------------------------------

def test_regression_matches_numpy_polyfit():
    rng = np.random.default_rng(0)
    n, L = 160, 40
    y = 100 + 0.25 * np.arange(n) + rng.standard_normal(n) * 1.5
    slope_pct, r2 = _regression_trend(_series(y), L)
    for t in (60, 120, n - 1):
        yy = y[t - L + 1 : t + 1]
        x = np.arange(L)
        m, b = np.polyfit(x, yy, 1)
        line_end = m * (L - 1) + b
        yhat = m * x + b
        r2_np = 1 - ((yy - yhat) ** 2).sum() / ((yy - yy.mean()) ** 2).sum()
        assert slope_pct.iloc[t] == pytest_approx(m / line_end)
        assert r2.iloc[t] == pytest_approx(r2_np)


def test_regression_warmup_is_nan():
    slope_pct, r2 = _regression_trend(_series(np.arange(30.0)), 10)
    assert slope_pct.iloc[:9].isna().all()   # first L-1 bars undefined
    assert not np.isnan(slope_pct.iloc[9])


def test_regression_flat_series_zero_slope_nan_r2():
    slope_pct, r2 = _regression_trend(_series(np.full(50, 42.0)), 20)
    assert slope_pct.iloc[-1] == 0.0
    assert np.isnan(r2.iloc[-1])            # no variance to explain


def test_regression_scale_free_slope():
    # same fractional trend at two price levels -> same slope_pct
    up = np.linspace(1.0, 2.0, 100)
    a, _ = _regression_trend(_series(up * 10.0), 50)
    b, _ = _regression_trend(_series(up * 1000.0), 50)
    assert a.iloc[-1] == pytest_approx(b.iloc[-1])


# --- trendline_blocks -------------------------------------------------------

def _bar(slope, r2):
    return pd.Series({"tl_slope": slope, "tl_r2": r2})


def test_trendline_blocks_direction():
    cfg = Config()
    cfg.trendline.slope_min = 0.0
    cfg.trendline.r2_min = 0.0
    assert trendline_blocks("buy", _bar(0.01, 0.9), cfg) is False
    assert trendline_blocks("buy", _bar(-0.01, 0.9), cfg) is True   # falling -> no long
    assert trendline_blocks("sell", _bar(-0.01, 0.9), cfg) is False
    assert trendline_blocks("sell", _bar(0.01, 0.9), cfg) is True   # rising -> no short


def test_trendline_blocks_r2_gate():
    cfg = Config()
    cfg.trendline.r2_min = 0.5
    assert trendline_blocks("buy", _bar(0.01, 0.8), cfg) is False   # clean enough
    assert trendline_blocks("buy", _bar(0.01, 0.3), cfg) is True    # too choppy


def test_trendline_blocks_slope_min():
    cfg = Config()
    cfg.trendline.slope_min = 0.005
    assert trendline_blocks("buy", _bar(0.004, 0.9), cfg) is True   # too shallow
    assert trendline_blocks("buy", _bar(0.006, 0.9), cfg) is False


def test_trendline_blocks_nan_blocks():
    cfg = Config()
    assert trendline_blocks("buy", _bar(float("nan"), 0.9), cfg) is True
    assert trendline_blocks("sell", _bar(0.01, float("nan")), cfg) is True
    assert trendline_blocks("buy", pd.Series(dtype=float), cfg) is True  # missing cols


# --- backtest integration ---------------------------------------------------

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


def _wavy(n: int) -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=n, freq="h", tz="UTC")
    t = np.arange(n)
    close = 1800.0 + t * 0.8 + 15.0 * np.sin(t / 6.0)
    return pd.DataFrame(
        {"open": close, "high": close + 1.0, "low": close - 1.0,
         "close": close, "volume": 100},
        index=idx,
    )


def test_trendline_off_is_noop():
    cfg = _donch_cfg()
    df = _wavy(400)
    base = bt.run_backtest(df, cfg)
    cfg.trendline.use = False
    assert bt.run_backtest(df, cfg)["n"] == base["n"]


def test_trendline_gate_only_removes_trades():
    cfg = _donch_cfg()
    df = _wavy(400)
    base = bt.run_backtest(df, cfg)
    cfg.trendline.use = True
    cfg.trendline.length = 50
    gated = bt.run_backtest(df, cfg)
    # a confirmation gate can only make entries stricter, never invent trades
    assert 0 < gated["n"] <= base["n"]


def test_trendline_high_r2_gate_is_strict():
    cfg = _donch_cfg()
    df = _wavy(400)
    cfg.trendline.use = True
    cfg.trendline.length = 50
    loose = bt.run_backtest(df, cfg)                 # r2_min 0
    cfg.trendline.r2_min = 0.95
    strict = bt.run_backtest(df, cfg)
    assert strict["n"] <= loose["n"]                 # tighter fit -> fewer trades


# tiny local approx helper so the file has no hard pytest dependency for asserts
def pytest_approx(x, rel=1e-9, abs_=1e-12):
    class _A:
        def __eq__(self, other):
            return abs(other - x) <= max(rel * abs(x), abs_)
    return _A()

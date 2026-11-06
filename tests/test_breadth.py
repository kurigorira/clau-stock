import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader import backtest as bt  # noqa: E402
from gold_trader.breadth import (  # noqa: E402
    breadth_blocks,
    compute_breadth,
    is_universe_member,
)
from gold_trader.config import Config  # noqa: E402


def _frame(highs, lows, closes=None) -> pd.DataFrame:
    n = len(highs)
    idx = pd.date_range("2025-01-01", periods=n, freq="h", tz="UTC")
    c = closes if closes is not None else [(h + l) / 2 for h, l in zip(highs, lows)]
    return pd.DataFrame(
        {"open": c, "high": highs, "low": lows, "close": c, "volume": 100},
        index=idx,
    )


# --- compute_breadth --------------------------------------------------------

def test_rising_symbol_makes_new_highs():
    rising = _frame(highs=[10, 11, 12, 13, 14], lows=[9, 10, 11, 12, 13])
    b = compute_breadth({"a": rising}, lookback=2)
    # warm-up bars 0,1 have no prior window -> 0; bars 2-4 are new highs -> +1
    assert list(b) == [0, 0, 1, 1, 1]


def test_falling_symbol_makes_new_lows():
    falling = _frame(highs=[14, 13, 12, 11, 10], lows=[13, 12, 11, 10, 9])
    b = compute_breadth({"a": falling}, lookback=2)
    assert list(b) == [0, 0, -1, -1, -1]


def test_rising_and_falling_net_to_zero():
    rising = _frame(highs=[10, 11, 12, 13, 14], lows=[9, 10, 11, 12, 13])
    falling = _frame(highs=[14, 13, 12, 11, 10], lows=[13, 12, 11, 10, 9])
    b = compute_breadth({"a": rising, "b": falling}, lookback=2)
    assert list(b) == [0, 0, 0, 0, 0]


def test_breadth_union_index_and_missing_bars_are_zero():
    a = _frame(highs=[10, 11, 12], lows=[9, 10, 11])
    # b starts one hour later -> its first timestamp is outside a's index
    b_df = _frame(highs=[20, 21, 22], lows=[19, 20, 21])
    b_df.index = b_df.index + pd.Timedelta(hours=1)
    b = compute_breadth({"a": a, "b": b_df}, lookback=2)
    assert len(b) == 4                      # union of the two 3-bar indices
    assert not b.isna().any()               # missing bars filled with 0


def test_compute_breadth_empty():
    assert compute_breadth({}, lookback=10).empty


# --- breadth_blocks ---------------------------------------------------------

def test_breadth_blocks_semantics():
    # min_net 0: long needs breadth>0, short needs breadth<0
    assert breadth_blocks("buy", 3.0, 0.0) is False
    assert breadth_blocks("buy", 0.0, 0.0) is True
    assert breadth_blocks("buy", -3.0, 0.0) is True
    assert breadth_blocks("sell", -3.0, 0.0) is False
    assert breadth_blocks("sell", 0.0, 0.0) is True
    # min_net 2: needs a clear majority
    assert breadth_blocks("buy", 2.0, 2.0) is True     # not strictly > 2
    assert breadth_blocks("buy", 3.0, 2.0) is False
    # unknown regime (NaN) never blocks
    assert breadth_blocks("buy", float("nan"), 0.0) is False
    assert breadth_blocks("sell", None, 0.0) is False


# --- universe membership ----------------------------------------------------

def test_is_universe_member():
    assert is_universe_member("nvidia_h1")
    assert is_universe_member("NVIDIA")
    assert is_universe_member("goog.24h")
    assert not is_universe_member("btcusd_h1")
    assert not is_universe_member("eurusd")
    assert not is_universe_member("jpn225ft_h1")


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


def test_breadth_series_ignored_when_off():
    cfg = _donch_cfg()
    df = _wavy(400)
    base = bt.run_backtest(df, cfg)
    # passing breadth with the gate OFF must not change anything
    zero = pd.Series(0.0, index=df.index)
    same = bt.run_backtest(df, cfg, breadth=zero)
    assert same["n"] == base["n"]


def test_breadth_zero_min_net_zero_blocks_everything():
    cfg = _donch_cfg()
    cfg.breadth.use = True
    cfg.breadth.min_net = 0.0
    df = _wavy(400)
    base = bt.run_backtest(df, cfg)
    # breadth == 0 everywhere: long needs >0, short needs <0 -> both blocked
    zero = pd.Series(0.0, index=df.index)
    gated = bt.run_backtest(df, cfg, breadth=zero)
    assert base["n"] > 0
    assert gated["n"] == 0


def test_breadth_positive_keeps_only_longs_negative_only_shorts():
    cfg = _donch_cfg()
    cfg.breadth.use = True
    df = _wavy(400)
    base = bt.run_backtest(df, cfg)
    pos = bt.run_backtest(df, cfg, breadth=pd.Series(10.0, index=df.index))
    neg = bt.run_backtest(df, cfg, breadth=pd.Series(-10.0, index=df.index))
    # base takes both sides; +breadth admits only longs, -breadth only shorts
    assert {t.side for t in base["trades"]} == {"buy", "sell"}
    assert pos["n"] > 0 and all(t.side == "buy" for t in pos["trades"])
    assert neg["n"] > 0 and all(t.side == "sell" for t in neg["trades"])

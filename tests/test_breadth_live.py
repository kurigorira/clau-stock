import logging
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader import executor as executor_mod  # noqa: E402
from gold_trader.breadth import discover_universe, live_net_breadth  # noqa: E402
from gold_trader.config import Config  # noqa: E402
from gold_trader.executor import Executor  # noqa: E402


# --- discover_universe ------------------------------------------------------

def test_discover_universe_filters_and_dedupes():
    names = ["EURUSD", "XAUUSD", "NVIDIA.24h", "NVIDIA", "AAPL", "BTCUSD", "Boeing"]
    got = discover_universe(names)
    # non-members dropped; NVIDIA venue duplicate deduped to the shortest name
    assert got == ["NVIDIA", "AAPL", "Boeing"]


def test_discover_universe_keeps_24h_when_only_feed():
    assert discover_universe(["NVIDIA.24h", "GS"]) == ["NVIDIA.24h", "GS"]


def test_discover_universe_empty():
    assert discover_universe(["EURUSD", "US500"]) == []


# --- live_net_breadth -------------------------------------------------------

BAR_T = pd.Timestamp("2025-06-02 15:00", tz="UTC")
LB = 5


def _feed(highs, lows, end=BAR_T, forming=True):
    """OHLCV frame ending at `end`; appends a still-forming bar when asked."""
    n = len(highs)
    idx = pd.date_range(end=end, periods=n, freq="h", tz="UTC")
    df = pd.DataFrame(
        {"open": lows, "high": highs, "low": lows,
         "close": [(h + l) / 2 for h, l in zip(highs, lows)], "volume": 100},
        index=idx,
    )
    if forming:
        nxt = df.iloc[[-1]].copy()
        nxt.index = [end + pd.Timedelta(hours=1)]
        df = pd.concat([df, nxt])
    return df


def test_live_net_breadth_counts_highs_and_lows():
    feeds = {
        # last closed bar breaks above the prior 5-bar high -> +1
        "UP": _feed([10, 10, 10, 10, 10, 11], [9, 9, 9, 9, 9, 9.5]),
        # breaks below the prior low -> -1
        "DN": _feed([10, 10, 10, 10, 10, 10], [9, 9, 9, 9, 9, 8]),
        # inside bar -> 0
        "FLAT": _feed([10, 10, 10, 10, 10, 10], [9, 9, 9, 9, 9, 9]),
    }
    net = live_net_breadth(lambda s, tf, n: feeds[s], list(feeds), LB, BAR_T)
    assert net == 0.0  # +1 -1 +0
    assert live_net_breadth(lambda s, tf, n: feeds["UP"], ["UP"], LB, BAR_T) == 1.0


def test_live_net_breadth_skips_stale_and_short_feeds():
    stale = _feed([10] * 6, [9] * 5 + [8], end=BAR_T - pd.Timedelta(hours=3))
    short = _feed([10, 11], [9, 9.5])

    def fetch(s, tf, n):
        if s == "ERR":
            raise RuntimeError("no rates")
        return {"STALE": stale, "SHORT": short}[s]

    assert live_net_breadth(fetch, ["STALE", "SHORT", "ERR"], LB, BAR_T) == 0.0


def test_live_net_breadth_ignores_forming_bar():
    # the forming bar spikes to a huge high; only the closed bar may count
    df = _feed([10, 10, 10, 10, 10, 10], [9, 9, 9, 9, 9, 9], forming=False)
    spike = df.iloc[[-1]].copy()
    spike.index = [BAR_T + pd.Timedelta(hours=1)]
    spike["high"] = 99.0
    df = pd.concat([df, spike])
    assert live_net_breadth(lambda s, tf, n: df, ["X"], LB, BAR_T) == 0.0


# --- Executor._breadth_value ------------------------------------------------

def _executor() -> Executor:
    cfg = Config()
    cfg.symbol = "AAPL"
    cfg.breadth.use = True
    cfg.breadth.lookback = LB
    return Executor(cfg, logging.getLogger("test"), account="1")


def test_executor_breadth_value_and_cache():
    executor_mod._BREADTH_CACHE.clear()
    ex = _executor()
    up = _feed([10, 10, 10, 10, 10, 11], [9, 9, 9, 9, 9, 9.5])
    calls = {"fetch": 0}

    def fake_fetch(sym, tf, n):
        calls["fetch"] += 1
        return up

    with patch("gold_trader.executor.mt5_client.list_symbols",
               return_value=["AAPL", "NVIDIA", "EURUSD"]), \
         patch("gold_trader.executor.mt5_client.fetch_ohlcv", fake_fetch):
        assert ex._breadth_value(BAR_T) == 2.0        # both members made highs
        n_first = calls["fetch"]
        assert ex._breadth_value(BAR_T) == 2.0        # cached: no new fetches
        assert calls["fetch"] == n_first
        # a second executor in the same process reuses the cached value
        ex2 = _executor()
        with patch("gold_trader.executor.mt5_client.list_symbols",
                   return_value=["AAPL", "NVIDIA"]):
            assert ex2._breadth_value(BAR_T) == 2.0
        assert calls["fetch"] == n_first


def test_executor_breadth_value_none_without_universe():
    executor_mod._BREADTH_CACHE.clear()
    ex = _executor()
    with patch("gold_trader.executor.mt5_client.list_symbols",
               return_value=["EURUSD", "XAUUSD"]):
        assert ex._breadth_value(BAR_T) is None       # no US stocks on broker


def test_executor_breadth_value_none_on_discovery_failure():
    executor_mod._BREADTH_CACHE.clear()
    ex = _executor()
    with patch("gold_trader.executor.mt5_client.list_symbols",
               side_effect=RuntimeError("terminal gone")):
        assert ex._breadth_value(BAR_T) is None

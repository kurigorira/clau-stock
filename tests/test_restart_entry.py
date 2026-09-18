import logging
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader.config import Config  # noqa: E402
from gold_trader.executor import Executor  # noqa: E402


def _bars(n=600):
    idx = pd.date_range("2026-09-01", periods=n, freq="h", tz="UTC")
    rng = np.random.default_rng(3)
    close = 100 + np.cumsum(rng.standard_normal(n) * 0.3 + 0.02)
    return pd.DataFrame(
        {"open": close, "high": close + 0.4, "low": close - 0.4,
         "close": close, "volume": 1000}, index=idx,
    )


def _executor():
    cfg = Config()
    cfg.symbol = "TEST"
    cfg.strategy = "macd"
    cfg.macd.use_h4_filter = False
    cfg.filters.adx_min = 0.0
    cfg.filters.atr_pct_min = 0.0
    cfg.filters.atr_pct_max = 1.0
    cfg.session.trade_days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    return Executor(cfg, logging.getLogger("t"), account="1")


def _step(ex, df, orders):
    """One step with everything but the order call stubbed out."""
    with patch("gold_trader.executor.mt5_client.fetch_ohlcv", return_value=df), \
         patch("gold_trader.executor.mt5_client.open_positions", return_value=[]), \
         patch("gold_trader.executor.mt5_client.account_equity", return_value=1_000_000.0), \
         patch("gold_trader.executor.mt5_client.symbol_meta", return_value={
             "point": 0.01, "digits": 2, "trade_tick_value": 1.0,
             "trade_tick_size": 0.01, "volume_min": 0.1, "volume_max": 100.0,
             "volume_step": 0.1, "stops_level": 0}), \
         patch("gold_trader.executor.mt5_client.symbol_tick", return_value=(100.0, 100.0)), \
         patch("gold_trader.executor.mt5_client.positions_total_count", return_value=0), \
         patch("gold_trader.executor.mt5_client.today_closed_pnl", return_value=(0.0, 0)), \
         patch("gold_trader.executor.mt5_client.modify_position_sl", return_value=None), \
         patch("gold_trader.executor.mt5_client.market_order",
               side_effect=lambda **kw: orders.append(kw) or SimpleNamespace(
                   order=1, price=100.0, volume=kw["volume"])):
        ex.step()


def _first_entry_bar(df):
    """Find a window whose last closed bar produces an entry."""
    ex = _executor()
    for end in range(300, len(df)):
        orders = []
        ex._last_bar_time = None
        # prime, then offer the same window again so the second call may trade
        _step(ex, df.iloc[:end], orders)
        ex._last_bar_time = df.index[end - 2] - pd.Timedelta(hours=1)
        _step(ex, df.iloc[:end], orders)
        if orders:
            return end
    return None


def test_first_bar_after_start_does_not_enter():
    df = _bars()
    end = _first_entry_bar(df)
    assert end is not None, "fixture produced no entry at all"

    # a freshly started executor sees that same bar and must NOT trade it:
    # it cannot know whether it already acted on it before the restart
    fresh, orders = _executor(), []
    _step(fresh, df.iloc[:end], orders)
    assert orders == []
    # ...and it remembers the bar, so it is not re-offered
    assert fresh._last_bar_time == df.index[end - 2]


def test_a_genuinely_new_bar_still_enters():
    df = _bars()
    end = _first_entry_bar(df)
    ex, orders = _executor(), []
    _step(ex, df.iloc[:end], orders)          # primes, no order
    assert orders == []
    ex._last_bar_time = df.index[end - 2] - pd.Timedelta(hours=1)
    _step(ex, df.iloc[:end], orders)          # now the bar is new
    assert len(orders) == 1

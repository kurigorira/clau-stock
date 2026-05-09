import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader.backtest import run_backtest  # noqa: E402
from gold_trader.config import Config  # noqa: E402


def _trend_then_reverse() -> pd.DataFrame:
    n = 200
    idx = pd.date_range("2025-01-01", periods=n, freq="h", tz="UTC")
    half = n // 2
    up = np.linspace(1800, 1900, half)
    down = np.linspace(1900, 1820, n - half)
    close = np.concatenate([up, down])
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 100,
        },
        index=idx,
    )


def test_backtest_runs_and_returns_summary():
    cfg = Config()
    cfg.trend.ema_length = 20
    cfg.trend.ema_slope_lookback = 5
    cfg.breakout.donchian_length = 10
    cfg.breakout.exit_donchian_length = 5
    cfg.breakout.atr_buffer_mult = 0.0
    cfg.filters.adx_min = 0.0
    cfg.filters.atr_pct_min = 0.0
    cfg.filters.atr_pct_max = 1.0
    result = run_backtest(_trend_then_reverse(), cfg)
    assert "n" in result
    assert result["n"] >= 1
    assert isinstance(result["total_pnl_price"], float)

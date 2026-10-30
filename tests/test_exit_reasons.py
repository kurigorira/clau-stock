import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader import backtest as bt  # noqa: E402
from gold_trader.backtest import Trade, exit_reason_breakdown  # noqa: E402
from gold_trader.config import Config  # noqa: E402
from gold_trader.strategy import Signal  # noqa: E402


def _trade(reason: str, pnl: float, bars: int = 5) -> Trade:
    t0 = pd.Timestamp("2025-01-01", tz="UTC")
    return Trade(
        side="buy", entry_time=t0, entry_price=100.0, exit_time=t0,
        exit_price=100.0 + pnl, stop=95.0, pnl_price=pnl, reason=reason, bars_held=bars,
    )


def test_exit_reason_breakdown_aggregates_per_reason():
    trades = [
        _trade("tp", 10.0, bars=8),
        _trade("tp", 12.0, bars=6),
        _trade("sl", -5.0, bars=3),
        _trade("channel", 2.0, bars=4),
        _trade("channel", -1.0, bars=5),
    ]
    b = exit_reason_breakdown(trades)
    assert b["tp"]["n"] == 2
    assert abs(b["tp"]["pnl"] - 22.0) < 1e-9
    assert b["tp"]["win_rate"] == 1.0
    assert abs(b["tp"]["avg_bars_held"] - 7.0) < 1e-9
    assert b["sl"]["n"] == 1
    assert b["channel"]["n"] == 2
    assert b["channel"]["win_rate"] == 0.5


def test_exit_reason_breakdown_omits_missing_reasons():
    b = exit_reason_breakdown([_trade("sl", -5.0)])
    assert set(b) == {"sl"}


def _h1(n: int, start: float = 1000.0, step: float = 0.5) -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=n, freq="h", tz="UTC")
    close = start + np.arange(n) * step
    return pd.DataFrame(
        {"open": close - 0.2, "high": close + 1.0, "low": close - 1.0,
         "close": close, "volume": 100},
        index=idx,
    )


def test_summary_includes_exit_reasons_key():
    result = bt.run_backtest(_h1(400), Config())  # donchian
    assert "exit_reasons" in result


def test_fib_tp_exit_recorded_as_tp_reason():
    df = _h1(300, start=1000.0, step=0.5)  # noqa: F841 (kept for clarity)
    cfg = Config()
    cfg.strategy = "fibonacci"
    fired = {}

    def fake_entry(df_h1, df_h4, c):
        if fired:
            return Signal(None, 0.0, 0.0, 0.0)
        fired["x"] = True
        close = float(df_h1["close"].iloc[-1])
        return Signal("buy", stop=close - 50.0, entry_ref=close, atr=1.0, tp=close + 5.0)

    with patch.object(bt, "evaluate_fib_entry", side_effect=fake_entry):
        result = bt.run_backtest(df, cfg)

    assert result["n"] == 1
    assert result["trades"][0].reason == "tp"
    assert result["exit_reasons"]["tp"]["n"] == 1


def test_donchian_exits_recorded_with_valid_reasons():
    # steady uptrend (breakout entries fire) then a crash (stops hit).
    # step 1.0 > the 0.5 high-offset so close clears the prior-bar high.
    up = np.arange(220) * 1.0 + 1000.0
    down = up[-1] - np.arange(1, 60) * 3.0
    close = np.concatenate([up, down])
    idx = pd.date_range("2025-01-01", periods=len(close), freq="h", tz="UTC")
    df = pd.DataFrame(
        {"open": close - 0.5, "high": close + 0.5, "low": close - 0.5,
         "close": close, "volume": 100},
        index=idx,
    )
    cfg = Config()
    cfg.trend.ema_length = 20
    cfg.filters.adx_min = 0.0
    cfg.filters.atr_pct_min = 0.0
    cfg.filters.atr_pct_max = 1.0
    result = bt.run_backtest(df, cfg)
    assert result["n"] >= 1
    # donchian never sets a TP, so no trade may exit via "tp"
    for t in result["trades"]:
        assert t.reason in ("sl", "channel")
    assert "tp" not in result["exit_reasons"]
    assert result["trades"][0].bars_held > 0

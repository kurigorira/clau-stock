import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader import backtest as bt  # noqa: E402
from gold_trader.config import Config  # noqa: E402
from gold_trader.data import resample_ohlcv  # noqa: E402
from gold_trader.strategy import Signal  # noqa: E402


def _h1(n: int, start: float = 1000.0, step: float = 0.5) -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=n, freq="h", tz="UTC")
    close = start + np.arange(n) * step
    return pd.DataFrame(
        {
            "open": close - 0.2,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 100,
        },
        index=idx,
    )


def _fib_cfg() -> Config:
    cfg = Config()
    cfg.strategy = "fibonacci"
    return cfg


def test_resample_ohlcv_aggregates_h4():
    df = _h1(8)
    h4 = resample_ohlcv(df, "4h")
    assert len(h4) == 2
    assert h4["open"].iloc[0] == df["open"].iloc[0]
    assert h4["close"].iloc[0] == df["close"].iloc[3]
    assert h4["high"].iloc[0] == df["high"].iloc[:4].max()
    assert h4["low"].iloc[0] == df["low"].iloc[:4].min()
    assert h4["volume"].iloc[0] == df["volume"].iloc[:4].sum()


def test_backtest_fib_smoke_runs_clean():
    result = bt.run_backtest(_h1(600), _fib_cfg())
    assert set(result) >= {"trades", "n", "win_rate", "total_pnl_price"}


def test_backtest_fib_tp_exit_uses_tp_price():
    df = _h1(300, start=1000.0, step=0.5)  # steadily rising: TP will be tagged
    cfg = _fib_cfg()
    entry_bar_time = {}

    def fake_entry(df_h1, df_h4, c):
        # fire exactly one buy on the first evaluated bar
        if entry_bar_time:
            return Signal(None, 0.0, 0.0, 0.0)
        t = df_h1.index[-1]
        entry_bar_time["t"] = t
        close = float(df_h1["close"].iloc[-1])
        return Signal(
            "buy", stop=close - 50.0, entry_ref=close, atr=1.0, tp=close + 5.0
        )

    with patch.object(bt, "evaluate_fib_entry", side_effect=fake_entry):
        result = bt.run_backtest(df, cfg)

    assert result["n"] == 1
    trade = result["trades"][0]
    expected_tp = trade.entry_price + 5.0
    assert abs(trade.exit_price - expected_tp) < 1e-9
    assert trade.pnl_price > 0


def test_backtest_fib_sl_beats_tp_when_both_touch():
    # falling market: the forced long's SL is hit; ensure SL price is used
    df = _h1(300, start=1000.0, step=-0.5)
    cfg = _fib_cfg()
    fired = {}

    def fake_entry(df_h1, df_h4, c):
        if fired:
            return Signal(None, 0.0, 0.0, 0.0)
        fired["t"] = True
        close = float(df_h1["close"].iloc[-1])
        # stop and tp both inside the very next bar's range
        return Signal(
            "buy", stop=close - 0.6, entry_ref=close, atr=1.0, tp=close + 0.4
        )

    with patch.object(bt, "evaluate_fib_entry", side_effect=fake_entry):
        result = bt.run_backtest(df, cfg)

    assert result["n"] == 1
    trade = result["trades"][0]
    assert abs(trade.exit_price - trade.stop) < 1e-9  # SL, not TP
    assert trade.pnl_price < 0


def test_backtest_fib_no_lookahead_h4_slice():
    """The H4 frame handed to the entry function must only contain bars that
    fully closed before the current H1 bar closed."""
    df = _h1(200)
    cfg = _fib_cfg()
    violations = []

    def spy_entry(df_h1, df_h4, c):
        t_h1 = df_h1.index[-1]
        if len(df_h4) and df_h4.index[-1] > t_h1 - pd.Timedelta(hours=3):
            violations.append((t_h1, df_h4.index[-1]))
        return Signal(None, 0.0, 0.0, 0.0)

    with patch.object(bt, "evaluate_fib_entry", side_effect=spy_entry):
        bt.run_backtest(df, cfg)

    assert not violations

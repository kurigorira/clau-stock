import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader.config import Config  # noqa: E402
from gold_trader.executor import Executor  # noqa: E402


@dataclass
class FakePosition:
    ticket: int
    type: int          # 0 = buy, 1 = sell
    sl: float
    symbol: str = "XAUUSD"
    volume: float = 0.01
    magic: int = 0
    tp: float = 0.0


def _closed_bars(n: int = 60, price: float = 2000.0) -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=n, freq="h", tz="UTC")
    close = np.full(n, price) + np.arange(n) * 0.1
    return pd.DataFrame(
        {
            "open": close - 0.5,
            "high": close + 2.0,
            "low": close - 2.0,
            "close": close,
            "volume": 100,
        },
        index=idx,
    )


def _executor() -> Executor:
    cfg = Config()
    cfg.symbol = "XAUUSD"
    return Executor(cfg, logging.getLogger("test"), account="1")


def test_sweep_attaches_sl_to_unprotected_buy():
    ex = _executor()
    pos = FakePosition(ticket=1, type=0, sl=0.0)
    with patch("gold_trader.executor.mt5_client.open_positions", return_value=[pos]), patch(
        "gold_trader.executor.mt5_client.modify_position_sl"
    ) as modify:
        ex._ensure_stop_losses(_closed_bars())
    modify.assert_called_once()
    p, stop = modify.call_args[0]
    assert p is pos
    close = float(_closed_bars()["close"].iloc[-1])
    assert stop < close  # buy stop sits below price


def test_sweep_attaches_sl_above_price_for_sell():
    ex = _executor()
    pos = FakePosition(ticket=2, type=1, sl=0.0)
    with patch("gold_trader.executor.mt5_client.open_positions", return_value=[pos]), patch(
        "gold_trader.executor.mt5_client.modify_position_sl"
    ) as modify:
        ex._ensure_stop_losses(_closed_bars())
    _, stop = modify.call_args[0]
    close = float(_closed_bars()["close"].iloc[-1])
    assert stop > close  # sell stop sits above price


def test_sweep_ignores_protected_positions():
    ex = _executor()
    pos = FakePosition(ticket=3, type=0, sl=1980.0)
    with patch("gold_trader.executor.mt5_client.open_positions", return_value=[pos]), patch(
        "gold_trader.executor.mt5_client.modify_position_sl"
    ) as modify:
        ex._ensure_stop_losses(_closed_bars())
    modify.assert_not_called()


def test_sweep_survives_modify_failure():
    ex = _executor()
    pos = FakePosition(ticket=4, type=0, sl=0.0)
    with patch("gold_trader.executor.mt5_client.open_positions", return_value=[pos]), patch(
        "gold_trader.executor.mt5_client.modify_position_sl",
        side_effect=RuntimeError("stops_level too close"),
    ):
        ex._ensure_stop_losses(_closed_bars())  # must not raise


def test_sweep_skips_when_atr_unusable():
    ex = _executor()
    pos = FakePosition(ticket=5, type=0, sl=0.0)
    # perfectly flat bars -> true range 0 -> ATR 0 -> a zero-distance stop
    # would sit ON the price, so the sweep must skip and retry later
    n = 30
    idx = pd.date_range("2025-01-01", periods=n, freq="h", tz="UTC")
    flat = pd.DataFrame(
        {"open": 2000.0, "high": 2000.0, "low": 2000.0, "close": 2000.0, "volume": 100},
        index=idx,
    )
    with patch("gold_trader.executor.mt5_client.open_positions", return_value=[pos]), patch(
        "gold_trader.executor.mt5_client.modify_position_sl"
    ) as modify:
        ex._ensure_stop_losses(flat)
    modify.assert_not_called()

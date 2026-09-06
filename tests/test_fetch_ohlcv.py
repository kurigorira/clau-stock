import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader import mt5_client  # noqa: E402


class FakeInfo:
    def __init__(self, visible):
        self.visible = visible


class FakeMT5:
    """copy_rates_from_pos fails until the symbol is selected - the terminal's
    real behaviour for a symbol that is known but not in Market Watch."""

    TIMEFRAME_M1 = 1

    def __init__(self, *, known=True, visible=False, serves_after_select=True):
        self._known = known
        self._visible = visible
        self._serves_after_select = serves_after_select
        self.select_calls: list[str] = []
        self.rate_calls = 0

    def symbol_info(self, symbol):
        return FakeInfo(self._visible) if self._known else None

    def symbol_select(self, symbol, enable):
        self.select_calls.append(symbol)
        if not self._known:
            return False
        self._visible = True
        return True

    def copy_rates_from_pos(self, symbol, tf, start, n):
        self.rate_calls += 1
        if not self._visible or not self._serves_after_select:
            return None
        return [
            {"time": 1756000000 + 60 * i, "open": 1.0, "high": 2.0, "low": 0.5,
             "close": 1.5, "tick_volume": 10}
            for i in range(n)
        ]

    def last_error(self):
        return (-1, "Terminal: Call failed")


def _fetch(fake, symbol="EA", n=3):
    with patch("gold_trader.mt5_client._mt5", return_value=fake):
        return mt5_client.fetch_ohlcv(symbol, "M1", n)


def test_hidden_symbol_is_selected_then_served():
    fake = FakeMT5(visible=False)
    df = _fetch(fake)
    assert fake.select_calls == ["EA"]      # selected once
    assert fake.rate_calls == 2             # failed, then retried
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert len(df) == 3


def test_visible_symbol_is_not_reselected():
    fake = FakeMT5(visible=True)
    _fetch(fake)
    assert fake.select_calls == []
    assert fake.rate_calls == 1


def test_unknown_symbol_raises_without_selecting():
    fake = FakeMT5(known=False, visible=False)
    with pytest.raises(RuntimeError, match="no rates for EA M1"):
        _fetch(fake)
    assert fake.select_calls == []          # symbol_info None -> nothing to select


def test_still_empty_after_select_raises_once():
    fake = FakeMT5(visible=False, serves_after_select=False)
    with pytest.raises(RuntimeError, match="Terminal: Call failed"):
        _fetch(fake)
    assert fake.rate_calls == 2             # one retry only, no loop


def test_ensure_symbol_visible_reports_state():
    with patch("gold_trader.mt5_client._mt5", return_value=FakeMT5(visible=True)):
        assert mt5_client.ensure_symbol_visible("EA") is True
    with patch("gold_trader.mt5_client._mt5", return_value=FakeMT5(known=False)):
        assert mt5_client.ensure_symbol_visible("NOPE") is False

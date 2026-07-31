import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader import mt5_client  # noqa: E402
from gold_trader.config import Config  # noqa: E402
from gold_trader.executor import Executor  # noqa: E402


@dataclass
class FakeTick:
    bid: float
    ask: float


@dataclass
class FakeResult:
    retcode: int
    order: int = 1
    price: float = 100.0
    volume: float = 0.1


class FakeMT5:
    """Enough of the MetaTrader5 surface for market_order."""
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    TRADE_ACTION_DEAL = 1
    ORDER_TIME_GTC = 0
    ORDER_FILLING_IOC = 1
    TRADE_RETCODE_DONE = 10009
    TRADE_RETCODE_MARKET_CLOSED = 10018
    TRADE_RETCODE_OFF_QUOTES = 10021
    TRADE_RETCODE_PRICE_OFF = 10020
    TRADE_RETCODE_TRADE_DISABLED = 10017
    TRADE_RETCODE_INVALID_VOLUME = 10014

    def __init__(self, tick, retcode=TRADE_RETCODE_DONE):
        self._tick = tick
        self._retcode = retcode

    def symbol_info_tick(self, symbol):
        return self._tick

    def order_send(self, request):
        return FakeResult(self._retcode)


def _order(fake):
    with patch("gold_trader.mt5_client._mt5", return_value=fake):
        return mt5_client.market_order(
            symbol="JNJ", side="buy", volume=0.1, sl=90.0, tp=None,
            magic=1, deviation=20, comment="t",
        )


def test_market_closed_retcode_raises_marketclosed():
    fake = FakeMT5(FakeTick(99.0, 100.0), FakeMT5.TRADE_RETCODE_MARKET_CLOSED)
    with pytest.raises(mt5_client.MarketClosedError):
        _order(fake)


@pytest.mark.parametrize("retcode", [10018, 10021, 10020, 10017])
def test_every_not_trading_retcode_is_marketclosed(retcode):
    with pytest.raises(mt5_client.MarketClosedError):
        _order(FakeMT5(FakeTick(99.0, 100.0), retcode))


def test_a_real_rejection_still_raises_runtimeerror():
    # a wrong request must NOT be swallowed as "market closed"
    fake = FakeMT5(FakeTick(99.0, 100.0), FakeMT5.TRADE_RETCODE_INVALID_VOLUME)
    with pytest.raises(RuntimeError) as exc:
        _order(fake)
    assert not isinstance(exc.value, mt5_client.MarketClosedError)


def test_missing_tick_is_marketclosed():
    with pytest.raises(mt5_client.MarketClosedError):
        _order(FakeMT5(None))


def test_zero_price_is_marketclosed():
    # quotes go to 0 outside hours on some feeds — must not send an order at 0
    with pytest.raises(mt5_client.MarketClosedError):
        _order(FakeMT5(FakeTick(0.0, 0.0)))


def test_successful_order_still_returns_ticket():
    assert _order(FakeMT5(FakeTick(99.0, 100.0)))["ticket"] == 1


# --- session gate -----------------------------------------------------------

def test_us_session_window_excludes_closed_hours():
    from datetime import datetime, time, timezone
    cfg = Config()
    cfg.session.start_utc = time(13, 30)
    cfg.session.end_utc = time(21, 0)
    cfg.session.trade_days = ["Mon", "Tue", "Wed", "Thu", "Fri"]
    ex = Executor(cfg, logging.getLogger("test"))
    assert ex._in_session(datetime(2026, 7, 29, 18, 0, tzinfo=timezone.utc))
    assert not ex._in_session(datetime(2026, 7, 29, 6, 0, tzinfo=timezone.utc))
    assert not ex._in_session(datetime(2026, 7, 29, 23, 0, tzinfo=timezone.utc))
    assert not ex._in_session(datetime(2026, 8, 1, 18, 0, tzinfo=timezone.utc))  # Sat


def test_default_session_is_still_all_hours():
    # gold/FX configs must be unaffected by the US-equity fleet default
    ex = Executor(Config(), logging.getLogger("test"))
    from datetime import datetime, timezone
    assert ex._in_session(datetime(2026, 8, 1, 3, 0, tzinfo=timezone.utc))

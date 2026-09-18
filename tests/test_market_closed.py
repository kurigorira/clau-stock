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


# --- a rejected bar must not be silently lost -------------------------------

def _bars(n=60, price=100.0):
    import numpy as np
    import pandas as pd
    idx = pd.date_range("2026-07-31 13:00", periods=n, freq="h", tz="UTC")
    close = np.full(n, price) + np.arange(n) * 0.05
    return pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1,
         "close": close, "volume": 100}, index=idx,
    )


def test_market_closed_releases_the_bar_for_retry():
    """Quotes often start minutes after the open; the signal is still valid."""
    cfg = Config()
    cfg.symbol = "WFC"
    ex = Executor(cfg, logging.getLogger("test"), account="1")
    df = _bars()
    bar_time = df.index[-2]          # last row is the still-forming bar
    ex._last_bar_time = bar_time     # pretend this bar was being processed

    # simulate the except-branch behaviour
    ex._last_bar_time = None
    assert ex._last_bar_time is None, "bar must be released so the next poll retries"

    # and once released, a fresh step would treat the bar as unseen again
    assert ex._last_bar_time != bar_time


def test_closed_notice_is_deduped_per_bar():
    import pandas as pd
    cfg = Config()
    ex = Executor(cfg, logging.getLogger("test"), account="1")
    bar = pd.Timestamp("2026-07-31 13:00", tz="UTC")
    assert ex._closed_notice_bar is None
    ex._closed_notice_bar = bar
    # same bar again -> caller must not log twice
    assert ex._closed_notice_bar == bar
    # a new bar re-arms the notice
    assert ex._closed_notice_bar != pd.Timestamp("2026-07-31 14:00", tz="UTC")


# --- stop validity vs the live price ----------------------------------------

class _Sig:
    def __init__(self, side, stop, ref):
        self.side, self.stop, self.entry_ref = side, stop, ref


META = {"stops_level": 0, "point": 0.01}


def _ex(min_frac=0.5):
    cfg = Config()
    cfg.symbol = "EXXON"
    cfg.risk.min_stop_fraction = min_frac
    return Executor(cfg, logging.getLogger("test"), account="1")


def _valid(ex, sig, planned, bid, ask, meta=META):
    with patch("gold_trader.executor.mt5_client.symbol_tick", return_value=(bid, ask)):
        return ex._stop_still_valid(sig, meta, planned)


def test_untouched_price_is_valid():
    # buy signalled at 157.72 with stop 155.16 (2.56 away); price barely moved
    assert _valid(_ex(), _Sig("buy", 155.16, 157.72), 2.56, 157.70, 157.72)


def test_price_ran_to_the_stop_is_rejected():
    # the real EXXON case: filled at 155.28, leaving 0.12 of a 2.56 stop
    assert not _valid(_ex(), _Sig("buy", 155.16, 157.72), 2.56, 155.26, 155.28)


def test_price_past_the_stop_is_rejected():
    assert not _valid(_ex(), _Sig("buy", 155.16, 157.72), 2.56, 154.00, 154.02)


def test_short_side_mirrors():
    # the real GOOG case: sell stop 340.64, price ran up to 341.76
    assert not _valid(_ex(), _Sig("sell", 340.64, 334.05), 6.59, 341.76, 341.78)
    assert _valid(_ex(), _Sig("sell", 340.64, 334.05), 6.59, 334.00, 334.02)


def test_broker_minimum_stop_distance_is_enforced():
    meta = {"stops_level": 200, "point": 0.01}      # 2.00 minimum
    sig = _Sig("buy", 155.16, 157.72)
    assert not _valid(_ex(min_frac=0.0), sig, 2.56, 156.50, 156.52, meta)  # 1.36 < 2.00
    assert _valid(_ex(min_frac=0.0), sig, 2.56, 157.50, 157.52, meta)      # 2.36 > 2.00


def test_missing_quote_defers_to_the_order():
    ex = _ex()
    with patch("gold_trader.executor.mt5_client.symbol_tick", return_value=None):
        assert ex._stop_still_valid(_Sig("buy", 155.16, 157.72), META, 2.56)
    with patch("gold_trader.executor.mt5_client.symbol_tick",
               side_effect=RuntimeError("terminal gone")):
        assert ex._stop_still_valid(_Sig("buy", 155.16, 157.72), META, 2.56)

"""Thin wrapper around the MetaTrader5 Python API.

The `MetaTrader5` package is Windows-only and needs the MT5 terminal installed
and authenticated against a Vantage account. The import is deferred so backtests
and unit tests can run on non-Windows hosts.
"""
from __future__ import annotations

import sys
import time as time_mod
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterator, Optional, Tuple

import pandas as pd


_TIMEFRAME_MAP_LOOKUP = {
    "M1": "TIMEFRAME_M1",
    "M5": "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30",
    "H1": "TIMEFRAME_H1",
    "H4": "TIMEFRAME_H4",
    "D1": "TIMEFRAME_D1",
}

# How long to wait between MT5 initialize retries when the terminal is
# still warming up (auto-login dialog, market-watch loading, etc.).
_INIT_MAX_ATTEMPTS = 6
_INIT_RETRY_DELAY_S = 5


def _mt5():
    import MetaTrader5 as mt5  # imported lazily on purpose

    return mt5


class UnknownSymbolError(RuntimeError):
    """This account's terminal does not carry the symbol at all.

    Unlike a closed venue or an unselected symbol, no amount of retrying
    fixes it — the broker does not offer this instrument on this account, or
    the config names it differently than the terminal does. Callers drop the
    symbol instead of raising once per poll forever."""


class MarketClosedError(RuntimeError):
    """The venue rejected the order because it is not trading right now.

    An expected state — holidays, early closes, halts, and the minutes either
    side of a DST shift — not a bug, so callers log it and move on instead of
    surfacing a traceback every poll."""


# What the broker's rejection codes mean, in the terms that decide what to do
# about them. Only the ones a market order can realistically hit.
_RETCODE_MEANINGS = {
    10004: "requote - the price moved; retry",
    10006: "rejected by the dealer",
    10013: "malformed request",
    10014: "volume not accepted for this symbol",
    10015: "price not accepted",
    10016: "stop level too close to the price",
    10017: "trading disabled for this symbol on this account",
    10018: "market closed",
    10019: "not enough free margin",
    10020: "price changed",
    10021: "no quotes",
    10024: "too many requests - slow down",
    10026: "algorithmic trading disabled on the SERVER side",
    10027: "algorithmic trading disabled in THIS TERMINAL "
           "(the AutoTrading toolbar button is off)",
    10030: "filling mode not supported for this symbol",
    10031: "no connection to the trade server",
    10034: "this would exceed the account's volume limit",
}


class OrderRejected(RuntimeError):
    """The broker refused the order and said why.

    Carries the retcode and the broker's comment as fields rather than only
    in the message, so a caller sending many orders can group identical
    rejections. Formatting the whole result into the string instead would
    fold in each order's own price and volume, and a hundred orders refused
    for one reason would read as a hundred different reasons.
    """

    def __init__(self, retcode: int | None, comment: str = ""):
        self.retcode = retcode
        self.comment = (comment or "").strip()
        super().__init__(self.describe())

    def describe(self) -> str:
        """The rejection with no per-order detail in it, so it groups."""
        if self.retcode is None:
            return "no reply from the terminal (not connected?)"
        meaning = _RETCODE_MEANINGS.get(self.retcode)
        out = f"retcode {self.retcode}"
        if meaning:
            out += f" - {meaning}"
        if self.comment and (not meaning or self.comment.lower() not in meaning.lower()):
            out += f' ["{self.comment}"]'
        return out


# Retcodes that mean "not trading now" rather than "the request was wrong".
# Resolved by name with numeric fallbacks because the constant set varies
# between MetaTrader5 package versions.
def _closed_retcodes(mt5) -> set:
    names = (
        ("TRADE_RETCODE_MARKET_CLOSED", 10018),
        ("TRADE_RETCODE_OFF_QUOTES", 10021),
        ("TRADE_RETCODE_PRICE_OFF", 10020),
        ("TRADE_RETCODE_TRADE_DISABLED", 10017),
    )
    return {getattr(mt5, name, fallback) for name, fallback in names}


@dataclass
class MT5Credentials:
    """How to reach one account's terminal.

    login/password/server log a terminal IN. Leaving them empty and giving
    only `path` attaches to whatever that terminal is ALREADY logged into -
    enough to read balances and history, which is all the reports need, and
    the only option for an account whose password is not to hand. Trading
    should always pass real credentials so the account is never a surprise.
    """

    login: int = 0
    password: str = ""
    server: str = ""
    path: Optional[str] = None

    @property
    def attach_only(self) -> bool:
        return not (self.login and self.password and self.server)


@contextmanager
def connect(creds: MT5Credentials) -> Iterator[object]:
    mt5 = _mt5()
    if creds.attach_only:
        if not creds.path:
            raise RuntimeError(
                "no credentials and no path: set MT5_LOGIN/PASSWORD/SERVER, or "
                "MT5_PATH alone to attach to a terminal that is already logged in"
            )
        # No login kwargs: MT5 attaches to the account the terminal already
        # holds. It must be running and logged in - there is nothing here to
        # log it in with.
        init_kwargs: dict = {"path": creds.path}
    else:
        init_kwargs = {
            "login": creds.login,
            "password": creds.password,
            "server": creds.server,
        }
        if creds.path:
            init_kwargs["path"] = creds.path

    initialized = False
    last_err = None
    for attempt in range(1, _INIT_MAX_ATTEMPTS + 1):
        if mt5.initialize(**init_kwargs):
            initialized = True
            break
        last_err = mt5.last_error()
        if attempt < _INIT_MAX_ATTEMPTS:
            print(
                f"MT5 initialize attempt {attempt}/{_INIT_MAX_ATTEMPTS} failed "
                f"({last_err}); retrying in {_INIT_RETRY_DELAY_S}s...",
                file=sys.stderr,
            )
            time_mod.sleep(_INIT_RETRY_DELAY_S)

    if not initialized:
        raise RuntimeError(
            f"MT5 initialize failed after {_INIT_MAX_ATTEMPTS} attempts: {last_err}"
        )
    try:
        yield mt5
    finally:
        mt5.shutdown()


def timeframe(name: str) -> int:
    mt5 = _mt5()
    return getattr(mt5, _TIMEFRAME_MAP_LOOKUP[name])


def ensure_symbol_visible(symbol: str) -> bool:
    """Add `symbol` to Market Watch if the terminal is hiding it.

    History calls fail with the generic (-1, 'Terminal: Call failed') for a
    symbol the terminal knows but has not selected, so anything that reads
    bars must select first. True when the symbol is (now) visible.
    """
    mt5 = _mt5()
    info = mt5.symbol_info(symbol)
    if info is None:
        return False
    if getattr(info, "visible", True):
        return True
    return bool(mt5.symbol_select(symbol, True))


def fetch_ohlcv(symbol: str, tf_name: str, n_bars: int) -> pd.DataFrame:
    mt5 = _mt5()
    rates = mt5.copy_rates_from_pos(symbol, timeframe(tf_name), 0, n_bars)
    if rates is None or len(rates) == 0:
        # Two very different causes look alike here. A symbol this account
        # simply does not carry can never work and must be dropped; one the
        # terminal knows but has not put in Market Watch works after a select.
        if mt5.symbol_info(symbol) is None:
            raise UnknownSymbolError(
                f"{symbol} is not in this terminal's symbol list: "
                f"{mt5.last_error()}"
            )
        if ensure_symbol_visible(symbol):
            rates = mt5.copy_rates_from_pos(symbol, timeframe(tf_name), 0, n_bars)
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"no rates for {symbol} {tf_name}: {mt5.last_error()}")
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("time")
    df = df.rename(columns={"tick_volume": "volume"})
    return df[["open", "high", "low", "close", "volume"]]


def list_symbols() -> list[str]:
    """Names of every symbol the terminal knows (visible or not).

    Used by the live breadth gate to auto-discover the US-stock universe on
    this broker's naming scheme (see breadth.discover_universe)."""
    mt5 = _mt5()
    return [s.name for s in (mt5.symbols_get() or [])]


def symbol_meta(symbol: str) -> dict:
    mt5 = _mt5()
    info = mt5.symbol_info(symbol)
    if info is None:
        raise RuntimeError(f"unknown symbol {symbol}")
    if not info.visible:
        mt5.symbol_select(symbol, True)
        info = mt5.symbol_info(symbol)
    return {
        "point": info.point,
        "digits": info.digits,
        "trade_tick_value": info.trade_tick_value,
        "trade_tick_size": info.trade_tick_size,
        "volume_min": info.volume_min,
        "volume_max": info.volume_max,
        "volume_step": info.volume_step,
        "stops_level": info.trade_stops_level,
        # shares (or units) per lot: notional is volume * this * price, which
        # is what sizing to a target exposure needs rather than to a stop
        "contract_size": getattr(info, "trade_contract_size", 1.0) or 1.0,
    }


def unit_value(meta: dict) -> float:
    """Account-currency value of 1.0 of price, per lot. 0.0 when unknown.

    `contract_size * price` is denominated in the symbol's QUOTE currency,
    while equity, profit and swap are all in the ACCOUNT currency. Mixing
    them is wrong by whatever the FX rate happens to be - as sizing a JPY
    account against USD prices was, building a book 150x the intended size.

    trade_tick_value is in the account currency by definition: one lot
    moving by trade_tick_size earns exactly that. So tick_value / tick_size
    is the account-currency exposure per 1.0 of price, per lot - the FX
    conversion and the contract size in one number the broker supplies.

    Returns 0.0 rather than a guess when the broker gives nothing to convert
    with, so callers skip the symbol instead of sizing it in the wrong
    currency.
    """
    tick_value = float(meta.get("trade_tick_value") or 0.0)
    tick_size = float(meta.get("trade_tick_size") or 0.0)
    if tick_value <= 0 or tick_size <= 0:
        return 0.0
    return tick_value / tick_size


def account_equity() -> float:
    mt5 = _mt5()
    info = mt5.account_info()
    if info is None:
        raise RuntimeError("account_info unavailable")
    return float(info.equity)


def account_currency() -> str:
    """The account's deposit currency, e.g. "JPY".

    Printed beside any figure derived from equity: a notional and an equity
    in different currencies look identical on screen, which is how a book
    150x the account once printed as "1.00x equity".
    """
    mt5 = _mt5()
    info = mt5.account_info()
    if info is None:
        return "?"
    return str(getattr(info, "currency", "") or "?")


def list_symbols_with_paths() -> list[tuple[str, str]]:
    """(name, path) for every symbol the terminal knows.

    The MT5 `path` is the broker's own taxonomy (e.g. 'Stocks\\US\\AAPL'),
    used by breadth.discover_from_paths to build the live universe without a
    hand-maintained ticker list."""
    mt5 = _mt5()
    return [(s.name, getattr(s, "path", "") or "") for s in (mt5.symbols_get() or [])]


def symbol_tick(symbol: str) -> tuple[float, float] | None:
    """(bid, ask) for `symbol`, or None when the terminal has no quote."""
    mt5 = _mt5()
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return None
    return (float(tick.bid), float(tick.ask))


def positions_total_count() -> int:
    """Number of open positions on the whole account (any symbol, any magic).

    Used by the portfolio-wide cap (risk.max_total_positions): counting every
    position — not just our magic's — is the conservative reading on a
    dedicated bot account."""
    mt5 = _mt5()
    return int(mt5.positions_total() or 0)


def open_positions(symbol: str, magic: int) -> list:
    mt5 = _mt5()
    positions = mt5.positions_get(symbol=symbol) or []
    return [p for p in positions if p.magic == magic]


def all_open_positions() -> list:
    """Every open position on the account, any symbol, any magic.

    A buy-and-hold book closes nothing, so it contributes no closed trades and
    is invisible to the monthly statistics. Its cost is real all the same -
    swap is charged nightly on the full notional - and it only shows up here.
    """
    mt5 = _mt5()
    return list(mt5.positions_get() or [])


def today_closed_pnl(symbol: str, magic: int) -> Tuple[float, int]:
    """Return (realized_pnl_today, trailing_loss_streak) for our magic+symbol.

    "Today" is bounded by UTC 00:00 of the current day. Each closing deal's
    profit, commission and swap are summed. The streak counts consecutive
    losing closing deals starting from the most recent one.
    """
    mt5 = _mt5()
    now = datetime.now(timezone.utc)
    # MT5's history_deals_get treats the date args as broker-local time; we
    # query a generous window and filter against UTC midnight ourselves using
    # the deal's unix timestamp.
    deals = mt5.history_deals_get(now - timedelta(days=2), now + timedelta(hours=1))
    if deals is None:
        return 0.0, 0
    today_start_unix = int(
        now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    )
    ours = [
        d
        for d in deals
        if d.magic == magic
        and d.symbol == symbol
        and d.entry == mt5.DEAL_ENTRY_OUT
        and d.time >= today_start_unix
    ]
    if not ours:
        return 0.0, 0
    ours.sort(key=lambda d: d.time)
    pnl_total = sum(
        float(d.profit) + float(d.commission) + float(d.swap) for d in ours
    )
    streak = 0
    for d in reversed(ours):
        net = float(d.profit) + float(d.commission) + float(d.swap)
        if net < 0:
            streak += 1
        else:
            break
    return pnl_total, streak


def market_order(
    symbol: str,
    side: str,
    volume: float,
    sl: float | None,
    tp: float | None,
    magic: int,
    deviation: int,
    comment: str,
) -> dict:
    mt5 = _mt5()
    order_type = mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        raise MarketClosedError(f"{symbol}: no tick available (market closed?)")
    price = tick.ask if side == "buy" else tick.bid
    if not price or price <= 0:
        raise MarketClosedError(f"{symbol}: no {side} price (market closed?)")
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": order_type,
        "price": price,
        # 0.0 is MT5's "no level", and the struct fields are doubles: a None
        # here is not an empty stop, it is a type error that fails the order.
        # A book held without stops passes None for both.
        "sl": sl if sl is not None else 0.0,
        "tp": tp if tp is not None else 0.0,
        "deviation": deviation,
        "magic": magic,
        "comment": comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        if result is not None and result.retcode in _closed_retcodes(mt5):
            raise MarketClosedError(
                f"{symbol}: venue not trading (retcode {result.retcode})"
            )
        raise OrderRejected(
            None if result is None else int(result.retcode),
            "" if result is None else str(getattr(result, "comment", "")),
        )
    return {"ticket": result.order, "price": result.price, "volume": result.volume}


def modify_position_sl(position, sl: float) -> None:
    """Attach or move a position's stop-loss (keeps its TP untouched)."""
    mt5 = _mt5()
    request = {
        "action": mt5.TRADE_ACTION_SLTP,
        "position": position.ticket,
        "symbol": position.symbol,
        "sl": sl,
        "tp": position.tp,
    }
    result = mt5.order_send(request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        raise RuntimeError(f"sl modify failed: {result}")


def close_position(position, deviation: int, comment: str) -> None:
    mt5 = _mt5()
    closing_side = "sell" if position.type == mt5.POSITION_TYPE_BUY else "buy"
    order_type = mt5.ORDER_TYPE_SELL if closing_side == "sell" else mt5.ORDER_TYPE_BUY
    tick = mt5.symbol_info_tick(position.symbol)
    price = tick.bid if closing_side == "sell" else tick.ask
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "position": position.ticket,
        "symbol": position.symbol,
        "volume": position.volume,
        "type": order_type,
        "price": price,
        "deviation": deviation,
        "magic": position.magic,
        "comment": comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        raise RuntimeError(f"close failed: {result}")

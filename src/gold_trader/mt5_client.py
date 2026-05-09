"""Thin wrapper around the MetaTrader5 Python API.

The `MetaTrader5` package is Windows-only and needs the MT5 terminal installed
and authenticated against a Vantage account. The import is deferred so backtests
and unit tests can run on non-Windows hosts.
"""
from __future__ import annotations

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


def _mt5():
    import MetaTrader5 as mt5  # imported lazily on purpose

    return mt5


@dataclass
class MT5Credentials:
    login: int
    password: str
    server: str
    path: Optional[str] = None


@contextmanager
def connect(creds: MT5Credentials) -> Iterator[object]:
    mt5 = _mt5()
    init_kwargs: dict = {
        "login": creds.login,
        "password": creds.password,
        "server": creds.server,
    }
    if creds.path:
        init_kwargs["path"] = creds.path
    if not mt5.initialize(**init_kwargs):
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
    try:
        yield mt5
    finally:
        mt5.shutdown()


def timeframe(name: str) -> int:
    mt5 = _mt5()
    return getattr(mt5, _TIMEFRAME_MAP_LOOKUP[name])


def fetch_ohlcv(symbol: str, tf_name: str, n_bars: int) -> pd.DataFrame:
    mt5 = _mt5()
    rates = mt5.copy_rates_from_pos(symbol, timeframe(tf_name), 0, n_bars)
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"no rates for {symbol} {tf_name}: {mt5.last_error()}")
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("time")
    df = df.rename(columns={"tick_volume": "volume"})
    return df[["open", "high", "low", "close", "volume"]]


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
    }


def account_equity() -> float:
    mt5 = _mt5()
    info = mt5.account_info()
    if info is None:
        raise RuntimeError("account_info unavailable")
    return float(info.equity)


def open_positions(symbol: str, magic: int) -> list:
    mt5 = _mt5()
    positions = mt5.positions_get(symbol=symbol) or []
    return [p for p in positions if p.magic == magic]


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
    sl: float,
    tp: float | None,
    magic: int,
    deviation: int,
    comment: str,
) -> dict:
    mt5 = _mt5()
    order_type = mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL
    tick = mt5.symbol_info_tick(symbol)
    price = tick.ask if side == "buy" else tick.bid
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": order_type,
        "price": price,
        "sl": sl,
        "tp": tp if tp is not None else 0.0,
        "deviation": deviation,
        "magic": magic,
        "comment": comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        raise RuntimeError(f"order_send failed: {result}")
    return {"ticket": result.order, "price": result.price, "volume": result.volume}


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

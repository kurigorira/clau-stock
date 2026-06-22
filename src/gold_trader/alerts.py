"""Price-change alerts: surface symbols that moved more than threshold_pct
over the last window_minutes of M1 bars.

Designed to run in its own process (`scripts/run_alerts.py`), independent of
the trading executor, so alerts keep firing even if the bot is paused.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class PriceChange:
    symbol: str
    change_pct: float
    current_price: float
    prev_price: float


def evaluate_change(symbol: str, bars_m1: pd.DataFrame, window_minutes: int) -> PriceChange | None:
    """Return the % change between the most recent close and the close
    ``window_minutes`` bars earlier. Returns None when there aren't enough bars
    or the older close is zero/NaN.

    Both endpoints are *closed* M1 bars; the still-forming bar is left to the
    caller to slice off before passing in the frame.
    """
    if len(bars_m1) < window_minutes + 1:
        return None
    current = float(bars_m1["close"].iloc[-1])
    prev = float(bars_m1["close"].iloc[-1 - window_minutes])
    if prev == 0 or pd.isna(prev) or pd.isna(current):
        return None
    change_pct = (current - prev) / prev * 100.0
    return PriceChange(symbol=symbol, change_pct=change_pct, current_price=current, prev_price=prev)


def should_alert(change_pct: float, threshold_pct: float) -> bool:
    return abs(change_pct) >= threshold_pct

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


@dataclass
class Streak:
    """N consecutive daily bars that each moved at least the threshold."""
    symbol: str
    changes: list[float]   # oldest first, one % per day
    current_price: float
    start_price: float     # close before the first counted day

    @property
    def days(self) -> int:
        return len(self.changes)

    @property
    def total_pct(self) -> float:
        """Compounded move over the streak, not the sum of the daily moves.

        Two +5% days are +10.25%, not +10%: the second day's move is on the
        bigger number. Over a long streak the difference stops being pedantic.
        """
        if self.start_price == 0:
            return 0.0
        return (self.current_price - self.start_price) / self.start_price * 100.0

    @property
    def direction(self) -> str:
        return "up" if self.changes and self.changes[-1] > 0 else "down"


def daily_changes(bars_d1: pd.DataFrame) -> list[float]:
    """Close-to-close % change for each bar that has a predecessor.

    Close-to-close rather than open-to-close: an overnight gap is part of the
    day's move for anyone holding through it, and the gap is often most of it.
    """
    closes = bars_d1["close"].astype(float).tolist()
    out: list[float] = []
    for prev, cur in zip(closes, closes[1:]):
        if prev == 0 or pd.isna(prev) or pd.isna(cur):
            out.append(float("nan"))
        else:
            out.append((cur - prev) / prev * 100.0)
    return out


def evaluate_streak(
    symbol: str,
    bars_d1: pd.DataFrame,
    threshold_pct: float,
    days: int = 2,
    same_direction: bool = True,
) -> Streak | None:
    """`days` consecutive daily bars each moving at least `threshold_pct`.

    With `same_direction` (the default) the moves must all share a sign, so
    this fires on a sustained run - two 5% days up is a 10.25% move - and not
    on a symbol that swung 5% up then 5% down, which is volatility rather
    than a move and nets out near zero.

    `bars_d1` must contain only CLOSED daily bars; the caller slices off the
    still-forming one, or today's partial move would count as a day.
    """
    if days < 1 or len(bars_d1) < days + 1:
        return None
    changes = daily_changes(bars_d1)[-days:]
    if len(changes) < days:
        return None
    if any(pd.isna(c) for c in changes):
        return None
    if not all(abs(c) >= threshold_pct for c in changes):
        return None
    if same_direction and not (
        all(c > 0 for c in changes) or all(c < 0 for c in changes)
    ):
        return None

    closes = bars_d1["close"].astype(float).tolist()
    return Streak(
        symbol=symbol,
        changes=changes,
        current_price=closes[-1],
        start_price=closes[-1 - days],
    )

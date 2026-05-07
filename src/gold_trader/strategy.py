from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from .config import Config


@dataclass
class Signal:
    side: Optional[str]   # "buy", "sell", or None
    stop: float
    entry_ref: float
    atr: float


def _ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


def _atr(df: pd.DataFrame, length: int) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / length, adjust=False).mean()


def add_indicators(df: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    out = df.copy()
    out["ema_trend"] = _ema(out["close"], cfg.trend.ema_length)
    out["atr"] = _atr(out, cfg.risk.atr_length)
    n = cfg.breakout.donchian_length
    m = cfg.breakout.exit_donchian_length
    # shift(1) so the channel reflects bars *prior* to the current one
    out["donch_high"] = out["high"].rolling(n).max().shift(1)
    out["donch_low"] = out["low"].rolling(n).min().shift(1)
    out["exit_high"] = out["high"].rolling(m).max().shift(1)
    out["exit_low"] = out["low"].rolling(m).min().shift(1)
    return out


def evaluate_last_bar(df: pd.DataFrame, cfg: Config) -> Signal:
    """Return entry signal computed on the most recent *closed* bar."""
    if len(df) < max(cfg.trend.ema_length, cfg.breakout.donchian_length) + 2:
        return Signal(None, 0.0, 0.0, 0.0)

    bar = df.iloc[-1]
    close = float(bar["close"])
    ema = float(bar["ema_trend"])
    atr = float(bar["atr"])
    high_ref = float(bar["donch_high"])
    low_ref = float(bar["donch_low"])

    if np.isnan(atr) or np.isnan(high_ref) or np.isnan(low_ref) or np.isnan(ema):
        safe_atr = 0.0 if np.isnan(atr) else atr
        return Signal(None, 0.0, close, safe_atr)

    stop_dist = cfg.risk.atr_stop_mult * atr
    if close > high_ref and close > ema:
        return Signal("buy", stop=close - stop_dist, entry_ref=close, atr=atr)
    if close < low_ref and close < ema:
        return Signal("sell", stop=close + stop_dist, entry_ref=close, atr=atr)
    return Signal(None, 0.0, close, atr)


def should_exit(position_side: str, bar: pd.Series) -> bool:
    """Donchian reverse-channel exit: long exits below recent low, vice versa."""
    close = float(bar["close"])
    if position_side == "buy":
        ref = float(bar["exit_low"])
        return not np.isnan(ref) and close < ref
    ref = float(bar["exit_high"])
    return not np.isnan(ref) and close > ref

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
    # Populated when MTF filtering is on; used by the notifier in the email body.
    donch_high: float = 0.0
    donch_low: float = 0.0
    h4_trend_dir: int = 0   # +1 / -1 / 0


def h4_trend_dir(df_h4: pd.DataFrame, cfg: Config) -> int:
    """Return +1 / -1 / 0 from an indicator-enriched H4 frame.

    Uses the *last fully closed* H4 bar (df_h4.iloc[-1] after the executor
    has already dropped the still-forming bar). +1 when ema_slope > 0 and
    ADX >= adx_min, -1 when ema_slope < 0 and ADX >= adx_min, else 0.
    """
    if len(df_h4) == 0:
        return 0
    bar = df_h4.iloc[-1]
    ema_slope = float(bar["ema_slope"])
    adx = float(bar["adx"])
    if np.isnan(ema_slope) or np.isnan(adx):
        return 0
    if adx < cfg.filters.adx_min:
        return 0
    if ema_slope > 0:
        return 1
    if ema_slope < 0:
        return -1
    return 0


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


def _adx(df: pd.DataFrame, length: int) -> pd.Series:
    """Wilder's ADX, smoothed via EMA(alpha=1/length)."""
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    prev_high = high.shift(1)
    prev_low = low.shift(1)

    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    up_move = high - prev_high
    down_move = prev_low - low
    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
        index=df.index,
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
        index=df.index,
    )
    atr = tr.ewm(alpha=1 / length, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / length, adjust=False).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1 / length, adjust=False).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / length, adjust=False).mean()


def add_indicators(df: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    out = df.copy()
    out["ema_trend"] = _ema(out["close"], cfg.trend.ema_length)
    out["ema_slope"] = (
        out["ema_trend"] - out["ema_trend"].shift(cfg.trend.ema_slope_lookback)
    )
    out["atr"] = _atr(out, cfg.risk.atr_length)
    out["atr_pct"] = out["atr"] / out["close"]
    out["adx"] = _adx(out, cfg.filters.adx_length)
    n = cfg.breakout.donchian_length
    m = cfg.breakout.exit_donchian_length
    # shift(1) so the channel reflects bars *prior* to the current one
    out["donch_high"] = out["high"].rolling(n).max().shift(1)
    out["donch_low"] = out["low"].rolling(n).min().shift(1)
    out["exit_high"] = out["high"].rolling(m).max().shift(1)
    out["exit_low"] = out["low"].rolling(m).min().shift(1)
    return out


def evaluate_last_bar(
    df: pd.DataFrame,
    cfg: Config,
    df_h4: Optional[pd.DataFrame] = None,
) -> Signal:
    """Return entry signal computed on the most recent *closed* bar.

    Conditions (long; short is symmetric):
      1. close > Donchian-high(N).shift(1) + ATR * atr_buffer_mult
      2. close > EMA(trend)
      3. EMA(trend) now > EMA(trend) ema_slope_lookback bars ago
      4. ADX(adx_length) >= adx_min
      5. atr_pct_min <= ATR / close <= atr_pct_max
      6. (when df_h4 is given and cfg.trend.higher_timeframe is set)
         signal side agrees with the H4 trend direction
    Daily-loss / consecutive-loss filters are enforced at the executor layer
    because they need account history. df_h4=None preserves the legacy
    H1-only behaviour for tests that don't supply an H4 frame.
    """
    warmup = max(
        cfg.trend.ema_length,
        cfg.breakout.donchian_length,
        cfg.filters.adx_length * 2,
        cfg.trend.ema_slope_lookback + 1,
    )
    if len(df) < warmup + 2:
        return Signal(None, 0.0, 0.0, 0.0)

    bar = df.iloc[-1]
    close = float(bar["close"])
    ema = float(bar["ema_trend"])
    ema_slope = float(bar["ema_slope"])
    atr = float(bar["atr"])
    atr_pct = float(bar["atr_pct"])
    adx = float(bar["adx"])
    high_ref = float(bar["donch_high"])
    low_ref = float(bar["donch_low"])

    if any(
        np.isnan(x)
        for x in (atr, atr_pct, adx, ema, ema_slope, high_ref, low_ref)
    ):
        safe_atr = 0.0 if np.isnan(atr) else atr
        return Signal(None, 0.0, close, safe_atr)

    f = cfg.filters
    if not (f.atr_pct_min <= atr_pct <= f.atr_pct_max):
        return Signal(None, 0.0, close, atr)
    if adx < f.adx_min:
        return Signal(None, 0.0, close, atr)

    buffer = cfg.breakout.atr_buffer_mult * atr
    stop_dist = cfg.risk.atr_stop_mult * atr

    h4_dir = h4_trend_dir(df_h4, cfg) if (df_h4 is not None and cfg.trend.higher_timeframe) else 0
    mtf_on = df_h4 is not None and cfg.trend.higher_timeframe

    if close > high_ref + buffer and close > ema and ema_slope > 0:
        if mtf_on and h4_dir != 1:
            return Signal(None, 0.0, close, atr, high_ref, low_ref, h4_dir)
        return Signal("buy", close - stop_dist, close, atr, high_ref, low_ref, h4_dir)
    if close < low_ref - buffer and close < ema and ema_slope < 0:
        if mtf_on and h4_dir != -1:
            return Signal(None, 0.0, close, atr, high_ref, low_ref, h4_dir)
        return Signal("sell", close + stop_dist, close, atr, high_ref, low_ref, h4_dir)
    return Signal(None, 0.0, close, atr, high_ref, low_ref, h4_dir)


def should_exit(position_side: str, bar: pd.Series) -> bool:
    """Donchian reverse-channel exit: long exits below recent low, vice versa."""
    close = float(bar["close"])
    if position_side == "buy":
        ref = float(bar["exit_low"])
        return not np.isnan(ref) and close < ref
    ref = float(bar["exit_high"])
    return not np.isnan(ref) and close > ref
